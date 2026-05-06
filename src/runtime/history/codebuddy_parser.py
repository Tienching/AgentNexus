# -*- coding: utf-8 -*-
"""CodeBuddy history parser.

Reads ~/.codebuddy/projects/{encoded_path}/*.jsonl files and converts them
to the project's unified AGUI data models.

CodeBuddy JSONL entry format (differs from Claude Code):
  - Top-level fields: id, timestamp, type, role, content, sessionId, cwd, parentId
  - type="message" + role="user"/"assistant": chat messages
  - type="function_call": tool invocation (callId, name, arguments)
  - type="function_call_result": tool output (callId, name, output, status)
  - type="topic": session title (topic field)
  - type="reasoning": model thinking (rawContent[].type="reasoning_text")
  - type="file-history-snapshot": skip
  - Content blocks use "input_text" (user) / "output_text" (assistant)
"""

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from ..models.session import (
    ContentSegment,
    MessageStatus,
    SessionMeta,
    SessionStatus,
    StoredMessage,
    StoredToolCall,
    ToolCallStatus,
)
from .base_parser import BaseHistoryParser, HistorySessionDetail, decode_encoded_project_path
from .cache_store import CacheStore, stat_paths

logger = logging.getLogger(__name__)

# Prefixes for user messages that should be skipped (internal/system messages)
_SKIP_USER_PREFIXES = (
    "<command-name>",
    "<command-message>",
    "<local-command-stdout>",
    "<system-reminder>",
    "Caveat:",
    "Warmup",
)

# Entry types that are not user-facing messages
_SKIP_ENTRY_TYPES = frozenset({
    "file-history-snapshot",
    "reasoning",
})


class CodeBuddyHistoryParser(BaseHistoryParser):
    """Parser for CodeBuddy's native JSONL session files."""

    @property
    def provider_name(self) -> str:
        return "codebuddy"

    def list_projects(self, config_path: Path) -> List[Dict[str, object]]:
        """Discover available project paths from CodeBuddy's projects directory.

        CodeBuddy stores sessions in {config_path}/projects/{encoded_path}/*.jsonl
        where encoded_path is: /home/bob/proj -> home-bob-proj (no leading dash).
        """
        projects_dir = config_path / "projects"
        if not projects_dir.is_dir():
            return []

        results = []
        for subdir in sorted(projects_dir.iterdir()):
            if not subdir.is_dir():
                continue
            encoded_name = subdir.name
            decoded_path = self._decode_project_path(encoded_name)
            if not decoded_path:
                continue

            jsonl_files = [f for f in subdir.glob("*.jsonl") if not f.name.startswith("agent-")]
            if not jsonl_files:
                continue

            latest_mtime = max(f.stat().st_mtime for f in jsonl_files)
            results.append({
                "path": decoded_path,
                "provider": "codebuddy",
                "session_count": len(jsonl_files),
                "last_active": int(latest_mtime * 1000),
            })

        return results

    @staticmethod
    def _decode_project_path(encoded: str) -> Optional[str]:
        """Decode CodeBuddy's encoded project directory name back to a path.

        CodeBuddy encoding: /home/bob/my-proj -> home-bob-my-proj (no leading dash)
        Uses filesystem probing to disambiguate '-' as '/' vs literal '-'.
        """
        if not encoded:
            return None
        segments = encoded.split("-")
        if not segments:
            return None
        return decode_encoded_project_path(segments, leading_slash=True)

    def list_all_sessions(self, config_path: Path, linux_user: Optional[str] = None) -> List[SessionMeta]:
        """List ALL CodeBuddy sessions across all projects (no project filter).

        Scans every subdirectory under {config_path}/projects/ and attaches
        the decoded project path as exec_dir on each SessionMeta.

        Args:
            config_path: Provider config directory (e.g. ~/.codebuddy)
            linux_user: Optional Linux username to tag on each session
        """
        projects_dir = config_path / "projects"
        if not projects_dir.is_dir():
            return []

        all_sessions: List[SessionMeta] = []
        for subdir in projects_dir.iterdir():
            if not subdir.is_dir():
                continue
            decoded_path = self._decode_project_path(subdir.name)
            sessions = self._list_sessions_in_dir(subdir)
            for s in sessions:
                s.exec_dir = decoded_path or subdir.name
                if linux_user and not s.exec_user:
                    s.exec_user = linux_user
            all_sessions.extend(sessions)

        all_sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return all_sessions

    def list_sessions(self, config_path: Path, project_path: str) -> List[SessionMeta]:
        """List CodeBuddy sessions for a specific project.

        Scans {config_path}/projects/{encoded_path}/*.jsonl,
        groups entries by sessionId, and returns session metadata.
        """
        encoded = self._encode_project_path(project_path)
        projects_dir = config_path / "projects" / encoded

        if not projects_dir.is_dir():
            return []

        return self._list_sessions_in_dir(projects_dir)

    def _list_sessions_in_dir(self, projects_dir: Path) -> List[SessionMeta]:
        """Scan a single project directory for sessions.

        Reads all *.jsonl (excluding agent-*) in projects_dir,
        groups entries by sessionId, and returns session metadata.

        Per-file parsed shards are persisted to CacheStore, so the
        second call on an unchanged directory only touches mtime/size.
        """
        jsonl_files = sorted(
            [f for f in projects_dir.glob("*.jsonl") if not f.name.startswith("agent-")],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        if not jsonl_files:
            return []

        stamps = stat_paths(jsonl_files)
        cache = CacheStore.get_default()
        try:
            cached = cache.lookup_many(self.provider_name, stamps)
        except Exception:
            logger.debug("codebuddy cache lookup failed; falling through", exc_info=True)
            cached = {}

        shards_by_file: Dict[Path, List[SessionMeta]] = {}
        to_persist: List = []
        for jsonl_file, stamp in stamps.items():
            if jsonl_file in cached:
                shards_by_file[jsonl_file] = cached[jsonl_file]
                continue
            file_shards = self._parse_file_to_shards(jsonl_file)
            shards_by_file[jsonl_file] = file_shards
            to_persist.append((jsonl_file, stamp, file_shards))

        if to_persist:
            try:
                cache.store_many(self.provider_name, to_persist)
            except Exception:
                logger.debug("codebuddy cache store failed; continuing", exc_info=True)

        return self._aggregate_shards(shards_by_file)

    def _parse_file_to_shards(self, jsonl_file: Path) -> List[SessionMeta]:
        """Parse ONE jsonl file into per-sessionId shards.

        Cross-file merging happens later in ``_aggregate_shards``.
        """
        sessions_map: Dict[str, dict] = {}

        for entry in self.safe_read_jsonl(jsonl_file):
            session_id = entry.get("sessionId")
            if not session_id:
                continue

            if session_id not in sessions_map:
                sessions_map[session_id] = {
                    "id": session_id,
                    "title": "",
                    "message_count": 0,
                    "last_activity": 0,
                    "cwd": entry.get("cwd", ""),
                    "last_user_message": "",
                    "last_assistant_message": "",
                    "model": "",
                }

            sdata = sessions_map[session_id]

            # Track timestamps
            ts_ms = self._get_timestamp_ms(entry)
            if ts_ms > sdata["last_activity"]:
                sdata["last_activity"] = ts_ms

            entry_type = entry.get("type", "")

            # Topic entries provide session title
            if entry_type == "topic":
                topic = entry.get("topic", "")
                if topic:
                    sdata["title"] = topic[:100]
                continue

            # Skip non-message entry types
            if entry_type in _SKIP_ENTRY_TYPES:
                continue

            # Skip function_call and function_call_result for counting
            if entry_type in ("function_call", "function_call_result"):
                continue

            # Only process "message" type entries
            if entry_type != "message":
                continue

            role = entry.get("role", "")
            content = entry.get("content", "")
            text = self._extract_text_from_content(content)

            # Extract model info
            provider_data = entry.get("providerData", {})
            if isinstance(provider_data, dict) and provider_data.get("model"):
                sdata["model"] = provider_data["model"]

            if role == "user" and text:
                if any(text.startswith(prefix) for prefix in _SKIP_USER_PREFIXES):
                    continue
                if text.strip().startswith('{ "'):
                    continue
                sdata["message_count"] += 1
                sdata["last_user_message"] = text[:100]

            elif role == "assistant" and text:
                if text.strip().startswith('{ "'):
                    continue
                sdata["message_count"] += 1
                sdata["last_assistant_message"] = text[:100]

        now_ms = int(time.time() * 1000)
        shards: List[SessionMeta] = []
        for sid, sdata in sessions_map.items():
            last_activity = sdata["last_activity"] or now_ms
            shards.append(SessionMeta(
                id=sid,
                thread_id=sid,
                # Pack title candidates so cross-file aggregation can
                # still resolve the best title after merge.
                title=self._pack_title_shard(
                    topic=sdata["title"],
                    last_user=sdata["last_user_message"],
                    last_assistant=sdata["last_assistant_message"],
                ),
                username="",
                provider="codebuddy",
                status=SessionStatus.COMPLETED,
                created_at=last_activity,
                updated_at=last_activity,
                message_count=sdata["message_count"],
                source="history",
            ))
        return shards

    @staticmethod
    def _pack_title_shard(topic: str, last_user: str, last_assistant: str) -> str:
        """Pack title candidates using control-char separators."""
        return "\u0001" + (topic or "") + "\u0002" + (last_user or "") + "\u0003" + (last_assistant or "")

    @staticmethod
    def _unpack_title_shard(packed: str) -> tuple:
        if not packed or not packed.startswith("\u0001"):
            return (packed or "", "", "")
        rest = packed[1:]
        try:
            topic, tail = rest.split("\u0002", 1)
            last_user, last_assistant = tail.split("\u0003", 1)
        except ValueError:
            return (rest, "", "")
        return (topic, last_user, last_assistant)

    def _aggregate_shards(
        self,
        shards_by_file: Dict[Path, List[SessionMeta]],
    ) -> List[SessionMeta]:
        """Merge per-file shards into final session list."""
        agg: Dict[str, dict] = {}

        for _file, shards in shards_by_file.items():
            for shard in shards:
                sid = shard.id
                topic, last_user, last_assistant = self._unpack_title_shard(shard.title)
                shard_activity = int(shard.updated_at or 0)
                entry = agg.get(sid)
                if entry is None:
                    agg[sid] = {
                        "topic": topic,
                        "topic_ts": shard_activity if topic else 0,
                        "last_user": last_user,
                        "last_user_ts": shard_activity if last_user else 0,
                        "last_assistant": last_assistant,
                        "last_assistant_ts": shard_activity if last_assistant else 0,
                        "message_count": int(shard.message_count or 0),
                        "last_activity": shard_activity,
                    }
                    continue

                entry["message_count"] += int(shard.message_count or 0)
                if shard_activity > entry["last_activity"]:
                    entry["last_activity"] = shard_activity

                if topic and shard_activity >= entry["topic_ts"]:
                    entry["topic"] = topic
                    entry["topic_ts"] = shard_activity
                if last_user and shard_activity >= entry["last_user_ts"]:
                    entry["last_user"] = last_user
                    entry["last_user_ts"] = shard_activity
                if last_assistant and shard_activity >= entry["last_assistant_ts"]:
                    entry["last_assistant"] = last_assistant
                    entry["last_assistant_ts"] = shard_activity

        now_ms = int(time.time() * 1000)
        sessions: List[SessionMeta] = []
        for sid, state in agg.items():
            title = state["topic"]
            if not title:
                title = state["last_user"] or state["last_assistant"] or "New Session"

            title = " ".join(title.split())

            # Skip JSON-only sessions
            if title.strip().startswith('{ "'):
                continue

            last_activity = state["last_activity"] or now_ms

            sessions.append(SessionMeta(
                id=sid,
                thread_id=sid,
                title=title[:100],
                username="",
                provider="codebuddy",
                status=SessionStatus.COMPLETED,
                created_at=last_activity,
                updated_at=last_activity,
                message_count=state["message_count"],
                source="history",
            ))

        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def get_session_detail(self, config_path: Path, session_id: str) -> Optional[HistorySessionDetail]:
        """Get full message detail for a CodeBuddy session.

        Searches all JSONL files in all project subdirectories for the given sessionId.
        """
        projects_dir = config_path / "projects"
        if not projects_dir.is_dir():
            return None

        entries = []
        found_project_subdir: Optional[Path] = None
        for project_subdir in projects_dir.iterdir():
            if not project_subdir.is_dir():
                continue
            for jsonl_file in project_subdir.glob("*.jsonl"):
                if jsonl_file.name.startswith("agent-"):
                    continue
                for entry in self.safe_read_jsonl(jsonl_file):
                    if entry.get("sessionId") == session_id:
                        entries.append(entry)
                        if found_project_subdir is None:
                            found_project_subdir = project_subdir

        if not entries:
            return None

        entries.sort(key=lambda e: self._get_timestamp_ms(e))

        messages: List[StoredMessage] = []
        tool_calls: List[StoredToolCall] = []
        # Map callId -> StoredToolCall for matching results
        tc_map: Dict[str, StoredToolCall] = {}
        current_assistant_msg_id: Optional[str] = None

        for entry in entries:
            entry_type = entry.get("type", "")
            ts_ms = self._get_timestamp_ms(entry)

            # Skip non-message metadata
            if entry_type in _SKIP_ENTRY_TYPES:
                continue

            if entry_type == "topic":
                continue

            if entry_type == "message":
                role = entry.get("role", "")
                content = entry.get("content", "")
                text = self._extract_text_from_content(content)

                if role == "user":
                    if not text or any(text.startswith(p) for p in _SKIP_USER_PREFIXES):
                        continue
                    if text.strip().startswith('{ "'):
                        continue

                    msg_id = entry.get("id") or str(uuid.uuid4())
                    messages.append(StoredMessage(
                        id=msg_id,
                        role="user",
                        content=text,
                        timestamp=ts_ms,
                        status=MessageStatus.COMPLETE,
                    ))
                    current_assistant_msg_id = None

                elif role == "assistant":
                    msg_id = entry.get("id") or str(uuid.uuid4())

                    # Skip JSON-only assistant messages
                    if text.strip().startswith('{ "'):
                        continue

                    messages.append(StoredMessage(
                        id=msg_id,
                        role="assistant",
                        content=text,
                        timestamp=ts_ms,
                        status=MessageStatus.COMPLETE,
                    ))
                    current_assistant_msg_id = msg_id

            elif entry_type == "function_call":
                call_id = entry.get("callId") or str(uuid.uuid4())
                name = entry.get("name", "unknown")
                arguments_str = entry.get("arguments", "")

                # Parse arguments JSON string
                args = {}
                if isinstance(arguments_str, str) and arguments_str:
                    try:
                        args = json.loads(arguments_str)
                    except (json.JSONDecodeError, TypeError):
                        args = {"raw": arguments_str}
                elif isinstance(arguments_str, dict):
                    args = arguments_str

                tc = StoredToolCall(
                    id=call_id,
                    tool_name=name,
                    args=args,
                    args_string=arguments_str if isinstance(arguments_str, str) else json.dumps(args, ensure_ascii=False),
                    status=ToolCallStatus.PENDING,
                    start_time=ts_ms,
                    parent_message_id=current_assistant_msg_id,
                )
                tool_calls.append(tc)
                tc_map[call_id] = tc

                # Update parent assistant message with tool_call reference
                if current_assistant_msg_id:
                    for msg in messages:
                        if msg.id == current_assistant_msg_id:
                            if msg.tool_call_ids is None:
                                msg.tool_call_ids = []
                            msg.tool_call_ids.append(call_id)

                            # Add content segment
                            if msg.content_segments is None:
                                msg.content_segments = []
                                if msg.content:
                                    msg.content_segments.append(ContentSegment(
                                        type="text", content=msg.content, sequence=0
                                    ))
                            msg.content_segments.append(ContentSegment(
                                type="tool_call",
                                tool_call_id=call_id,
                                sequence=len(msg.content_segments),
                            ))
                            break

            elif entry_type == "function_call_result":
                call_id = entry.get("callId", "")
                if call_id and call_id in tc_map:
                    tc = tc_map[call_id]
                    output = entry.get("output", {})
                    if isinstance(output, dict):
                        tc.result = output.get("text", str(output))
                    else:
                        tc.result = str(output) if output else ""
                    status = entry.get("status", "")
                    if status == "completed":
                        tc.status = ToolCallStatus.COMPLETED
                    elif status in ("failed", "error"):
                        tc.status = ToolCallStatus.FAILED
                    else:
                        tc.status = ToolCallStatus.COMPLETED
                    tc.end_time = ts_ms

        # Attach session metadata with exec_dir decoded from project subdirectory
        session_meta = None
        if found_project_subdir is not None:
            decoded_path = self._decode_project_path(found_project_subdir.name)
            if decoded_path:
                session_meta = SessionMeta(
                    id=session_id,
                    thread_id=session_id,
                    title="",
                    username="",
                    provider="codebuddy",
                    status=SessionStatus.COMPLETED,
                    source="history",
                    exec_dir=decoded_path,
                )

        return HistorySessionDetail(
            session_id=session_id,
            messages=messages,
            tool_calls=tool_calls,
            session=session_meta,
        )

    # ---- Private helpers ----

    @staticmethod
    def _encode_project_path(project_path: str) -> str:
        """Encode a project path to CodeBuddy's directory name format.

        CodeBuddy uses 'home-user-project' (no leading dash),
        unlike Claude Code which uses '-home-user-project'.
        """
        return project_path.replace("/", "-").lstrip("-")

    @staticmethod
    def _extract_text_from_content(content) -> str:
        """Extract plain text from CodeBuddy's content field.

        CodeBuddy uses input_text/output_text block types instead of Claude's text type.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type in ("input_text", "output_text", "text"):
                        parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(parts)
        return ""

    @staticmethod
    def _get_timestamp_ms(entry: dict) -> int:
        """Extract timestamp in milliseconds from a JSONL entry."""
        ts = entry.get("timestamp")
        if not ts:
            return 0
        if isinstance(ts, str):
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return int(dt.timestamp() * 1000)
            except (ValueError, TypeError):
                return 0
        if isinstance(ts, (int, float)):
            return int(ts) if ts > 1e12 else int(ts * 1000)
        return 0

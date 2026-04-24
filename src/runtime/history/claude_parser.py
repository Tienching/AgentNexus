# -*- coding: utf-8 -*-
"""Claude Code history parser.

Reads ~/.claude/projects/{encoded_path}/*.jsonl files and converts them
to the project's unified AGUI data models.
"""

import logging
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set

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
from .cache_store import CacheStore, FileStamp, stat_paths

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

# Entry types that carry no user-facing message content
_SKIP_ENTRY_TYPES = frozenset({
    "file-history-snapshot",
    "progress",
    "system",
    "queue-operation",
})


class ClaudeHistoryParser(BaseHistoryParser):
    """Parser for Claude Code's native JSONL session files."""

    @property
    def provider_name(self) -> str:
        return "claude"

    def list_projects(self, config_path: Path) -> List[Dict[str, object]]:
        """Discover available project paths from Claude's projects directory.

        Claude stores sessions in {config_path}/projects/{encoded_path}/*.jsonl
        where encoded_path is: /home/bob/proj -> -home-bob-proj
        """
        projects_dir = config_path / "projects"
        if not projects_dir.is_dir():
            return []

        results = []
        for subdir in sorted(projects_dir.iterdir()):
            if not subdir.is_dir():
                continue
            encoded_name = subdir.name
            # Decode: -home-bob-proj -> /home/bob/proj
            decoded_path = self._decode_project_path(encoded_name)
            if not decoded_path:
                continue

            # Count JSONL files and find latest mtime
            jsonl_files = [f for f in subdir.glob("*.jsonl") if not f.name.startswith("agent-")]
            if not jsonl_files:
                continue

            latest_mtime = max(f.stat().st_mtime for f in jsonl_files)
            results.append({
                "path": decoded_path,
                "provider": "claude",
                "session_count": len(jsonl_files),
                "last_active": int(latest_mtime * 1000),
            })

        return results

    @staticmethod
    def _decode_project_path(encoded: str) -> Optional[str]:
        """Decode Claude's encoded project directory name back to a path.

        Claude encoding: /home/bob/my-proj -> -home-bob-my-proj
        The problem is '-' is ambiguous: it could be '/' or literal '-'.
        We use greedy filesystem-based decoding to find the actual path.
        """
        if not encoded or not encoded.startswith("-"):
            return None

        # Split into segments (skip leading empty from the first -)
        segments = encoded[1:].split("-")
        if not segments:
            return None

        return decode_encoded_project_path(segments, leading_slash=True)

    def list_all_sessions(self, config_path: Path, linux_user: Optional[str] = None) -> List[SessionMeta]:
        """List ALL Claude sessions across all projects (no project filter).

        Scans every subdirectory under {config_path}/projects/ and attaches
        the decoded project path as exec_dir on each SessionMeta.

        Args:
            config_path: Provider config directory (e.g. ~/.claude)
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
        """List Claude sessions for a specific project.

        Scans {config_path}/projects/{encoded_path}/*.jsonl (excluding agent-*.jsonl),
        groups entries by sessionId, and returns session metadata.
        """
        encoded = self.encode_project_path(project_path)
        projects_dir = config_path / "projects" / encoded

        if not projects_dir.is_dir():
            return []

        return self._list_sessions_in_dir(projects_dir)

    def _list_sessions_in_dir(self, projects_dir: Path) -> List[SessionMeta]:
        """Scan a single project directory for Claude sessions.

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

        # ---- file-level cache lookup ----
        stamps = stat_paths(jsonl_files)
        cache = CacheStore.get_default()
        try:
            cached = cache.lookup_many(self.provider_name, stamps)
        except Exception:
            logger.debug("claude cache lookup failed; falling through", exc_info=True)
            cached = {}

        # For each file we need its sessions_map shards list; parse-on-miss
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
                logger.debug("claude cache store failed; continuing", exc_info=True)

        # ---- cross-file aggregation by sessionId ----
        return self._aggregate_shards(shards_by_file)

    def _parse_file_to_shards(self, jsonl_file: Path) -> List[SessionMeta]:
        """Parse ONE jsonl file into per-sessionId shards.

        Unlike the old in-place aggregation this returns one SessionMeta
        per distinct sessionId *seen in this file only*. Cross-file
        sessionIds are merged later in ``_aggregate_shards``.
        """
        sessions_map: Dict[str, dict] = {}

        for entry in self.safe_read_jsonl(jsonl_file):
            session_id = entry.get("sessionId")
            if not session_id:
                continue

            if session_id not in sessions_map:
                sessions_map[session_id] = {
                    "id": session_id,
                    "summary": "New Session",
                    "message_count": 0,
                    "last_activity": 0,
                    "cwd": entry.get("cwd", ""),
                    "last_user_message": "",
                    "last_assistant_message": "",
                }

            sdata = sessions_map[session_id]

            # Track timestamps
            ts_ms = self._get_timestamp_ms(entry)
            if ts_ms > sdata["last_activity"]:
                sdata["last_activity"] = ts_ms

            entry_type = entry.get("type", "")

            # Summary entries
            if entry_type == "summary":
                summary_text = entry.get("summary", "")
                if summary_text:
                    sdata["summary"] = summary_text[:100]
                continue

            # Skip non-message entry types
            if entry_type in _SKIP_ENTRY_TYPES:
                continue

            # Skip API error messages
            if entry.get("isApiErrorMessage"):
                continue

            message = entry.get("message", {})
            if not message:
                continue

            role = message.get("role", "")
            content = message.get("content", "")

            # Extract text from content
            text = self._extract_text_from_content(content)

            # Check if this user message is purely tool_result (no text)
            is_tool_result_only = (
                role == "user"
                and not text
                and isinstance(content, list)
                and any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content
                )
            )
            if is_tool_result_only:
                continue

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

        # Serialise the per-file state into SessionMeta shards. Title
        # fallback / "New Session" detection stays in the aggregator so
        # cross-file merging can still recover a real title.
        now_ms = int(time.time() * 1000)
        shards: List[SessionMeta] = []
        for sid, sdata in sessions_map.items():
            last_activity = sdata["last_activity"] or now_ms
            # We stash the raw fallback strings in the title field
            # using a tagged prefix so _aggregate_shards can tell them
            # apart from a real summary. Cheapest and keeps SessionMeta
            # schema untouched.
            summary = sdata["summary"]
            title_fallback_user = sdata["last_user_message"]
            title_fallback_assistant = sdata["last_assistant_message"]

            shards.append(SessionMeta(
                id=sid,
                thread_id=sid,
                title=self._pack_title_shard(
                    summary=summary,
                    last_user=title_fallback_user,
                    last_assistant=title_fallback_assistant,
                ),
                username="",
                provider="claude",
                status=SessionStatus.COMPLETED,
                created_at=last_activity,
                updated_at=last_activity,
                message_count=sdata["message_count"],
                source="history",
            ))
        return shards

    @staticmethod
    def _pack_title_shard(summary: str, last_user: str, last_assistant: str) -> str:
        """Pack title candidates into a shard-local string.

        Format: ``"\u0001<summary>\u0002<last_user>\u0003<last_assistant>"``
        Chosen control chars never appear in JSONL-derived text. The
        aggregator unpacks this and picks the best title per session
        after merging across files.
        """
        return "\u0001" + (summary or "") + "\u0002" + (last_user or "") + "\u0003" + (last_assistant or "")

    @staticmethod
    def _unpack_title_shard(packed: str) -> tuple:
        """Return (summary, last_user, last_assistant)."""
        if not packed or not packed.startswith("\u0001"):
            # Legacy / uncached value — treat whole string as summary
            return (packed or "", "", "")
        rest = packed[1:]
        try:
            summary, tail = rest.split("\u0002", 1)
            last_user, last_assistant = tail.split("\u0003", 1)
        except ValueError:
            return (rest, "", "")
        return (summary, last_user, last_assistant)

    def _aggregate_shards(
        self,
        shards_by_file: Dict[Path, List[SessionMeta]],
    ) -> List[SessionMeta]:
        """Merge per-file shards into final session list.

        For each sessionId we:
          * sum ``message_count`` across files
          * take ``max(last_activity)`` as updated_at
          * prefer the first non-default summary; fall back to the
            last_user / last_assistant candidate with the latest timestamp
        """
        # sessionId -> aggregated state
        agg: Dict[str, dict] = {}

        # Walk files ordered by mtime desc (Claude already sorts that way
        # when called from _list_sessions_in_dir; for safety we don't
        # rely on insertion order here — we track per-shard activity).
        for _file, shards in shards_by_file.items():
            for shard in shards:
                sid = shard.id
                summary, last_user, last_assistant = self._unpack_title_shard(shard.title)
                entry = agg.get(sid)
                shard_activity = int(shard.updated_at or 0)
                if entry is None:
                    agg[sid] = {
                        "summary": summary if summary and summary != "New Session" else "",
                        "summary_ts": shard_activity if (summary and summary != "New Session") else 0,
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

                # Prefer the most recent non-default summary
                if summary and summary != "New Session" and shard_activity >= entry["summary_ts"]:
                    entry["summary"] = summary
                    entry["summary_ts"] = shard_activity

                # Track latest last_user / last_assistant as title fallbacks
                if last_user and shard_activity >= entry["last_user_ts"]:
                    entry["last_user"] = last_user
                    entry["last_user_ts"] = shard_activity
                if last_assistant and shard_activity >= entry["last_assistant_ts"]:
                    entry["last_assistant"] = last_assistant
                    entry["last_assistant_ts"] = shard_activity

        now_ms = int(time.time() * 1000)
        sessions: List[SessionMeta] = []
        for sid, state in agg.items():
            title = state["summary"]
            if not title:
                title = state["last_user"] or state["last_assistant"] or "New Session"

            # Skip Task Master JSON sessions
            if title.strip().startswith('{ "'):
                continue

            title = " ".join(title.split())
            last_activity = state["last_activity"] or now_ms

            sessions.append(SessionMeta(
                id=sid,
                thread_id=sid,
                title=title[:100],
                username="",
                provider="claude",
                status=SessionStatus.COMPLETED,
                created_at=last_activity,
                updated_at=last_activity,
                message_count=state["message_count"],
                source="history",
            ))

        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def get_session_detail(self, config_path: Path, session_id: str) -> Optional[HistorySessionDetail]:
        """Get full message detail for a Claude session.

        Searches all JSONL files in all project subdirectories for the given sessionId.
        """
        projects_dir = config_path / "projects"
        if not projects_dir.is_dir():
            return None

        # Search across all project directories for this session
        entries = []
        agent_ids: Set[str] = set()
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
                        # Collect agent IDs from tool results
                        message = entry.get("message", {})
                        if message:
                            content = message.get("content", [])
                            if isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict):
                                        agent_id = block.get("toolUseResult", {}).get("agentId") if isinstance(block.get("toolUseResult"), dict) else None
                                        if agent_id:
                                            agent_ids.add(agent_id)

        if not entries:
            return None

        # Sort entries by timestamp
        entries.sort(key=lambda e: self._get_timestamp_ms(e))

        # Parse entries into messages and tool calls
        messages: List[StoredMessage] = []
        tool_calls: List[StoredToolCall] = []
        current_message_id: Optional[str] = None

        for entry in entries:
            if entry.get("isApiErrorMessage"):
                continue

            entry_type = entry.get("type", "")
            if entry_type in _SKIP_ENTRY_TYPES or entry_type == "summary":
                continue

            message = entry.get("message", {})
            if not message:
                continue

            role = message.get("role", "")
            content = message.get("content", "")
            ts_ms = self._get_timestamp_ms(entry)

            if role == "user":
                text = self._extract_text_from_content(content)

                # User messages that are purely tool_result blocks are not
                # independent user turns — they just carry tool output back
                # to the model.  We still need to process them later to
                # attach results to the matching StoredToolCall.
                is_tool_result_only = (
                    not text
                    and isinstance(content, list)
                    and any(
                        isinstance(b, dict) and b.get("type") == "tool_result"
                        for b in content
                    )
                )
                if is_tool_result_only:
                    continue

                if not text or any(text.startswith(p) for p in _SKIP_USER_PREFIXES):
                    continue
                if text.strip().startswith('{ "'):
                    continue

                msg_id = entry.get("uuid") or str(uuid.uuid4())
                messages.append(StoredMessage(
                    id=msg_id,
                    role="user",
                    content=text,
                    timestamp=ts_ms,
                    status=MessageStatus.COMPLETE,
                ))
                current_message_id = None

            elif role == "assistant":
                msg_id = entry.get("uuid") or str(uuid.uuid4())
                text_parts, tool_use_blocks = self._parse_assistant_content(content)

                # Build content segments
                segments: List[ContentSegment] = []
                tc_ids: List[str] = []
                seq = 0

                # Add text content
                full_text = "\n".join(text_parts) if text_parts else ""

                if full_text:
                    segments.append(ContentSegment(
                        type="text", content=full_text, sequence=seq
                    ))
                    seq += 1

                # Process tool uses
                for tu in tool_use_blocks:
                    tc_id = tu.get("id") or str(uuid.uuid4())
                    tc_ids.append(tc_id)

                    segments.append(ContentSegment(
                        type="tool_call", tool_call_id=tc_id, sequence=seq
                    ))
                    seq += 1

                    tool_calls.append(StoredToolCall(
                        id=tc_id,
                        tool_name=tu.get("name", "unknown"),
                        args=tu.get("input", {}),
                        args_string=str(tu.get("input", {})),
                        status=ToolCallStatus.COMPLETED,
                        start_time=ts_ms,
                        end_time=ts_ms,
                        parent_message_id=msg_id,
                    ))

                # Skip Task Master JSON
                if full_text.strip().startswith('{ "') and not tool_use_blocks:
                    continue

                stored_msg = StoredMessage(
                    id=msg_id,
                    role="assistant",
                    content=full_text,
                    timestamp=ts_ms,
                    status=MessageStatus.COMPLETE,
                    tool_call_ids=tc_ids if tc_ids else None,
                    content_segments=segments if segments else None,
                )
                messages.append(stored_msg)
                current_message_id = msg_id

        # Process tool results from user messages (tool_result type in content)
        for entry in entries:
            message = entry.get("message", {})
            if not message or message.get("role") != "user":
                continue
            content = message.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    tc_id = block.get("tool_use_id")
                    if tc_id:
                        # Find and update the tool call
                        for tc in tool_calls:
                            if tc.id == tc_id:
                                result_content = block.get("content", "")
                                if isinstance(result_content, list):
                                    result_content = "\n".join(
                                        b.get("text", "") for b in result_content
                                        if isinstance(b, dict) and b.get("type") == "text"
                                    )
                                tc.result = result_content
                                tc.end_time = self._get_timestamp_ms(entry)
                                break

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
                    provider="claude",
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
    def _extract_text_from_content(content) -> str:
        """Extract plain text from Claude's content field (string or content blocks array)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(parts)
        return ""

    @staticmethod
    def _parse_assistant_content(content) -> tuple:
        """Parse assistant content into text parts and tool_use blocks.

        Returns:
            (text_parts: List[str], tool_use_blocks: List[dict])
        """
        if isinstance(content, str):
            return ([content] if content else [], [])

        text_parts = []
        tool_uses = []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            text_parts.append(text)
                    elif block.get("type") == "tool_use":
                        tool_uses.append(block)
                elif isinstance(block, str):
                    text_parts.append(block)
        return (text_parts, tool_uses)

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

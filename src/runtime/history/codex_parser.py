# -*- coding: utf-8 -*-
"""Codex history parser.

Reads ~/.codex/sessions/*.jsonl files and converts them
to the project's unified AGUI data models.
"""

import logging
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
from .base_parser import BaseHistoryParser, HistorySessionDetail
from .cache_store import CacheStore, stat_paths

logger = logging.getLogger(__name__)

# Tool name mapping: Codex internal names -> display names
_TOOL_NAME_MAP = {
    "shell": "Bash",
    "shell_command": "Bash",
    "apply_patch": "Edit",
    "apply_diff": "Edit",
}


def _find_jsonl_files(directory: Path) -> List[Path]:
    """Recursively find all .jsonl files in a directory."""
    files = []
    if not directory.is_dir():
        return files
    try:
        for item in directory.rglob("*.jsonl"):
            if item.is_file():
                files.append(item)
    except OSError as e:
        logger.warning("Error scanning directory %s: %s", directory, e)
    return files


def _extract_text(content) -> str:
    """Extract text from Codex content array or string.

    Handles content formats: string, list of dicts with type=input_text/output_text/text.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("input_text") or item.get("output_text") or ""
                if text:
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


class CodexHistoryParser(BaseHistoryParser):
    """Parser for Codex's native JSONL session files."""

    @property
    def provider_name(self) -> str:
        return "codex"

    def list_projects(self, config_path: Path) -> List[Dict[str, object]]:
        """Discover available project paths from Codex session files.

        Codex stores cwd in session_meta entries. We scan all JSONL files
        and collect unique cwd values.
        """
        sessions_dir = config_path / "sessions"
        if not sessions_dir.is_dir():
            return []

        jsonl_files = _find_jsonl_files(sessions_dir)
        if not jsonl_files:
            return []

        # Collect cwd -> {session_count, last_active}
        projects: Dict[str, Dict] = {}

        for jsonl_file in jsonl_files:
            cwd = ""
            last_ts = 0
            for entry in self.safe_read_jsonl(jsonl_file, max_lines=100):
                entry_type = entry.get("type", "")
                if entry_type == "session_meta":
                    payload = entry.get("payload", {})
                    cwd = payload.get("cwd", "")
                    ts = entry.get("timestamp")
                    if ts:
                        last_ts = self._parse_timestamp_ms(ts)
                    break  # session_meta is typically the first entry

            if not cwd:
                continue

            normalized_cwd = self.normalize_path(cwd)
            if normalized_cwd not in projects:
                projects[normalized_cwd] = {"session_count": 0, "last_active": 0}
            projects[normalized_cwd]["session_count"] += 1
            if last_ts > projects[normalized_cwd]["last_active"]:
                projects[normalized_cwd]["last_active"] = last_ts

        return [
            {
                "path": path,
                "provider": "codex",
                "session_count": info["session_count"],
                "last_active": info["last_active"],
            }
            for path, info in projects.items()
        ]

    def list_all_sessions(self, config_path: Path, linux_user: Optional[str] = None) -> List[SessionMeta]:
        """List ALL Codex sessions without project_path filtering.

        Scans all JSONL files and returns every session with exec_dir set
        to the session's cwd.

        Args:
            config_path: Provider config directory (e.g. ~/.codex)
            linux_user: Optional Linux username to tag on each session
        """
        sessions_dir = config_path / "sessions"
        if not sessions_dir.is_dir():
            return []

        jsonl_files = _find_jsonl_files(sessions_dir)
        if not jsonl_files:
            return []

        sessions: List[SessionMeta] = []
        for meta in self._collect_unfiltered_metas(jsonl_files):
            if linux_user and not meta.exec_user:
                meta.exec_user = linux_user
            sessions.append(meta)

        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def list_sessions(self, config_path: Path, project_path: str) -> List[SessionMeta]:
        """List Codex sessions filtered by project_path (cwd matching).

        Scans {config_path}/sessions/ recursively for *.jsonl files.
        Reads session_meta entries to extract cwd and match against project_path.
        """
        sessions_dir = config_path / "sessions"
        if not sessions_dir.is_dir():
            return []

        jsonl_files = _find_jsonl_files(sessions_dir)
        if not jsonl_files:
            return []

        normalized_project = self.normalize_path(project_path)
        sessions: List[SessionMeta] = []
        for meta in self._collect_unfiltered_metas(jsonl_files):
            exec_dir = meta.exec_dir or ""
            if not exec_dir:
                # No cwd info in the session — can't attribute to a project
                continue
            if self.normalize_path(exec_dir) != normalized_project:
                continue
            # Strip the exec_dir so legacy callers that did not expect it
            # on this code-path still get identical objects.
            meta.exec_dir = None
            sessions.append(meta)

        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def _collect_unfiltered_metas(self, jsonl_files: List[Path]) -> List[SessionMeta]:
        """Cache-aware batch extraction of SessionMeta (one per file).

        Uses CacheStore keyed on (provider, file_path) with mtime_ns/size
        invalidation. Cache shards here are single-element lists because
        one Codex JSONL file == one session.
        """
        stamps = stat_paths(jsonl_files)
        cache = CacheStore.get_default()
        try:
            cached = cache.lookup_many(self.provider_name, stamps)
        except Exception:
            logger.debug("codex cache lookup failed; falling through", exc_info=True)
            cached = {}

        metas: List[SessionMeta] = []
        to_persist: List = []
        for jsonl_file, stamp in stamps.items():
            if jsonl_file in cached:
                metas.extend(cached[jsonl_file])
                continue
            parsed = self._parse_session_meta_unfiltered(jsonl_file)
            shard = [parsed] if parsed else []
            if shard:
                metas.append(parsed)
            to_persist.append((jsonl_file, stamp, shard))

        if to_persist:
            try:
                cache.store_many(self.provider_name, to_persist)
            except Exception:
                logger.debug("codex cache store failed; continuing", exc_info=True)

        return metas

    def get_session_detail(self, config_path: Path, session_id: str) -> Optional[HistorySessionDetail]:
        """Get full message detail for a Codex session.

        Finds the JSONL file for the given session_id and parses all entries.
        """
        sessions_dir = config_path / "sessions"
        if not sessions_dir.is_dir():
            return None

        # Find the JSONL file containing this session
        jsonl_files = _find_jsonl_files(sessions_dir)
        target_file: Optional[Path] = None
        found_cwd: Optional[str] = None

        for jsonl_file in jsonl_files:
            for entry in self.safe_read_jsonl(jsonl_file):
                if entry.get("type") == "session_meta":
                    payload = entry.get("payload", {})
                    if payload.get("id") == session_id or entry.get("id") == session_id:
                        target_file = jsonl_file
                        found_cwd = payload.get("cwd", "") or None
                        break
            if target_file:
                break

        # Also try matching by filename pattern
        if target_file is None:
            for jsonl_file in jsonl_files:
                if session_id in jsonl_file.stem:
                    target_file = jsonl_file
                    break

        if target_file is None:
            return None

        detail = self._parse_session_messages(target_file, session_id)
        # Attach exec_dir from session_meta cwd
        if found_cwd and detail.session is None:
            detail.session = SessionMeta(
                id=session_id,
                thread_id=session_id,
                title="",
                username="",
                provider="codex",
                status=SessionStatus.COMPLETED,
                source="history",
                exec_dir=found_cwd,
            )
        return detail

    def _parse_session_meta(self, jsonl_file: Path, normalized_project: str) -> Optional[SessionMeta]:
        """Parse a single JSONL file for session metadata.

        Returns SessionMeta if the session's cwd matches normalized_project, else None.
        """
        session_id = None
        cwd = ""
        message_count = 0
        last_user_message = ""
        last_timestamp = 0

        for entry in self.safe_read_jsonl(jsonl_file):
            entry_type = entry.get("type", "")

            if entry_type == "session_meta":
                payload = entry.get("payload", {})
                session_id = payload.get("id") or entry.get("id")
                cwd = payload.get("cwd", "")
                ts = entry.get("timestamp")
                if ts:
                    last_timestamp = self._parse_timestamp_ms(ts)

            elif entry_type == "event_msg":
                payload = entry.get("payload", {})
                if payload.get("type") == "user_message":
                    message_count += 1
                    # Codex stores user text in payload.message (string)
                    msg_text = payload.get("message", "") or ""
                    if not msg_text:
                        # Fallback: some versions may use payload.content
                        msg_text = _extract_text(payload.get("content", ""))
                    if msg_text:
                        last_user_message = msg_text[:100]

            elif entry_type == "response_item":
                payload = entry.get("payload", {})
                p_type = payload.get("type", "")
                if p_type == "message" and payload.get("role") == "assistant":
                    message_count += 1

            # Track last timestamp from any entry
            ts = entry.get("timestamp")
            if ts:
                ts_ms = self._parse_timestamp_ms(ts)
                if ts_ms > last_timestamp:
                    last_timestamp = ts_ms

        if not session_id:
            # Use filename as session id fallback
            session_id = jsonl_file.stem

        # Match cwd against project_path
        if cwd:
            normalized_cwd = self.normalize_path(cwd)
            if normalized_cwd != normalized_project:
                return None
        else:
            # No cwd info — skip (can't determine project association)
            return None

        title = last_user_message or "New Session"

        return SessionMeta(
            id=session_id,
            thread_id=session_id,
            title=title,
            username="",
            provider="codex",
            status=SessionStatus.COMPLETED,
            created_at=last_timestamp,
            updated_at=last_timestamp,
            message_count=message_count,
            source="history",
        )

    def _parse_session_meta_unfiltered(self, jsonl_file: Path) -> Optional[SessionMeta]:
        """Parse a single JSONL file for session metadata without cwd filtering.

        Returns SessionMeta with exec_dir set to the session's cwd.
        """
        session_id = None
        cwd = ""
        message_count = 0
        last_user_message = ""
        last_timestamp = 0

        for entry in self.safe_read_jsonl(jsonl_file):
            entry_type = entry.get("type", "")

            if entry_type == "session_meta":
                payload = entry.get("payload", {})
                session_id = payload.get("id") or entry.get("id")
                cwd = payload.get("cwd", "")
                ts = entry.get("timestamp")
                if ts:
                    last_timestamp = self._parse_timestamp_ms(ts)

            elif entry_type == "event_msg":
                payload = entry.get("payload", {})
                if payload.get("type") == "user_message":
                    message_count += 1
                    msg_text = payload.get("message", "") or ""
                    if not msg_text:
                        msg_text = _extract_text(payload.get("content", ""))
                    if msg_text:
                        last_user_message = msg_text[:100]

            elif entry_type == "response_item":
                payload = entry.get("payload", {})
                p_type = payload.get("type", "")
                if p_type == "message" and payload.get("role") == "assistant":
                    message_count += 1

            ts = entry.get("timestamp")
            if ts:
                ts_ms = self._parse_timestamp_ms(ts)
                if ts_ms > last_timestamp:
                    last_timestamp = ts_ms

        if not session_id:
            session_id = jsonl_file.stem

        title = last_user_message or "New Session"

        return SessionMeta(
            id=session_id,
            thread_id=session_id,
            title=title,
            username="",
            provider="codex",
            status=SessionStatus.COMPLETED,
            created_at=last_timestamp,
            updated_at=last_timestamp,
            message_count=message_count,
            source="history",
            exec_dir=cwd or None,
        )

    def _parse_session_messages(self, jsonl_file: Path, session_id: str) -> HistorySessionDetail:
        """Parse all entries in a JSONL file into messages and tool calls."""
        messages: List[StoredMessage] = []
        tool_calls: List[StoredToolCall] = []
        current_assistant_msg_id: Optional[str] = None

        for entry in self.safe_read_jsonl(jsonl_file):
            entry_type = entry.get("type", "")
            payload = entry.get("payload", {})
            ts = entry.get("timestamp")
            ts_ms = self._parse_timestamp_ms(ts) if ts else 0

            if entry_type == "event_msg":
                p_type = payload.get("type", "")
                if p_type == "user_message":
                    # Codex stores user text in payload.message (string)
                    text = payload.get("message", "") or ""
                    if not text:
                        text = _extract_text(payload.get("content", ""))
                    if text:
                        msg_id = str(uuid.uuid4())
                        messages.append(StoredMessage(
                            id=msg_id,
                            role="user",
                            content=text,
                            timestamp=ts_ms,
                            status=MessageStatus.COMPLETE,
                        ))
                        current_assistant_msg_id = None

            elif entry_type == "response_item":
                p_type = payload.get("type", "")

                if p_type == "message":
                    role = payload.get("role", "assistant")
                    content = payload.get("content", "")
                    text = _extract_text(content)

                    # Skip system context messages
                    if text and "<environment_context>" in text:
                        continue

                    if role == "user" and text:
                        msg_id = payload.get("id") or str(uuid.uuid4())
                        messages.append(StoredMessage(
                            id=msg_id,
                            role="user",
                            content=text,
                            timestamp=ts_ms,
                            status=MessageStatus.COMPLETE,
                        ))
                    elif role == "assistant" and text:
                        msg_id = payload.get("id") or str(uuid.uuid4())
                        messages.append(StoredMessage(
                            id=msg_id,
                            role="assistant",
                            content=text,
                            timestamp=ts_ms,
                            status=MessageStatus.COMPLETE,
                        ))
                        current_assistant_msg_id = msg_id

                elif p_type == "reasoning":
                    # Reasoning/thinking — Codex uses payload.summary[].text
                    summary = ""
                    summary_items = payload.get("summary", [])
                    if isinstance(summary_items, list):
                        parts = [
                            item.get("text", "") for item in summary_items
                            if isinstance(item, dict) and item.get("text")
                        ]
                        summary = "\n".join(parts)
                    if not summary:
                        # Fallback: some versions may use payload.content
                        r_content = payload.get("content", [])
                        if isinstance(r_content, list):
                            for item in r_content:
                                if isinstance(item, dict) and item.get("type") == "summary_text":
                                    summary = item.get("text", "")
                                    break
                    if summary:
                        msg_id = payload.get("id") or str(uuid.uuid4())
                        messages.append(StoredMessage(
                            id=msg_id,
                            role="assistant",
                            content=f"[Thinking] {summary}",
                            timestamp=ts_ms,
                            status=MessageStatus.COMPLETE,
                        ))

                elif p_type == "function_call":
                    tc_id = payload.get("call_id") or payload.get("id") or str(uuid.uuid4())
                    raw_name = payload.get("name", "unknown")
                    tool_name = _TOOL_NAME_MAP.get(raw_name, raw_name)
                    args_str = payload.get("arguments", "")

                    # Parse args
                    args = {}
                    if args_str:
                        try:
                            import json
                            args = json.loads(args_str)
                        except (ValueError, TypeError):
                            args = {"raw": args_str}

                    tc = StoredToolCall(
                        id=tc_id,
                        tool_name=tool_name,
                        args=args,
                        args_string=args_str,
                        status=ToolCallStatus.COMPLETED,
                        start_time=ts_ms,
                        parent_message_id=current_assistant_msg_id,
                    )
                    tool_calls.append(tc)

                    # Add tool_call segment to the current assistant message
                    if current_assistant_msg_id:
                        for msg in messages:
                            if msg.id == current_assistant_msg_id:
                                if msg.tool_call_ids is None:
                                    msg.tool_call_ids = []
                                msg.tool_call_ids.append(tc_id)
                                if msg.content_segments is None:
                                    msg.content_segments = []
                                    if msg.content:
                                        msg.content_segments.append(ContentSegment(
                                            type="text", content=msg.content, sequence=0
                                        ))
                                msg.content_segments.append(ContentSegment(
                                    type="tool_call",
                                    tool_call_id=tc_id,
                                    sequence=len(msg.content_segments),
                                ))
                                break

                elif p_type == "function_call_output":
                    tc_id = payload.get("call_id") or ""
                    output = payload.get("output", "")
                    if tc_id:
                        for tc in tool_calls:
                            if tc.id == tc_id:
                                tc.result = output
                                tc.end_time = ts_ms
                                break

                elif p_type == "custom_tool_call":
                    tc_id = payload.get("call_id") or payload.get("id") or str(uuid.uuid4())
                    raw_name = payload.get("name", "unknown")
                    tool_name = _TOOL_NAME_MAP.get(raw_name, raw_name)
                    args_str = payload.get("input", "")

                    args = {}
                    if isinstance(args_str, dict):
                        args = args_str
                        args_str = str(args_str)
                    elif isinstance(args_str, str) and args_str:
                        # For apply_patch, parse the diff format
                        if raw_name == "apply_patch":
                            args = self._parse_apply_patch(args_str)
                        else:
                            try:
                                import json
                                args = json.loads(args_str)
                            except (ValueError, TypeError):
                                args = {"raw": args_str}

                    tc = StoredToolCall(
                        id=tc_id,
                        tool_name=tool_name,
                        args=args,
                        args_string=str(args_str),
                        status=ToolCallStatus.COMPLETED,
                        start_time=ts_ms,
                        parent_message_id=current_assistant_msg_id,
                    )
                    tool_calls.append(tc)

                    if current_assistant_msg_id:
                        for msg in messages:
                            if msg.id == current_assistant_msg_id:
                                if msg.tool_call_ids is None:
                                    msg.tool_call_ids = []
                                msg.tool_call_ids.append(tc_id)
                                if msg.content_segments is None:
                                    msg.content_segments = []
                                    if msg.content:
                                        msg.content_segments.append(ContentSegment(
                                            type="text", content=msg.content, sequence=0
                                        ))
                                msg.content_segments.append(ContentSegment(
                                    type="tool_call",
                                    tool_call_id=tc_id,
                                    sequence=len(msg.content_segments),
                                ))
                                break

                elif p_type == "custom_tool_call_output":
                    tc_id = payload.get("call_id") or payload.get("id") or ""
                    output = payload.get("output", "")
                    if tc_id:
                        for tc in tool_calls:
                            if tc.id == tc_id:
                                tc.result = output
                                tc.end_time = ts_ms
                                break

        return HistorySessionDetail(
            session_id=session_id,
            messages=messages,
            tool_calls=tool_calls,
        )

    @staticmethod
    def _parse_apply_patch(patch_input: str) -> Dict:
        """Parse Codex apply_patch input into structured args.

        Format: *** Update File: {path}\n@@...@@\n-old\n+new
        """
        result: Dict = {"raw": patch_input}
        lines = patch_input.split("\n")
        for line in lines:
            if line.startswith("*** Update File:") or line.startswith("*** Add File:"):
                result["file"] = line.split(":", 1)[1].strip() if ":" in line else ""
                break
        return result

    @staticmethod
    def _parse_timestamp_ms(ts) -> int:
        """Parse various timestamp formats to milliseconds."""
        if not ts:
            return 0
        if isinstance(ts, (int, float)):
            return int(ts) if ts > 1e12 else int(ts * 1000)
        if isinstance(ts, str):
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return int(dt.timestamp() * 1000)
            except (ValueError, TypeError):
                try:
                    val = float(ts)
                    return int(val) if val > 1e12 else int(val * 1000)
                except (ValueError, TypeError):
                    return 0
        return 0

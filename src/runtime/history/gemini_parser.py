# -*- coding: utf-8 -*-
"""Gemini CLI history parser.

Reads ~/.gemini/tmp/{sha256(project_path)}/chats/session-*.json files and
converts them to the project's unified AGUI data models.

Gemini session JSON format:
  - Single JSON file per session (not JSONL)
  - Top-level: sessionId, projectHash, startTime, lastUpdated, messages[]
  - messages[].type: "user", "gemini", "error", "info", "warning"
  - "gemini" messages may contain: content (str), toolCalls[], thoughts[]
  - toolCalls[]: {id, name, args, result: [{functionResponse: {...}}]}
"""

import hashlib
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
from .base_parser import BaseHistoryParser, HistorySessionDetail

logger = logging.getLogger(__name__)

# Maximum file size to read (50 MB safety limit)
_MAX_FILE_SIZE = 50 * 1024 * 1024

# Message types that are not user-facing
_SKIP_MSG_TYPES = frozenset({"error", "info", "warning"})


class GeminiHistoryParser(BaseHistoryParser):
    """Parser for Gemini CLI's native JSON session files."""

    @property
    def provider_name(self) -> str:
        return "gemini"

    def list_projects(self, config_path: Path) -> List[Dict[str, object]]:
        """Discover available project hashes from Gemini's tmp directory.

        Gemini uses SHA256 of the project path as directory names, so we cannot
        reverse them. We return entries with 'hash' instead of 'path'.
        The service layer will attempt to match these hashes against known paths
        from other providers.
        """
        tmp_dir = config_path / "tmp"
        if not tmp_dir.is_dir():
            return []

        results = []
        for hash_dir in tmp_dir.iterdir():
            if not hash_dir.is_dir():
                continue
            chats_dir = hash_dir / "chats"
            if not chats_dir.is_dir():
                continue

            session_files = list(chats_dir.glob("session-*.json"))
            if not session_files:
                continue

            latest_mtime = max(f.stat().st_mtime for f in session_files)
            results.append({
                "hash": hash_dir.name,
                "provider": "gemini",
                "session_count": len(session_files),
                "last_active": int(latest_mtime * 1000),
            })

        return results

    def list_all_sessions(self, config_path: Path, linux_user: Optional[str] = None) -> List[SessionMeta]:
        """List ALL Gemini sessions across all project hashes (no project filter).

        Scans every {config_path}/tmp/*/chats/session-*.json and attaches
        the hash directory name as exec_dir (since Gemini hashes are
        not reversible; the service layer can match them later).

        Args:
            config_path: Provider config directory (e.g. ~/.gemini)
            linux_user: Optional Linux username to tag on each session
        """
        tmp_dir = config_path / "tmp"
        if not tmp_dir.is_dir():
            return []

        all_sessions: List[SessionMeta] = []
        now_ms = int(time.time() * 1000)

        for hash_dir in tmp_dir.iterdir():
            if not hash_dir.is_dir():
                continue
            chats_dir = hash_dir / "chats"
            if not chats_dir.is_dir():
                continue

            session_files = sorted(
                chats_dir.glob("session-*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )

            for session_file in session_files:
                data = self._safe_read_json(session_file)
                if not data:
                    continue

                session_id = data.get("sessionId", "")
                if not session_id:
                    session_id = self._session_id_from_filename(session_file.name)

                messages = data.get("messages", [])
                if not isinstance(messages, list):
                    continue

                message_count = 0
                last_user_message = ""
                last_assistant_message = ""

                for msg in messages:
                    if not isinstance(msg, dict):
                        continue
                    msg_type = msg.get("type", "")
                    content = msg.get("content", "")

                    if msg_type in _SKIP_MSG_TYPES:
                        continue

                    if msg_type == "user" and content:
                        if isinstance(content, str):
                            message_count += 1
                            last_user_message = content[:100]
                    elif msg_type == "gemini":
                        text = content if isinstance(content, str) else ""
                        if text:
                            message_count += 1
                            last_assistant_message = text[:100]

                title = last_user_message or last_assistant_message or "New Session"
                title = " ".join(title.split())

                start_time = self._parse_iso_timestamp_ms(data.get("startTime", ""))
                last_updated = self._parse_iso_timestamp_ms(data.get("lastUpdated", ""))
                created_at = start_time or now_ms
                updated_at = last_updated or start_time or now_ms

                all_sessions.append(SessionMeta(
                    id=session_id,
                    thread_id=session_id,
                    title=title[:100],
                    username="",
                    provider="gemini",
                    status=SessionStatus.COMPLETED,
                    created_at=created_at,
                    updated_at=updated_at,
                    message_count=message_count,
                    source="history",
                    exec_dir=f"[gemini:{hash_dir.name[:12]}...]",
                    exec_user=linux_user,
                ))

        all_sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return all_sessions

    def list_sessions(self, config_path: Path, project_path: str) -> List[SessionMeta]:
        """List Gemini sessions for a specific project.

        Scans {config_path}/tmp/{sha256(project_path)}/chats/session-*.json.
        """
        project_hash = self._hash_project_path(project_path)
        chats_dir = config_path / "tmp" / project_hash / "chats"

        if not chats_dir.is_dir():
            return []

        session_files = sorted(
            chats_dir.glob("session-*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        if not session_files:
            return []

        sessions: List[SessionMeta] = []
        now_ms = int(time.time() * 1000)

        for session_file in session_files:
            data = self._safe_read_json(session_file)
            if not data:
                continue

            session_id = data.get("sessionId", "")
            if not session_id:
                # Extract from filename: session-{datetime}-{sessionId}.json
                session_id = self._session_id_from_filename(session_file.name)

            messages = data.get("messages", [])
            if not isinstance(messages, list):
                continue

            # Count user-facing messages
            message_count = 0
            last_user_message = ""
            last_assistant_message = ""

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                msg_type = msg.get("type", "")
                content = msg.get("content", "")

                if msg_type in _SKIP_MSG_TYPES:
                    continue

                if msg_type == "user" and content:
                    if isinstance(content, str):
                        message_count += 1
                        last_user_message = content[:100]

                elif msg_type == "gemini":
                    text = content if isinstance(content, str) else ""
                    if text:
                        message_count += 1
                        last_assistant_message = text[:100]

            # Determine title
            title = last_user_message or last_assistant_message or "New Session"
            title = " ".join(title.split())

            # Parse timestamps
            start_time = self._parse_iso_timestamp_ms(data.get("startTime", ""))
            last_updated = self._parse_iso_timestamp_ms(data.get("lastUpdated", ""))
            created_at = start_time or now_ms
            updated_at = last_updated or start_time or now_ms

            sessions.append(SessionMeta(
                id=session_id,
                thread_id=session_id,
                title=title[:100],
                username="",
                provider="gemini",
                status=SessionStatus.COMPLETED,
                created_at=created_at,
                updated_at=updated_at,
                message_count=message_count,
                source="history",
            ))

        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def get_session_detail(self, config_path: Path, session_id: str) -> Optional[HistorySessionDetail]:
        """Get full message detail for a Gemini session.

        Searches all project hash directories for the matching session file.
        """
        tmp_dir = config_path / "tmp"
        if not tmp_dir.is_dir():
            return None

        # Search across all project hash directories
        for hash_dir in tmp_dir.iterdir():
            if not hash_dir.is_dir():
                continue
            chats_dir = hash_dir / "chats"
            if not chats_dir.is_dir():
                continue

            for session_file in chats_dir.glob("session-*.json"):
                data = self._safe_read_json(session_file)
                if not data:
                    continue

                file_session_id = data.get("sessionId", "")
                if not file_session_id:
                    file_session_id = self._session_id_from_filename(session_file.name)

                if file_session_id != session_id:
                    continue

                # Found the session — parse it
                return self._parse_session(data, session_id)

        return None

    def _parse_session(self, data: dict, session_id: str) -> HistorySessionDetail:
        """Parse a Gemini session JSON into messages and tool calls."""
        raw_messages = data.get("messages", [])
        if not isinstance(raw_messages, list):
            raw_messages = []

        messages: List[StoredMessage] = []
        tool_calls: List[StoredToolCall] = []

        for raw_msg in raw_messages:
            if not isinstance(raw_msg, dict):
                continue

            msg_type = raw_msg.get("type", "")
            content = raw_msg.get("content", "")
            msg_id = raw_msg.get("id") or str(uuid.uuid4())
            ts_ms = self._parse_iso_timestamp_ms(raw_msg.get("timestamp", ""))

            # Skip system messages
            if msg_type in _SKIP_MSG_TYPES:
                continue

            if msg_type == "user":
                text = content if isinstance(content, str) else ""
                if not text:
                    continue

                messages.append(StoredMessage(
                    id=msg_id,
                    role="user",
                    content=text,
                    timestamp=ts_ms,
                    status=MessageStatus.COMPLETE,
                ))

            elif msg_type == "gemini":
                text = content if isinstance(content, str) else ""
                raw_tool_calls = raw_msg.get("toolCalls", [])
                thoughts = raw_msg.get("thoughts", [])

                # Build content segments
                segments: List[ContentSegment] = []
                tc_ids: List[str] = []
                seq = 0

                if text:
                    segments.append(ContentSegment(
                        type="text", content=text, sequence=seq
                    ))
                    seq += 1

                # Process tool calls
                if isinstance(raw_tool_calls, list):
                    for tc_raw in raw_tool_calls:
                        if not isinstance(tc_raw, dict):
                            continue

                        tc_id = tc_raw.get("id") or str(uuid.uuid4())
                        tc_name = tc_raw.get("name", "unknown")
                        tc_args = tc_raw.get("args", {})
                        if not isinstance(tc_args, dict):
                            tc_args = {}

                        # Extract result
                        result_text = None
                        tc_status = ToolCallStatus.COMPLETED
                        results = tc_raw.get("result", [])
                        if isinstance(results, list):
                            for r in results:
                                if isinstance(r, dict):
                                    fr = r.get("functionResponse", {})
                                    if isinstance(fr, dict):
                                        resp = fr.get("response", {})
                                        if isinstance(resp, dict):
                                            result_text = resp.get("output") or resp.get("error") or str(resp)
                                            if resp.get("error"):
                                                tc_status = ToolCallStatus.FAILED

                        tc_ids.append(tc_id)
                        segments.append(ContentSegment(
                            type="tool_call", tool_call_id=tc_id, sequence=seq
                        ))
                        seq += 1

                        tool_calls.append(StoredToolCall(
                            id=tc_id,
                            tool_name=tc_name,
                            args=tc_args,
                            args_string=json.dumps(tc_args, ensure_ascii=False),
                            status=tc_status,
                            result=result_text,
                            start_time=ts_ms,
                            end_time=ts_ms,
                            parent_message_id=msg_id,
                        ))

                # Only add message if it has content or tool calls
                if text or tc_ids:
                    messages.append(StoredMessage(
                        id=msg_id,
                        role="assistant",
                        content=text,
                        timestamp=ts_ms,
                        status=MessageStatus.COMPLETE,
                        tool_call_ids=tc_ids if tc_ids else None,
                        content_segments=segments if segments else None,
                    ))

        return HistorySessionDetail(
            session_id=session_id,
            messages=messages,
            tool_calls=tool_calls,
        )

    # ---- Private helpers ----

    @staticmethod
    def _hash_project_path(project_path: str) -> str:
        """Compute SHA256 hex digest of a project path."""
        return hashlib.sha256(project_path.encode("utf-8")).hexdigest()

    @staticmethod
    def _session_id_from_filename(filename: str) -> str:
        """Extract session ID from filename like 'session-2026-01-28T07-47-7833c16a.json'.

        The session ID is the last segment after the datetime portion.
        """
        name = filename.rsplit(".", 1)[0]  # Remove .json
        parts = name.split("-")
        # session-YYYY-MM-DDTHH-MM-{sessionId}
        # The sessionId is typically the last part (could be a UUID segment)
        if len(parts) >= 6:
            return parts[-1]
        return name

    @staticmethod
    def _safe_read_json(file_path: Path) -> Optional[dict]:
        """Read and parse a JSON file with safety checks."""
        try:
            if file_path.stat().st_size > _MAX_FILE_SIZE:
                logger.warning("Skipping oversized JSON file: %s", file_path)
                return None
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            return None
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("Failed to read JSON file %s: %s", file_path, e)
            return None

    @staticmethod
    def _parse_iso_timestamp_ms(ts) -> int:
        """Parse an ISO 8601 timestamp string to milliseconds."""
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

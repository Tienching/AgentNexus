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
from collections import defaultdict
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

    def list_sessions(self, config_path: Path, project_path: str) -> List[SessionMeta]:
        """List CodeBuddy sessions for a specific project.

        Scans {config_path}/projects/{encoded_path}/*.jsonl,
        groups entries by sessionId, and returns session metadata.
        """
        encoded = self._encode_project_path(project_path)
        projects_dir = config_path / "projects" / encoded

        if not projects_dir.is_dir():
            return []

        jsonl_files = sorted(
            [f for f in projects_dir.glob("*.jsonl") if not f.name.startswith("agent-")],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        if not jsonl_files:
            return []

        sessions_map: Dict[str, dict] = {}

        for jsonl_file in jsonl_files:
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

        # Build SessionMeta list
        sessions: List[SessionMeta] = []
        now_ms = int(time.time() * 1000)

        for sid, sdata in sessions_map.items():
            title = sdata["title"]
            if not title:
                title = sdata["last_user_message"] or sdata["last_assistant_message"] or "New Session"

            # Clean title
            title = " ".join(title.split())

            # Skip JSON-only sessions
            if title.strip().startswith('{ "'):
                continue

            last_activity = sdata["last_activity"] or now_ms

            sessions.append(SessionMeta(
                id=sid,
                thread_id=sid,
                title=title[:100],
                username="",
                provider="codebuddy",
                status=SessionStatus.COMPLETED,
                created_at=last_activity,
                updated_at=last_activity,
                message_count=sdata["message_count"],
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
        for project_subdir in projects_dir.iterdir():
            if not project_subdir.is_dir():
                continue
            for jsonl_file in project_subdir.glob("*.jsonl"):
                if jsonl_file.name.startswith("agent-"):
                    continue
                for entry in self.safe_read_jsonl(jsonl_file):
                    if entry.get("sessionId") == session_id:
                        entries.append(entry)

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

        return HistorySessionDetail(
            session_id=session_id,
            messages=messages,
            tool_calls=tool_calls,
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

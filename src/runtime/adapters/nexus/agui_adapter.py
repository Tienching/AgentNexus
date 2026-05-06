# -*- coding: utf-8 -*-
"""NexusAGUIAdapter — converts internal NexusEvents to AG-UI SSE.

This adapter sits between the raw JSON lines emitted by
:class:`NexusExecutor` and the client expecting AG-UI protocol events.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

from src.runtime.adapters.base import BaseAdapter, ProtocolType
from src.runtime.events.agui import (
    MessageRole,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
    build_tool_call_start_metadata,
)

logger = logging.getLogger(__name__)


class NexusAGUIAdapter(BaseAdapter):
    """AG-UI adapter for the Nexus provider.

    Unlike the Claude adapter which parses ``stream-json`` events, this
    adapter receives our own :mod:`event_schema` events (serialised as
    JSON lines) and maps them directly to AG-UI SSE.
    """

    def __init__(self):
        super().__init__()
        self._active_message_id: Optional[str] = None
        self._message_started: bool = False

    # ── BaseAdapter interface ─────────────────────────────────────────

    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.AGUI

    def init_state(self, thread_id: str, run_id: str) -> None:
        super().init_state(thread_id, run_id)
        self._active_message_id = None
        self._message_started = False

    def convert(self, event: Dict[str, Any]) -> Optional[str]:
        """Convert a single NexusEvent dict to one or more AG-UI SSE events."""
        if not self.state:
            return None

        event_type = event.get("type")

        if event_type == "text_start":
            return self._handle_text_start(event)
        elif event_type == "text_delta":
            return self._handle_text_delta(event)
        elif event_type == "text_end":
            return self._handle_text_end(event)
        elif event_type == "tool_start":
            return self._handle_tool_start(event)
        elif event_type == "tool_result":
            return self._handle_tool_result(event)
        elif event_type == "tool_end":
            return self._handle_tool_end(event)
        elif event_type == "error":
            return self._handle_error(event)
        elif event_type == "done":
            return None  # handled by create_end_event
        elif event_type == "thinking":
            return None  # suppress thinking events for now
        return None

    def format_sse(self, data: Any) -> str:
        if hasattr(data, "to_sse"):
            return data.to_sse()
        json_str = json.dumps(data, ensure_ascii=False)
        return f"data: {json_str}\n\n"

    def create_start_event(self) -> Optional[str]:
        if not self.state or self.state.run_started:
            return None
        self.state.run_started = True
        return RunStartedEvent(
            threadId=self.state.thread_id,
            runId=self.state.run_id,
        ).to_sse()

    def create_end_event(self, is_error: bool = False, error_msg: str = "") -> str:
        if not self.state:
            return ""
        results: list[str] = []

        # Close any open text message
        if self._message_started and self._active_message_id:
            results.append(TextMessageEndEvent(
                messageId=self._active_message_id,
            ).to_sse())
            self._message_started = False

        if is_error:
            results.append(RunErrorEvent(
                threadId=self.state.thread_id,
                runId=self.state.run_id,
                message=error_msg,
            ).to_sse())

        results.append(RunFinishedEvent(
            threadId=self.state.thread_id,
            runId=self.state.run_id,
        ).to_sse())
        self.state.run_finished = True
        return "".join(results)

    def create_error_event(self, error_msg: str) -> str:
        if not self.state:
            from src.runtime.utils.ids import gen_session_id, gen_run_id
            thread_id = gen_session_id()
            run_id = gen_run_id()
        else:
            thread_id = self.state.thread_id
            run_id = self.state.run_id
        return RunErrorEvent(
            threadId=thread_id,
            runId=run_id,
            message=error_msg,
        ).to_sse()

    # ── Private handlers ──────────────────────────────────────────────

    def _handle_text_start(self, event: Dict[str, Any]) -> Optional[str]:
        msg_id = event.get("message_id", f"msg_{uuid.uuid4().hex[:12]}")
        self._active_message_id = msg_id
        self._message_started = True
        return TextMessageStartEvent(
            messageId=msg_id,
            role=MessageRole.ASSISTANT,
        ).to_sse()

    def _handle_text_delta(self, event: Dict[str, Any]) -> Optional[str]:
        delta = event.get("delta", "")
        if not delta:
            return None

        results: list[str] = []

        # Auto-open message if we haven't yet (defensive)
        if not self._message_started:
            msg_id = event.get("message_id", f"msg_{uuid.uuid4().hex[:12]}")
            self._active_message_id = msg_id
            self._message_started = True
            results.append(TextMessageStartEvent(
                messageId=msg_id,
                role=MessageRole.ASSISTANT,
            ).to_sse())

        results.append(TextMessageContentEvent(
            messageId=self._active_message_id,
            delta=delta,
        ).to_sse())
        return "".join(results)

    def _handle_text_end(self, event: Dict[str, Any]) -> Optional[str]:
        if not self._message_started:
            return None
        msg_id = self._active_message_id or event.get("message_id", "")
        self._message_started = False
        return TextMessageEndEvent(messageId=msg_id).to_sse()

    def _handle_tool_start(self, event: Dict[str, Any]) -> Optional[str]:
        tool_call_id = event.get("tool_call_id", str(uuid.uuid4()))
        name = event.get("name", "unknown")
        arguments = event.get("arguments", {})

        results: list[str] = []

        # ToolCallStart
        results.append(ToolCallStartEvent(
            toolCallId=tool_call_id,
            toolCallName=name,
            parentMessageId=self._active_message_id,
            **build_tool_call_start_metadata(
                name,
                arguments,
                description=event.get("tool_call_description") or event.get("description"),
                display_name=event.get("tool_call_display_name") or event.get("display_name"),
            ),
        ).to_sse())

        # ToolCallArgs (send full arguments if available)
        if arguments:
            args_str = json.dumps(arguments, ensure_ascii=False)
            if args_str and args_str != "{}":
                results.append(ToolCallArgsEvent(
                    toolCallId=tool_call_id,
                    delta=args_str,
                ).to_sse())

        if self.state:
            self.state.active_tool_calls[tool_call_id] = name

        return "".join(results)

    def _handle_tool_result(self, event: Dict[str, Any]) -> Optional[str]:
        tool_call_id = event.get("tool_call_id", "")
        content = event.get("content", "")

        # Truncate for display
        if len(content) > 1000:
            content = content[:1000] + "…(truncated)"

        return ToolCallResultEvent(
            messageId=self._active_message_id or f"msg_{uuid.uuid4().hex[:12]}",
            toolCallId=tool_call_id,
            content=content,
        ).to_sse()

    def _handle_tool_end(self, event: Dict[str, Any]) -> Optional[str]:
        tool_call_id = event.get("tool_call_id", "")

        result = ToolCallEndEvent(toolCallId=tool_call_id).to_sse()

        if self.state and tool_call_id in self.state.active_tool_calls:
            del self.state.active_tool_calls[tool_call_id]

        return result

    def _handle_error(self, event: Dict[str, Any]) -> Optional[str]:
        msg = event.get("message", "Unknown error")
        results: list[str] = []

        # Send error as text message
        if not self._message_started:
            err_msg_id = f"err_{uuid.uuid4().hex[:8]}"
            self._active_message_id = err_msg_id
            self._message_started = True
            results.append(TextMessageStartEvent(
                messageId=err_msg_id,
                role=MessageRole.ASSISTANT,
            ).to_sse())

        results.append(TextMessageContentEvent(
            messageId=self._active_message_id,
            delta=f"\n\n⚠️ **Error**: {msg}",
        ).to_sse())

        results.append(TextMessageEndEvent(
            messageId=self._active_message_id,
        ).to_sse())
        self._message_started = False

        if self.state:
            results.append(RunErrorEvent(
                threadId=self.state.thread_id,
                runId=self.state.run_id,
                message=msg,
            ).to_sse())
            self.state.has_error = True

        return "".join(results)


NanobotAGUIAdapter = NexusAGUIAdapter

__all__ = ["NexusAGUIAdapter", "NanobotAGUIAdapter"]

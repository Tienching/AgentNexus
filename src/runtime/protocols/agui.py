# -*- coding: utf-8 -*-
"""AG-UI Protocol (compat mode)

This implementation intentionally matches the production semantics used by
`claude_code_api.models.agui_events.AGUIBaseEvent.to_sse()`:

- SSE frames are `data: <compact-json>\n\n` (no mandatory `event:` line)
- The JSON payload includes a top-level `type` field (e.g. "RUN_STARTED")
- JSON is compact (`separators=(',',':')`) and `ensure_ascii=False`

NOTE: `src.runtime` MUST NOT depend on `claude_code_api`.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Optional

from .base import ProtocolType, ProtocolState
from ..events import (
    Event,
    EventType,
    TokenEvent,
    ToolCallStartEvent,
    ToolCallEndEvent,
    ToolResultEvent,
    MessageStartEvent,
    MessageEndEvent,
    ErrorEvent,
)


@dataclass
class AGUIState(ProtocolState):
    message_counter: int = 0
    current_message_id: Optional[str] = None
    run_started: bool = False
    run_finished: bool = False


class AGUIProtocol:
    def __init__(self):
        self.state: Optional[AGUIState] = None

    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.AGUI

    def init_state(self, thread_id: str, run_id: str) -> None:
        self.state = AGUIState(thread_id=thread_id, run_id=run_id)

    def _generate_message_id(self, provider: str) -> str:
        if (provider or "").strip().lower() == "gemini":
            return f"gemini-msg-{uuid.uuid4().hex}"

        # Claude/default: match `claude_code_api/adapters/agui_adapter.py` behavior.
        if not self.state:
            return f"msg_{uuid.uuid4().hex[:8]}_0001"

        self.state.message_counter += 1
        run_id_suffix = (self.state.run_id or "")[:8] or uuid.uuid4().hex[:8]
        return f"msg_{run_id_suffix}_{self.state.message_counter:04d}"

    def _format_sse(self, data: dict, include_event_line: bool = False) -> str:
        event_type = str(data.get("type") or "")
        json_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if include_event_line:
            return f"event: {event_type}\ndata: {json_str}\n\n"
        return f"data: {json_str}\n\n"

    def convert(self, event: Event) -> Optional[str]:
        if not self.state:
            return None

        results: list[str] = []

        # Always emit RUN_STARTED first.
        if not self.state.run_started:
            self.state.run_started = True
            results.append(
                self._format_sse(
                    {"type": "RUN_STARTED", "threadId": self.state.thread_id, "runId": self.state.run_id}
                )
            )

        provider = (getattr(event, "provider", "") or "").strip().lower()

        if event.type == EventType.MESSAGE_START:
            msg_id = self._generate_message_id(provider)
            self.state.current_message_id = msg_id
            role = event.data.get("role", "assistant") if isinstance(event, MessageStartEvent) else "assistant"
            results.append(self._format_sse({"type": "TEXT_MESSAGE_START", "messageId": msg_id, "role": role}))

        elif event.type == EventType.TOKEN:
            text = event.text if isinstance(event, TokenEvent) else (event.data.get("text", "") or "")
            if text:
                if not self.state.current_message_id:
                    # Defensive: ensure a message exists.
                    msg_id = self._generate_message_id(provider)
                    self.state.current_message_id = msg_id
                    results.append(
                        self._format_sse({"type": "TEXT_MESSAGE_START", "messageId": msg_id, "role": "assistant"})
                    )
                results.append(
                    self._format_sse(
                        {
                            "type": "TEXT_MESSAGE_CONTENT",
                            "messageId": self.state.current_message_id,
                            "delta": text,
                        }
                    )
                )

        elif event.type == EventType.MESSAGE_END:
            mid = self.state.current_message_id or (event.data.get("message_id") or "")
            results.append(self._format_sse({"type": "TEXT_MESSAGE_END", "messageId": mid}))
            self.state.current_message_id = None

        elif event.type == EventType.TOOL_CALL_START:
            tool_name = event.tool_name if isinstance(event, ToolCallStartEvent) else (event.data.get("tool_name") or "")
            tool_id = event.tool_id if isinstance(event, ToolCallStartEvent) else (event.data.get("tool_id") or "")
            results.append(self._format_sse({"type": "TOOL_CALL_START", "toolCallId": tool_id, "toolCallName": tool_name}))

            arguments = event.arguments if isinstance(event, ToolCallStartEvent) else (event.data.get("arguments") or {})
            if arguments:
                results.append(
                    self._format_sse(
                        {
                            "type": "TOOL_CALL_ARGS",
                            "toolCallId": tool_id,
                            "delta": json.dumps(arguments, ensure_ascii=False, separators=(",", ":")),
                        }
                    )
                )

        elif event.type == EventType.TOOL_CALL_END:
            tool_id = event.tool_id if isinstance(event, ToolCallEndEvent) else (event.data.get("tool_id") or "")
            results.append(self._format_sse({"type": "TOOL_CALL_END", "toolCallId": tool_id}))

        elif event.type == EventType.TOOL_RESULT:
            tool_id = event.tool_id if isinstance(event, ToolResultEvent) else (event.data.get("tool_id") or "")
            result = event.result if isinstance(event, ToolResultEvent) else event.data.get("result")
            results.append(
                self._format_sse({"type": "TOOL_CALL_RESULT", "toolCallId": tool_id, "result": "" if result is None else str(result)})
            )

        elif event.type == EventType.ERROR:
            message = event.message if isinstance(event, ErrorEvent) else (event.data.get("message") or "Unknown error")
            code = event.code if isinstance(event, ErrorEvent) else (event.data.get("code") or "error")
            results.append(self._format_sse({"type": "RUN_ERROR", "message": message, "code": code}))

        return "".join(results) if results else None

    def finalize(self) -> Optional[str]:
        if not self.state or self.state.run_finished:
            return None

        self.state.run_finished = True
        return self._format_sse({"type": "RUN_FINISHED", "threadId": self.state.thread_id, "runId": self.state.run_id})

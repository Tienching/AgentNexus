# -*- coding: utf-8 -*-
"""Legacy (WeCom) Protocol (compat mode)

This protocol matches the legacy SSE format used by `CCRExecutor.format_legacy_sse()`:

- SSE frame: `event:delta\ndata:<json>\n\n`
- JSON payload: {response, finished, global_output:{context,answer_success,docs}}

NOTE: Naming kept as `WeComProtocol` for compatibility with earlier runtime scaffold.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from .base import ProtocolType, ProtocolState
from ..events import (
    Event,
    EventType,
    TokenEvent,
    ToolCallStartEvent,
    ToolResultEvent,
    ErrorEvent,
)


@dataclass
class WeComState(ProtocolState):
    finished: bool = False


class WeComProtocol:
    def __init__(self):
        self.state: Optional[WeComState] = None

    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.WECOM

    def init_state(self, thread_id: str, run_id: str) -> None:
        self.state = WeComState(thread_id=thread_id, run_id=run_id)

    def _format_delta(self, response: str, finished: bool = False, answer_success: int = 1) -> str:
        data = {
            "response": response,
            "finished": finished,
            "global_output": {
                "context": "",
                "answer_success": answer_success,
                "docs": [],
            },
        }
        json_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return f"event:delta\ndata:{json_str}\n\n"

    def convert(self, event: Event) -> Optional[str]:
        if not self.state:
            return None

        if event.type == EventType.TOKEN:
            text = event.text if isinstance(event, TokenEvent) else (event.data.get("text", "") or "")
            if text:
                return self._format_delta(text, finished=False, answer_success=1)

        if event.type == EventType.TOOL_CALL_START:
            tool_name = event.tool_name if isinstance(event, ToolCallStartEvent) else (event.data.get("tool_name", "unknown") or "unknown")
            arguments = event.arguments if isinstance(event, ToolCallStartEvent) else (event.data.get("arguments") or {})
            text = f"\n🔧 **调用工具: {tool_name}**\n"
            if arguments:
                try:
                    params_str = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
                except Exception:
                    params_str = str(arguments)
                text += f"参数: {params_str}\n"
            return self._format_delta(text, finished=False, answer_success=1)

        if event.type == EventType.TOOL_RESULT:
            result = event.result if isinstance(event, ToolResultEvent) else event.data.get("result")
            success = event.success if isinstance(event, ToolResultEvent) else bool(event.data.get("success", True))
            content = "" if result is None else str(result)
            if success:
                return self._format_delta(f"✅ **结果**: {content}\n", finished=False, answer_success=1)
            return self._format_delta(f"❌ **错误**: {content}\n", finished=False, answer_success=0)

        if event.type == EventType.ERROR:
            message = event.message if isinstance(event, ErrorEvent) else (event.data.get("message") or "Unknown error")
            self.state.finished = True
            return self._format_delta(message, finished=True, answer_success=0)

        return None

    def finalize(self) -> Optional[str]:
        if not self.state or self.state.finished:
            return None
        self.state.finished = True
        return self._format_delta("", finished=True, answer_success=1)

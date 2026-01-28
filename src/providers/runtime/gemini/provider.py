# -*- coding: utf-8 -*-
"""Gemini Provider 实现

NOTE:
- `src.runtime` MUST NOT depend on `gemini_cli_api` or `claude_code_api`.
- The concrete executor is injected by the host.

This provider converts Gemini stream-json events into unified `src.runtime.events`.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator, Any, Optional

from ..base import Executor, RunContext
from src.runtime.events import (
    Event,
    TokenEvent,
    ToolCallStartEvent,
    ToolResultEvent,
    MessageStartEvent,
    MessageEndEvent,
    ErrorEvent,
    SystemEvent,
)


class GeminiProvider:
    name: str = "gemini"

    def __init__(self, executor: Optional[Executor] = None):
        self._executor = executor
        self._capabilities = {
            "streaming": True,
            "tool_use": True,
            "vision": True,
            "code_execution": True,
        }

    def get_executor(self) -> Executor:
        if self._executor is None:
            raise RuntimeError("GeminiProvider requires an injected Executor (src.runtime MUST NOT import API layer executors)")
        return self._executor

    def set_executor(self, executor: Executor) -> None:
        self._executor = executor

    def supports_capability(self, capability: str) -> bool:
        return self._capabilities.get(capability, False)

    async def execute(self, prompt: str, context: RunContext) -> AsyncIterator[Event]:
        message_id = f"msg_{uuid.uuid4().hex[:12]}"

        yield MessageStartEvent(
            provider=self.name,
            session_id=context.session_id,
            message_id=message_id,
            role="assistant",
        )

        try:
            executor = self.get_executor()
            async for raw_event in executor.run(prompt, context):
                async for evt in self._convert_raw_event(raw_event, context):
                    yield evt
        except Exception as e:
            yield ErrorEvent(
                provider=self.name,
                session_id=context.session_id,
                code="execution_error",
                message=str(e),
                recoverable=False,
            )

        yield MessageEndEvent(
            provider=self.name,
            session_id=context.session_id,
            message_id=message_id,
            stop_reason="end_turn",
        )

    async def _convert_raw_event(self, raw_event: Any, context: RunContext) -> AsyncIterator[Event]:
        if raw_event is None:
            return

        if isinstance(raw_event, str):
            if raw_event.strip():
                yield TokenEvent(provider=self.name, session_id=context.session_id, text=raw_event)
            return

        if not isinstance(raw_event, dict):
            yield SystemEvent(
                provider=self.name,
                session_id=context.session_id,
                action="unknown_raw_event",
                details={"value": str(raw_event)},
            )
            return

        event_type = raw_event.get("type", "")

        if event_type == "message":
            if raw_event.get("role") == "assistant":
                content = raw_event.get("content", "")
                if content:
                    yield TokenEvent(provider=self.name, session_id=context.session_id, text=content)
            return

        if event_type == "tool_use":
            yield ToolCallStartEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_name=raw_event.get("tool_name", "unknown"),
                tool_id=raw_event.get("tool_id", ""),
                arguments=raw_event.get("parameters", {}) or {},
            )
            return

        if event_type == "tool_result":
            status = (raw_event.get("status") or "").lower()
            yield ToolResultEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_id=raw_event.get("tool_id", ""),
                result=raw_event.get("output", ""),
                success=(status == "success" or status == ""),
            )
            return

        if event_type == "result":
            subtype = raw_event.get("subtype", "")
            if subtype == "slash_command":
                yield TokenEvent(provider=self.name, session_id=context.session_id, text=raw_event.get("content", ""))
            else:
                yield SystemEvent(provider=self.name, session_id=context.session_id, action="result", details=raw_event)
            return

        if event_type == "error":
            yield ErrorEvent(
                provider=self.name,
                session_id=context.session_id,
                code="gemini_error",
                message=raw_event.get("message", str(raw_event)),
                recoverable=True,
            )
            return

        yield SystemEvent(provider=self.name, session_id=context.session_id, action=event_type or "unknown", details=raw_event)

# -*- coding: utf-8 -*-
"""Codebuddy Provider 实现

将 Codebuddy CLI 的 raw 输出转换为统一事件流。
"""

import json
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
from src.providers.codebuddy import CodebuddyCLIExecutor
from src.providers.base import RequestContext


class CodebuddyProvider:
    """Codebuddy Provider - 包装 Codebuddy CLI Executor 并转换为统一事件"""

    name: str = "codebuddy"

    def __init__(self, executor: Optional[Executor] = None):
        self._executor = executor
        self._capabilities = {
            "streaming": True,
            "tool_use": True,
            "vision": False,
            "code_execution": True,
        }

    def get_executor(self) -> Executor:
        if self._executor is None:
            self._executor = CodebuddyCLIExecutor()
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
            request_ctx = RequestContext(
                content=prompt,
                user=context.metadata.get("user", "default"),
                session_id=context.session_id,
                exec_user=context.exec_user or "default",
                cwd=str(context.workspace) if context.workspace else None,
            )
            async for raw_line in executor._execute_internal(request_ctx):
                async for evt in self._convert_raw_event(raw_line, context):
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

    async def _convert_raw_event(self, raw_line: Any, context: RunContext) -> AsyncIterator[Event]:
        if raw_line is None:
            return

        if isinstance(raw_line, str):
            if not raw_line.strip():
                return
            try:
                data = json.loads(raw_line)
            except json.JSONDecodeError:
                yield TokenEvent(provider=self.name, session_id=context.session_id, text=raw_line)
                return
        elif isinstance(raw_line, dict):
            data = raw_line
        else:
            yield SystemEvent(
                provider=self.name,
                session_id=context.session_id,
                action="unknown_raw_event",
                details={"value": str(raw_line)},
            )
            return

        event_type = data.get("type", "")

        if event_type == "system" and data.get("subtype") == "init":
            yield SystemEvent(provider=self.name, session_id=context.session_id, action="init", details=data)
            return

        if event_type == "topic":
            yield SystemEvent(provider=self.name, session_id=context.session_id, action="topic", details=data)
            return

        if event_type in ("assistant", "user"):
            message = data.get("message") or {}
            contents = message.get("content")
            if not isinstance(contents, list):
                return
            for item in contents:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                if item_type == "text":
                    text = item.get("text", "")
                    if text:
                        yield TokenEvent(provider=self.name, session_id=context.session_id, text=text)
                elif item_type == "tool_use":
                    yield ToolCallStartEvent(
                        provider=self.name,
                        session_id=context.session_id,
                        tool_name=item.get("name", "unknown"),
                        tool_id=item.get("id", ""),
                        arguments=item.get("input", {}) or {},
                    )
                elif item_type == "tool_result":
                    output = item.get("content")
                    result_text = ""
                    if isinstance(output, list):
                        parts = []
                        for out_item in output:
                            if isinstance(out_item, dict) and out_item.get("type") == "text":
                                parts.append(out_item.get("text", ""))
                            else:
                                parts.append(str(out_item))
                        result_text = "".join(parts)
                    else:
                        result_text = "" if output is None else str(output)
                    yield ToolResultEvent(
                        provider=self.name,
                        session_id=context.session_id,
                        tool_id=item.get("tool_use_id", item.get("id", "")),
                        result=result_text,
                        success=True,
                    )
            return

        if event_type == "message":
            if data.get("role") == "assistant":
                content = data.get("content", "")
                if content:
                    yield TokenEvent(provider=self.name, session_id=context.session_id, text=content)
            return

        if event_type == "tool_use":
            yield ToolCallStartEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_name=data.get("tool_name", "unknown"),
                tool_id=data.get("tool_id", ""),
                arguments=data.get("parameters", {}) or {},
            )
            return

        if event_type == "tool_result":
            status = (data.get("status") or "").lower()
            success = status in ("", "success", "ok")
            yield ToolResultEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_id=data.get("tool_id", ""),
                result=data.get("output", ""),
                success=success,
            )
            return

        if event_type == "result":
            subtype = data.get("subtype", "")
            if subtype == "slash_command":
                yield TokenEvent(provider=self.name, session_id=context.session_id, text=data.get("content", ""))
            else:
                yield SystemEvent(provider=self.name, session_id=context.session_id, action="result", details=data)
            return

        if event_type == "error":
            yield ErrorEvent(
                provider=self.name,
                session_id=context.session_id,
                code="codebuddy_error",
                message=data.get("message", str(data)),
                recoverable=True,
            )
            return

        yield SystemEvent(provider=self.name, session_id=context.session_id, action=event_type or "unknown", details=data)

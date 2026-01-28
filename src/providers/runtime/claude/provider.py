# -*- coding: utf-8 -*-
"""
Claude Provider 实现

将 Claude Code (CCR) 的 raw 输出转换为统一事件流。
"""

import json
import uuid
from typing import AsyncIterator, Any, Optional
from pathlib import Path

from ..base import Provider, Executor, RunContext
from src.runtime.events import (
    Event,
    TokenEvent,
    ToolCallStartEvent,
    ToolCallEndEvent,
    ToolResultEvent,
    MessageStartEvent,
    MessageEndEvent,
    ErrorEvent,
    SystemEvent,
)
from src.runtime.executors import CCRExecutor, RequestContext


class ClaudeProvider:
    """Claude Provider - 包装 CCR Executor 并转换为统一事件"""
    
    name: str = "claude"
    
    def __init__(self, executor: Optional[Executor] = None):
        self._executor = executor
        self._capabilities = {
            "streaming": True,
            "tool_use": True,
            "vision": True,
            "code_execution": True,
        }
    
    def get_executor(self) -> Executor:
        """获取底层执行器"""
        if self._executor is None:
            # Use runtime executor (no API layer dependency)
            self._executor = CCRExecutor()
        return self._executor
    
    def set_executor(self, executor: Executor) -> None:
        """设置执行器"""
        self._executor = executor
    
    def supports_capability(self, capability: str) -> bool:
        """检查是否支持某能力"""
        return self._capabilities.get(capability, False)
    
    async def execute(
        self,
        prompt: str,
        context: RunContext,
    ) -> AsyncIterator[Event]:
        """执行并产出统一事件流"""
        
        # 生成 message_id
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        
        # 发送消息开始事件
        yield MessageStartEvent(
            provider=self.name,
            session_id=context.session_id,
            message_id=message_id,
            role="assistant",
        )
        
        try:
            executor = self.get_executor()
            
            # 构造请求上下文（使用统一运行时的 RequestContext）
            request_ctx = RequestContext(
                content=prompt,
                user=context.metadata.get("user", "default"),
                session_id=context.session_id,
                agent_name=context.agent or "default",
            )
            
            # 执行并转换事件
            async for raw_line in executor.execute(request_ctx, output_format="raw"):
                # 转换 raw 事件为统一事件
                async for event in self._convert_raw_event(raw_line, context, message_id):
                    yield event
                    
        except Exception as e:
            yield ErrorEvent(
                provider=self.name,
                session_id=context.session_id,
                code="execution_error",
                message=str(e),
                recoverable=False,
            )
        
        # 发送消息结束事件
        yield MessageEndEvent(
            provider=self.name,
            session_id=context.session_id,
            message_id=message_id,
            stop_reason="end_turn",
        )
    
    async def _convert_raw_event(
        self,
        raw_line: str,
        context: RunContext,
        message_id: str,
    ) -> AsyncIterator[Event]:
        """将 raw JSON 行转换为统一事件"""
        
        if not raw_line or not raw_line.strip():
            return
            
        try:
            data = json.loads(raw_line)
        except json.JSONDecodeError:
            # 非 JSON 行，可能是纯文本
            yield TokenEvent(
                provider=self.name,
                session_id=context.session_id,
                text=raw_line,
            )
            return
        
        event_type = data.get("type", "")
        
        # 处理不同类型的 Claude 事件
        if event_type == "assistant":
            # 文本内容
            message = data.get("message", {})
            content_parts = message.get("content", [])
            for part in content_parts:
                if part.get("type") == "text":
                    yield TokenEvent(
                        provider=self.name,
                        session_id=context.session_id,
                        text=part.get("text", ""),
                    )
                elif part.get("type") == "tool_use":
                    yield ToolCallStartEvent(
                        provider=self.name,
                        session_id=context.session_id,
                        tool_name=part.get("name", ""),
                        tool_id=part.get("id", ""),
                        arguments=part.get("input", {}),
                    )
        
        elif event_type == "content_block_delta":
            # 流式文本增量
            delta = data.get("delta", {})
            if delta.get("type") == "text_delta":
                yield TokenEvent(
                    provider=self.name,
                    session_id=context.session_id,
                    text=delta.get("text", ""),
                )
        
        elif event_type == "tool_use":
            # 工具调用
            yield ToolCallStartEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_name=data.get("name", ""),
                tool_id=data.get("id", str(uuid.uuid4())),
                arguments=data.get("input", {}),
            )
        
        elif event_type == "tool_result":
            # 工具结果
            yield ToolResultEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_id=data.get("tool_use_id", ""),
                result=data.get("content", ""),
                success=not data.get("is_error", False),
            )
        
        elif event_type == "result":
            # 结果事件（包括 slash command 结果）
            subtype = data.get("subtype", "")
            if subtype == "slash_command":
                yield TokenEvent(
                    provider=self.name,
                    session_id=context.session_id,
                    text=data.get("content", ""),
                )
            else:
                yield SystemEvent(
                    provider=self.name,
                    session_id=context.session_id,
                    action="result",
                    details=data,
                )
        
        elif event_type == "error":
            yield ErrorEvent(
                provider=self.name,
                session_id=context.session_id,
                code=data.get("error", {}).get("code", "unknown"),
                message=data.get("error", {}).get("message", str(data)),
                recoverable=True,
            )
        
        elif event_type == "system":
            yield SystemEvent(
                provider=self.name,
                session_id=context.session_id,
                action=data.get("subtype", "system"),
                details=data,
            )
        
        else:
            # 其他未知事件，作为系统事件传递
            yield SystemEvent(
                provider=self.name,
                session_id=context.session_id,
                action=event_type or "unknown",
                details=data,
            )

# -*- coding: utf-8 -*-
"""
Codex Provider 实现

将 Codex CLI 的 raw 输出转换为统一事件流。
"""

import json
import uuid
from typing import AsyncIterator, Any, Optional
from pathlib import Path

from ..base import Provider, Executor, RunContext
from src.providers._error_sanitize import safe_error_message
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
from src.providers.codex import CodexCLIExecutor
from src.providers.base import RequestContext


class CodexProvider:
    """Codex Provider - 包装 Codex CLI Executor 并转换为统一事件"""
    
    name: str = "codex"
    
    def __init__(self, executor: Optional[Executor] = None):
        self._executor = executor
        self._capabilities = {
            "streaming": True,
            "tool_use": True,
            "vision": False,
            "code_execution": True,
            "file_changes": True,
            "web_search": True,
        }
    
    def get_executor(self) -> Executor:
        """获取底层执行器"""
        if self._executor is None:
            self._executor = CodexCLIExecutor()
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
            
            # 构造请求上下文
            request_ctx = RequestContext(
                content=prompt,
                user=context.metadata.get("user", "default"),
                session_id=context.session_id,
                exec_user=context.exec_user or "default",
                cwd=str(context.workspace) if context.workspace else None,
            )
            
            # 执行并转换事件
            async for raw_line in executor._execute_internal(request_ctx):
                # 转换 raw 事件为统一事件
                async for event in self._convert_raw_event(raw_line, context, message_id):
                    yield event
                    
        except Exception as e:
            yield ErrorEvent(
                provider=self.name,
                session_id=context.session_id,
                code="execution_error",
                message=safe_error_message(e),
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
        """将 Codex raw JSON 行转换为统一事件
        
        Codex exec --json 事件类型:
        - thread.started: 会话开始
        - turn.started: 轮次开始
        - item.started: 项目处理开始
        - item.completed: 项目处理完成
        - turn.completed: 轮次结束（含 usage）
        - error: 错误
        
        Item 类型:
        - agent_message: 文本输出
        - reasoning: 推理/思考
        - command_execution: Shell 命令执行
        - file_changes: 文件修改
        - mcp_tool_call: MCP 工具调用
        - web_search: 网页搜索
        """
        
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
        
        # 处理不同类型的 Codex 事件
        if event_type == "thread.started":
            yield SystemEvent(
                provider=self.name,
                session_id=context.session_id,
                action="thread_started",
                details={"thread_id": data.get("thread_id")},
            )
        
        elif event_type == "turn.started":
            yield SystemEvent(
                provider=self.name,
                session_id=context.session_id,
                action="turn_started",
                details=data,
            )
        
        elif event_type == "turn.completed":
            yield SystemEvent(
                provider=self.name,
                session_id=context.session_id,
                action="turn_completed",
                details={"usage": data.get("usage")},
            )
        
        elif event_type == "turn.failed":
            yield ErrorEvent(
                provider=self.name,
                session_id=context.session_id,
                code="turn_failed",
                message=data.get("error", "Turn failed"),
                recoverable=True,
            )
        
        elif event_type == "item.started":
            async for event in self._handle_item_started(data, context, message_id):
                yield event
        
        elif event_type == "item.completed":
            async for event in self._handle_item_completed(data, context, message_id):
                yield event
        
        elif event_type == "error":
            yield ErrorEvent(
                provider=self.name,
                session_id=context.session_id,
                code="codex_error",
                message=data.get("message", str(data)),
                recoverable=True,
            )
        
        else:
            # 其他未知事件，作为系统事件传递
            yield SystemEvent(
                provider=self.name,
                session_id=context.session_id,
                action=event_type or "unknown",
                details=data,
            )
    
    async def _handle_item_started(
        self,
        data: dict,
        context: RunContext,
        message_id: str,
    ) -> AsyncIterator[Event]:
        """处理 item.started 事件"""
        item = data.get("item", {})
        if not isinstance(item, dict):
            return
        
        item_type = item.get("type")
        item_id = item.get("id", str(uuid.uuid4()))
        
        if item_type == "command_execution":
            command = item.get("command", "")
            yield ToolCallStartEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_name="bash",
                tool_id=item_id,
                arguments={"command": command},
            )
        
        elif item_type == "file_changes":
            yield ToolCallStartEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_name="apply_patch",
                tool_id=item_id,
                arguments={},
            )
        
        elif item_type == "mcp_tool_call":
            tool_name = item.get("tool_name", "mcp_tool")
            arguments = item.get("arguments", {})
            yield ToolCallStartEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_name=tool_name,
                tool_id=item_id,
                arguments=arguments,
            )
        
        elif item_type == "web_search":
            query = item.get("query", "")
            yield ToolCallStartEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_name="web_search",
                tool_id=item_id,
                arguments={"query": query},
            )
    
    async def _handle_item_completed(
        self,
        data: dict,
        context: RunContext,
        message_id: str,
    ) -> AsyncIterator[Event]:
        """处理 item.completed 事件"""
        item = data.get("item", {})
        if not isinstance(item, dict):
            return
        
        item_type = item.get("type")
        item_id = item.get("id", "")
        
        if item_type == "agent_message":
            text = item.get("text", "")
            if text:
                yield TokenEvent(
                    provider=self.name,
                    session_id=context.session_id,
                    text=text,
                )
        
        elif item_type == "reasoning":
            text = item.get("text", "")
            if text:
                yield SystemEvent(
                    provider=self.name,
                    session_id=context.session_id,
                    action="reasoning",
                    details={"text": text},
                )
        
        elif item_type == "command_execution":
            output = item.get("aggregated_output", "")
            exit_code = item.get("exit_code")
            yield ToolCallEndEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_id=item_id,
            )
            yield ToolResultEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_id=item_id,
                result={"output": output, "exit_code": exit_code},
                success=exit_code == 0 if exit_code is not None else True,
            )
        
        elif item_type == "file_changes":
            changes = item.get("changes", [])
            yield ToolCallEndEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_id=item_id,
            )
            yield ToolResultEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_id=item_id,
                result={"files_changed": len(changes) if isinstance(changes, list) else 0},
                success=True,
            )
        
        elif item_type == "mcp_tool_call":
            result = item.get("result", "")
            yield ToolCallEndEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_id=item_id,
            )
            yield ToolResultEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_id=item_id,
                result=result,
                success=True,
            )
        
        elif item_type == "web_search":
            results_data = item.get("results", [])
            yield ToolCallEndEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_id=item_id,
            )
            yield ToolResultEvent(
                provider=self.name,
                session_id=context.session_id,
                tool_id=item_id,
                result=results_data,
                success=True,
            )

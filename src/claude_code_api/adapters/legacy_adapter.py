"""易事厅格式适配器

保持与现有易事厅系统的向后兼容
"""

import json
import re
from typing import Any, Dict, List, Optional

from .base_adapter import BaseAdapter, ProtocolType


class LegacyAdapter(BaseAdapter):
    """易事厅格式适配器（Legacy）"""
    
    def __init__(self):
        super().__init__()
        self.tool_input_buffer: Dict[int, tuple] = {}  # index -> (tool_name, params)
    
    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.LEGACY
    
    def _sanitize_text(self, text: str) -> str:
        """保持原始文本（Legacy SSE 里保留 <think> 标签，便于调用方自行处理）。"""
        return text
    
    def convert(self, claude_event: Dict[str, Any]) -> Optional[str]:
        """
        转换 Claude 事件为易事厅格式
        
        易事厅格式：
        event:delta
        data:{"response":"文本","finished":false,"global_output":{...}}
        """
        event_type = claude_event.get("type")
        
        # 跳过 result 类型（避免重复输出）
        if event_type == "result":
            return None
        
        # 处理 stream_event 类型
        if event_type == "stream_event":
            return self._handle_stream_event(claude_event)
        
        # 处理 user 类型（工具结果）
        if event_type == "user":
            return self._handle_user_event(claude_event)
        
        # 处理 system 类型（忽略）
        if event_type == "system":
            return None
        
        # 处理 assistant 类型（通常在 stream_event 中已处理）
        if event_type == "assistant":
            return None
        
        return None
    
    def _handle_stream_event(self, event: Dict[str, Any]) -> Optional[str]:
        """处理 stream_event 类型"""
        inner_event = event.get("event", {})
        inner_type = inner_event.get("type")
        
        # 处理文本增量
        if inner_type == "content_block_delta":
            delta = inner_event.get("delta", {})
            delta_type = delta.get("type")
            
            if delta_type == "text_delta":
                text = delta.get("text", "")
                text = self._sanitize_text(text)
                if text:
                    return self._format_response(text)
            
            elif delta_type == "input_json_delta":
                # 累积 JSON 片段（工具参数）
                partial = delta.get("partial_json", "")
                index = inner_event.get("index", 0)
                
                if index not in self.tool_input_buffer:
                    self.tool_input_buffer[index] = ("未知", "")
                
                tool_name, existing = self.tool_input_buffer[index]
                self.tool_input_buffer[index] = (tool_name, existing + partial)
                return None  # 累积中，不输出
        
        # 处理工具使用开始
        elif inner_type == "content_block_start":
            content_block = inner_event.get("content_block", {})
            if content_block.get("type") == "tool_use":
                tool_name = content_block.get("name", "未知")
                index = inner_event.get("index", 0)
                self.tool_input_buffer[index] = (tool_name, "")
                return None  # 暂不输出，等待参数收集完成
        
        # 处理工具使用结束
        elif inner_type == "content_block_stop":
            index = inner_event.get("index", 0)
            if index in self.tool_input_buffer:
                tool_name, params = self.tool_input_buffer[index]
                del self.tool_input_buffer[index]
                
                return self._format_tool_call(tool_name, params)

        # 结束事件（CCR 会输出 message_stop）
        elif inner_type in ("message_stop", "message_end"):
            return self._format_response("", finished=True, answer_success=1)

        return None
    
    def _handle_user_event(self, event: Dict[str, Any]) -> Optional[str]:
        """处理 user 事件（工具结果）"""
        message = event.get("message", {})
        content = message.get("content", [])
        
        # 如果 content 是字符串，直接返回
        if isinstance(content, str):
            return self._format_response(content)
        
        if not isinstance(content, list):
            return None
        
        formatted_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                is_error = item.get("is_error", False)
                content_text = item.get("content", "")
                
                if is_error:
                    formatted_parts.append(f"\n🚨 [工具错误]\n```text\n{content_text}\n```\n")
                else:
                    formatted_parts.append(f"\n🗒️ [工具结果]\n```text\n{content_text}\n```\n")
        
        if formatted_parts:
            return self._format_response("".join(formatted_parts))
        
        return None
    
    def _format_tool_call(self, tool_name: str, params: str) -> Optional[str]:
        """格式化工具调用"""
        if not params:
            return self._format_response(f"\n- 🛠️ [调用工具: {tool_name}]\n")
        
        try:
            params_obj = json.loads(params)
            
            # 特殊处理 todos
            if "todos" in params_obj:
                todos_markdown = self._format_todos_markdown(params_obj['todos'])
                return self._format_response(f"\n{todos_markdown}")
            
            # 其他工具
            if "command" in params_obj:
                return self._format_response(
                    f"\n🛠️ [调用工具: {tool_name}]\n```text\n{params_obj['command']}\n```\n"
                )
            elif "query" in params_obj:
                return self._format_response(
                    f"\n🛠️ [调用工具: {tool_name}]\n```text\n{params_obj['query']}\n```\n"
                )
            else:
                return self._format_response(
                    f"\n🛠️ [调用工具: {tool_name}]\n```json\n{params}\n```\n"
                )
        except json.JSONDecodeError:
            return self._format_response(
                f"\n🛠️ [调用工具: {tool_name}]\n```text\n{params}\n```\n"
            )
    
    def _format_todos_markdown(self, todos: List[Dict[str, Any]]) -> str:
        """格式化 todos 为 markdown"""
        if not todos:
            return ""
        
        status_mapping = {
            "completed": {"checkbox": "[x]", "emoji": "✅"},
            "in_progress": {"checkbox": "[ ]", "emoji": "🔄"},
            "pending": {"checkbox": "[ ]", "emoji": "⏳"},
            "cancelled": {"checkbox": "[ ]", "emoji": "❌"}
        }
        
        lines = ["### 📋 任务列表\n"]
        
        for todo in todos:
            content = todo.get("content", "")
            status = todo.get("status", "pending")
            
            mapping = status_mapping.get(status, {"checkbox": "[ ]", "emoji": "⏳"})
            checkbox = mapping["checkbox"]
            emoji = mapping["emoji"]
            
            if status == "in_progress":
                lines.append(f"- {checkbox} {emoji} **{content}** (进行中)")
            else:
                lines.append(f"- {checkbox} {emoji} {content}")
        
        lines.append("")
        return "\n".join(lines)
    
    def _format_response(self, text: str, finished: bool = False, answer_success: int = 0) -> str:
        """格式化为易事厅响应格式"""
        return self.format_sse({
            "response": text,
            "finished": finished,
            "global_output": {
                "context": "",
                "answer_success": answer_success,
                "docs": []
            }
        })
    
    def format_sse(self, data: Any) -> str:
        """格式化为易事厅 SSE 格式"""
        json_data = json.dumps(data, ensure_ascii=False)
        return f"event:delta\ndata:{json_data}\n\n"
    
    def create_start_event(self) -> Optional[str]:
        """Legacy 格式不需要开始事件"""
        return None
    
    def create_end_event(self, is_error: bool = False, error_msg: str = "") -> str:
        """创建结束事件"""
        if is_error:
            return self.format_sse({
                "response": error_msg,
                "finished": True,
                "global_output": {
                    "context": "",
                    "answer_success": 0,
                    "docs": []
                }
            })
        
        # Legacy 格式不需要显式的结束事件
        return ""
    
    def create_error_event(self, error_msg: str) -> str:
        """创建错误事件"""
        return self.format_sse({
            "response": error_msg,
            "finished": True,
            "global_output": {
                "context": "",
                "answer_success": 0,
                "docs": []
            }
        })

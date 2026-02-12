"""AG-UI 协议适配器

将 Claude Code stream-json 事件转换为 AG-UI 协议格式
"""

import json
import uuid
import re
import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from src.runtime.adapters.base import BaseAdapter, ProtocolType
from src.runtime.events.agui import (
    MessageRole,
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    StateSnapshotEvent,
)

logger = logging.getLogger(__name__)


@dataclass
class ParsedToolCall:
    """解析后的 subagent 工具调用"""
    tool_name: str
    arguments: Dict[str, Any]
    tool_id: str = ""
    
    def __post_init__(self):
        if not self.tool_id:
            self.tool_id = f"subagent_{uuid.uuid4().hex[:12]}"


class AGUIAdapter(BaseAdapter):
    """AG-UI 协议适配器"""
    
    def __init__(self):
        super().__init__()
        self._reset_tracking_state()
    
    def _reset_tracking_state(self):
        """重置跟踪状态（每次请求前调用）"""
        self._message_id_counter = 0
        # 跟踪是否已通过 stream_event 处理过内容，避免重复
        self._streamed_tool_ids: set = set()  # 已流式输出的 tool_use id
        self._has_streamed_text: bool = False  # 是否已通过 stream_event 流式输出过文本
        # 延迟发送 ToolCallStart，等待收集参数
        self._pending_tool_starts: dict = {}  # index -> (tool_name, tool_id, sent)
        self._tool_start_sent: set = set()  # 已发送 ToolCallStart 的 tool_id
        # 缓存未发送的 TOOL_CALL_ARGS（等待 TOOL_CALL_START 发送后再发送）
        self._pending_tool_args: dict = {}  # tool_id -> list of partial_json
    
    def init_state(self, thread_id: str, run_id: str) -> None:
        """初始化适配器状态（重写父类方法）"""
        super().init_state(thread_id, run_id)
        # 重置跟踪状态，确保每次请求都是干净的
        self._reset_tracking_state()
    
    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.AGUI
    
    def _generate_message_id(self) -> str:
        """生成消息ID
        
        使用 run_id + 计数器 确保每次请求的消息 ID 全局唯一，
        避免同一会话多次请求时消息 ID 冲突导致覆盖。
        """
        self._message_id_counter += 1
        run_id_suffix = self.state.run_id[:8] if self.state and self.state.run_id else uuid.uuid4().hex[:8]
        return f"msg_{run_id_suffix}_{self._message_id_counter:04d}"
    
    def _sanitize_text(self, text: str) -> str:
        """清理文本中的特殊标签
        
        注意：清理后可能变成空字符串，调用方需要检查
        注意：不再清理 <tool_call> 标签，由 _parse_subagent_tool_calls 单独处理
        """
        if not text:
            return ""
        # 移除 <think> 标签及其内容
        result = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        # 移除单独的 <think> 或 </think> 标签
        result = re.sub(r'</?think>', '', result)
        # 注意：不再移除 <tool_call> 标签，由 _parse_subagent_tool_calls 单独处理
        return result
    
    def _parse_subagent_tool_calls(self, text: str) -> Tuple[List[ParsedToolCall], str]:
        """解析 subagent 结果中的 <tool_call> 标签
        
        Args:
            text: 包含 <tool_call> 标签的文本
            
        Returns:
            (解析出的工具调用列表, 清理后的文本)
        """
        if not text or '<tool_call>' not in text:
            return [], text
        
        tool_calls = []
        
        # 匹配 <tool_call>...</tool_call> 块
        pattern = r'<tool_call>(.*?)</tool_call>'
        matches = re.findall(pattern, text, flags=re.DOTALL)
        
        for match in matches:
            try:
                parsed = self._parse_single_tool_call(match.strip())
                if parsed:
                    tool_calls.append(parsed)
            except Exception as e:
                logger.warning(f"Failed to parse tool_call: {e}")
                continue
        
        # 从文本中移除已解析的 tool_call 标签
        cleaned_text = re.sub(pattern, '', text, flags=re.DOTALL)
        # 移除单独的标签
        cleaned_text = re.sub(r'</?tool_call>', '', cleaned_text)
        
        return tool_calls, cleaned_text.strip()
    
    def _parse_single_tool_call(self, content: str) -> Optional[ParsedToolCall]:
        """解析单个 tool_call 内容
        
        格式示例:
        mcp__NOS-MCP__dify_knowledge_retrieve
        <arg_key>dataset_id</arg_key><arg_value>70c91f75-...</arg_value>
        <arg_key>query</arg_key><arg_value>SONiC回切...</arg_value>
        
        Args:
            content: tool_call 标签内的内容
            
        Returns:
            ParsedToolCall 对象，解析失败返回 None
        """
        if not content:
            return None
        
        lines = content.strip().split('\n')
        if not lines:
            return None
        
        # 第一行是工具名称
        tool_name = lines[0].strip()
        if not tool_name:
            return None
        
        # 解析参数
        arguments = {}
        remaining_content = '\n'.join(lines[1:]) if len(lines) > 1 else ''
        
        # 匹配 <arg_key>key</arg_key><arg_value>value</arg_value> 格式
        arg_pattern = r'<arg_key>(.*?)</arg_key>\s*<arg_value>(.*?)</arg_value>'
        arg_matches = re.findall(arg_pattern, remaining_content, flags=re.DOTALL)
        
        for key, value in arg_matches:
            key = key.strip()
            value = value.strip()
            if key:
                # 尝试解析 JSON 值
                try:
                    arguments[key] = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    arguments[key] = value
        
        return ParsedToolCall(
            tool_name=tool_name,
            arguments=arguments
        )
    
    def _get_tool_display_name(self, tool_name: str, params_json: str) -> str:
        """根据工具名称和参数生成更有意义的显示名称
        
        Args:
            tool_name: 原始工具名称
            params_json: 工具参数的 JSON 字符串
            
        Returns:
            带上下文的工具显示名称
        """
        try:
            params = json.loads(params_json) if params_json else {}
        except json.JSONDecodeError:
            return tool_name
        
        # 根据工具类型添加上下文信息
        # 注意：Claude Code 返回的工具名称是 Task、Skill、Read 等简化名称
        if tool_name == "Task" or tool_name == "task":
            # Task: 显示 subagent_type 和 description
            subagent = params.get("subagent_type", params.get("subagent_name", ""))
            desc = params.get("description", "")
            if subagent and desc:
                return f"Task: {subagent} - {desc}"
            elif subagent:
                return f"Task: {subagent}"
            elif desc:
                return f"Task: {desc}"
        
        elif tool_name == "Skill" or tool_name == "use_skill":
            # Skill: 显示具体的 skill 名称
            skill = params.get("skill", params.get("command", ""))
            if skill:
                return f"Skill: {skill}"
        
        elif tool_name == "Read" or tool_name == "read_file":
            # Read: 显示文件路径
            file_path = params.get("file_path", params.get("filePath", ""))
            if file_path:
                return f"Read: {file_path}"
        
        elif tool_name == "Write" or tool_name == "write_to_file":
            # Write: 显示文件路径
            file_path = params.get("file_path", params.get("filePath", ""))
            if file_path:
                return f"Write: {file_path}"
        
        elif tool_name == "Edit" or tool_name == "replace_in_file":
            # Edit: 显示文件路径
            file_path = params.get("file_path", params.get("filePath", ""))
            if file_path:
                return f"Edit: {file_path}"
        
        elif tool_name == "Grep" or tool_name == "search_content":
            # Grep: 显示搜索路径
            path = params.get("path", params.get("directory", ""))
            if path:
                return f"Grep: {path}"
        
        elif tool_name == "Glob" or tool_name == "search_file":
            # Glob: 显示搜索路径或模式
            path = params.get("path", params.get("target_directory", ""))
            pattern = params.get("pattern", "")
            if path and pattern:
                return f"Glob: {pattern} in {path}"
            elif path:
                return f"Glob: {path}"
            elif pattern:
                return f"Glob: {pattern}"
        
        elif tool_name == "Bash" or tool_name == "execute_command":
            # Bash: 显示 explanation/description
            explanation = params.get("explanation", params.get("description", ""))
            if explanation:
                return f"Bash: {explanation}"
        
        elif tool_name == "TodoWrite" or tool_name == "todo_write":
            # TodoWrite: 显示 Todos: 当前进度/总数 - 当前任务内容
            todos_str = params.get("todos", "")
            if todos_str:
                try:
                    todos = json.loads(todos_str) if isinstance(todos_str, str) else todos_str
                    if isinstance(todos, list) and todos:
                        total = len(todos)
                        # 找到 in_progress 的任务
                        current_index = 0
                        current_content = ""
                        for i, todo in enumerate(todos):
                            if isinstance(todo, dict) and todo.get("status") == "in_progress":
                                current_index = i + 1
                                current_content = todo.get("content", "")
                                break
                        
                        if current_index > 0 and current_content:
                            return f"Todos: {current_index}/{total} - {current_content}"
                        elif current_index > 0:
                            return f"Todos: {current_index}/{total}"
                        else:
                            # 没有 in_progress，显示总数
                            return f"Todos: {total} items"
                except (json.JSONDecodeError, TypeError):
                    pass
        
        # mcp__xxx 和其他工具保持原名
        return tool_name
    
    def convert(self, claude_event: Dict[str, Any]) -> Optional[str]:
        """
        转换 Claude 事件为 AG-UI 格式

        事件映射：
        - system + init → RunStarted (已在 create_start_event 处理)
        - assistant + text → TextMessageStart/Content
        - assistant + tool_use → ToolCallStart
        - stream_event + text_delta → TextMessageContent
        - stream_event + input_json_delta → ToolCallArgs
        - stream_event + content_block_start (tool_use) → ToolCallStart
        - stream_event + content_block_stop → ToolCallEnd (for tools)
        - user + tool_result → ToolCallEnd
        - result → RunFinished (已在 create_end_event 处理)
        """
        if not self.state:
            return None

        # 类型检查：确保 claude_event 是字典
        if not isinstance(claude_event, dict):
            return None

        event_type = claude_event.get("type")
        # 记录所有事件类型以便调试（使用 INFO 级别确保可见）
        if event_type == "stream_event":
            inner_type = claude_event.get("event", {}).get("type", "unknown")
            logger.info(f"[AGUI] Convert event: type={event_type}, inner_type={inner_type}")
        elif event_type in ("user", "assistant", "result"):
            logger.info(f"[AGUI] Convert event: type={event_type}")
        
        # 处理 system 事件
        if event_type == "system":
            return self._handle_system_event(claude_event)
        
        # 处理 stream_event 事件
        elif event_type == "stream_event":
            return self._handle_stream_event(claude_event)
        
        # 处理 assistant 事件
        elif event_type == "assistant":
            return self._handle_assistant_event(claude_event)
        
        # 处理 user 事件（工具结果）
        elif event_type == "user":
            return self._handle_user_event(claude_event)
        
        # 处理 result 事件
        elif event_type == "result":
            return self._handle_result_event(claude_event)
        
        return None
    
    def _handle_system_event(self, event: Dict[str, Any]) -> Optional[str]:
        """处理 system 事件"""
        subtype = event.get("subtype")
        
        if subtype == "init":
            # 发送状态快照（包含工具列表等信息）
            tools = event.get("tools", [])
            model = event.get("model")
            
            state_event = StateSnapshotEvent(
                snapshot={
                    "tools": tools,
                    "model": model,
                    "sessionId": event.get("session_id"),
                    "agents": event.get("agents", []),
                    "skills": event.get("skills", []),
                }
            )
            return state_event.to_sse()
        
        return None
    
    def _handle_stream_event(self, event: Dict[str, Any]) -> Optional[str]:
        """处理 stream_event 事件"""
        inner_event = event.get("event", {})
        
        # 类型检查：确保 inner_event 是字典
        if not isinstance(inner_event, dict):
            return None
        
        inner_type = inner_event.get("type")
        
        # 处理内容块开始
        if inner_type == "content_block_start":
            return self._handle_content_block_start(inner_event)
        
        # 处理内容块增量
        elif inner_type == "content_block_delta":
            return self._handle_content_block_delta(inner_event)
        
        # 处理内容块结束
        elif inner_type == "content_block_stop":
            return self._handle_content_block_stop(inner_event)
        
        return None
    
    def _handle_content_block_start(self, event: Dict[str, Any]) -> Optional[str]:
        """处理 content_block_start 事件"""
        content_block = event.get("content_block", {})
        if not isinstance(content_block, dict):
            return None
        
        block_type = content_block.get("type")
        index = event.get("index", 0)
        
        if block_type == "tool_use":
            # 工具调用开始
            tool_name = content_block.get("name", "unknown")
            tool_id = content_block.get("id", str(uuid.uuid4()))
            
            # 保存到缓冲区，延迟发送 ToolCallStart
            self.state.tool_input_buffer[index] = (tool_name, tool_id, "")
            self.state.active_tool_calls[tool_id] = tool_name
            
            # 标记此工具已通过流式输出
            self._streamed_tool_ids.add(tool_id)
            
            # 记录待发送的 ToolCallStart（延迟到收到参数后发送）
            self._pending_tool_starts[index] = (tool_name, tool_id)
            
            # 不立即发送 ToolCallStart，等待参数
            return None
        
        elif block_type == "text":
            # 文本块开始 - 如果还没有开始消息，发送 TextMessageStart
            if not self.state.message_started:
                self.state.current_message_id = self._generate_message_id()
                self.state.message_started = True
                
                msg_start = TextMessageStartEvent(
                    messageId=self.state.current_message_id,
                    role=MessageRole.ASSISTANT
                )
                return msg_start.to_sse()
        
        return None
    
    def _handle_content_block_delta(self, event: Dict[str, Any]) -> Optional[str]:
        """处理 content_block_delta 事件"""
        delta = event.get("delta", {})
        if not isinstance(delta, dict):
            return None
        
        delta_type = delta.get("type")
        index = event.get("index", 0)
        
        if delta_type == "text_delta":
            # 文本增量
            text = delta.get("text", "")
            text = self._sanitize_text(text)
            
            # 跳过空文本或只有空白字符的文本
            if not text or not text.strip():
                return None
            
            # 标记已流式输出过文本
            self._has_streamed_text = True
            
            # 确保消息已开始
            if not self.state.message_started:
                self.state.current_message_id = self._generate_message_id()
                self.state.message_started = True
                
                # 先发送 TextMessageStart
                msg_start = TextMessageStartEvent(
                    messageId=self.state.current_message_id,
                    role=MessageRole.ASSISTANT
                )
                start_sse = msg_start.to_sse()
                
                # 再发送内容
                content_event = TextMessageContentEvent(
                    messageId=self.state.current_message_id,
                    delta=text
                )
                return start_sse + content_event.to_sse()
            
            # 发送 TextMessageContent
            content_event = TextMessageContentEvent(
                messageId=self.state.current_message_id,
                delta=text
            )
            return content_event.to_sse()
        
        elif delta_type == "input_json_delta":
            # 工具参数增量
            partial_json = delta.get("partial_json", "")
            
            if index in self.state.tool_input_buffer:
                tool_name, tool_id, existing = self.state.tool_input_buffer[index]
                new_params = existing + partial_json
                self.state.tool_input_buffer[index] = (tool_name, tool_id, new_params)
                
                results = []
                
                # 检查是否需要发送延迟的 ToolCallStart
                if tool_id not in self._tool_start_sent and index in self._pending_tool_starts:
                    # 对于 Task 和 TodoWrite 工具，等待参数可解析后再发送
                    # 对于其他工具，立即发送
                    should_send = True
                    display_name = tool_name
                    
                    if tool_name in ("Task", "task", "TodoWrite", "todo_write"):
                        # 这些工具需要等待参数可解析
                        try:
                            params = json.loads(new_params)
                            # 参数可解析，生成显示名称
                            display_name = self._get_tool_display_name(tool_name, new_params)
                        except json.JSONDecodeError:
                            # 参数还不完整，缓存 partial_json
                            should_send = False
                            if partial_json:
                                if tool_id not in self._pending_tool_args:
                                    self._pending_tool_args[tool_id] = []
                                self._pending_tool_args[tool_id].append(partial_json)
                    else:
                        # 其他工具尝试解析，解析失败也发送
                        display_name = self._get_tool_display_name(tool_name, new_params)
                    
                    if should_send:
                        tool_start = ToolCallStartEvent(
                            toolCallId=tool_id,
                            toolCallName=display_name,
                            parentMessageId=self.state.current_message_id
                        )
                        results.append(tool_start.to_sse())
                        self._tool_start_sent.add(tool_id)
                        del self._pending_tool_starts[index]
                        
                        # 发送之前缓存的 TOOL_CALL_ARGS
                        if tool_id in self._pending_tool_args:
                            for cached_json in self._pending_tool_args[tool_id]:
                                if cached_json and cached_json.strip():  # 确保不发送空字符串
                                    args_event = ToolCallArgsEvent(
                                        toolCallId=tool_id,
                                        delta=cached_json
                                    )
                                    results.append(args_event.to_sse())
                            del self._pending_tool_args[tool_id]
                
                # 只有当 TOOL_CALL_START 已发送且 partial_json 不为空时才发送 ToolCallArgs
                if tool_id in self._tool_start_sent and partial_json and partial_json.strip():
                    args_event = ToolCallArgsEvent(
                        toolCallId=tool_id,
                        delta=partial_json
                    )
                    results.append(args_event.to_sse())
                
                return "".join(results) if results else None
        
        return None
    
    def _handle_content_block_stop(self, event: Dict[str, Any]) -> Optional[str]:
        """处理 content_block_stop 事件

        注意：不在这里发送 ToolCallEnd，因为此时还没有 ToolCallResult。
        ToolCallEnd 会在 _handle_user_event 中与 ToolCallResult 一起发送，确保正确的事件顺序。
        """
        index = event.get("index", 0)

        logger.info(f"[AGUI] content_block_stop: index={index}, pending_tools={list(self._pending_tool_starts.keys())}, buffer_keys={list(self.state.tool_input_buffer.keys())}")

        results = []

        # 检查是否有未发送的 ToolCallStart（工具没有参数的情况）
        if index in self._pending_tool_starts:
            tool_name, tool_id = self._pending_tool_starts[index]
            if tool_id not in self._tool_start_sent:
                # 没有参数，使用原始工具名
                params = ""
                if index in self.state.tool_input_buffer:
                    _, _, params = self.state.tool_input_buffer[index]

                display_name = self._get_tool_display_name(tool_name, params)

                tool_start = ToolCallStartEvent(
                    toolCallId=tool_id,
                    toolCallName=display_name,
                    parentMessageId=self.state.current_message_id
                )
                results.append(tool_start.to_sse())
                self._tool_start_sent.add(tool_id)
            del self._pending_tool_starts[index]

        # 从 tool_input_buffer 中移除（但不发送 ToolCallEnd）
        # ToolCallEnd 将在 _handle_user_event 中与 ToolCallResult 一起发送
        if index in self.state.tool_input_buffer:
            tool_name, tool_id, params = self.state.tool_input_buffer[index]
            del self.state.tool_input_buffer[index]
            logger.info(f"[AGUI] content_block_stop: removed tool_id={tool_id}, tool_name={tool_name} from buffer (will send End in user event)")
        else:
            logger.warning(f"[AGUI] content_block_stop: index={index} NOT in tool_input_buffer!")

        return "".join(results) if results else None
    
    def _handle_assistant_event(self, event: Dict[str, Any]) -> Optional[str]:
        """处理 assistant 事件
        
        注意：assistant 事件是完整消息的汇总。
        如果内容已通过 stream_event 流式输出，则跳过避免重复。
        """
        message = event.get("message", {})
        if not isinstance(message, dict):
            return None
        
        content = message.get("content", [])
        stop_reason = message.get("stop_reason")
        
        results = []
        
        # 确保 content 是列表
        if not isinstance(content, list):
            content = []
        
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type")
                
                if item_type == "text":
                    # 如果已经通过 stream_event 流式输出过文本，跳过
                    if self._has_streamed_text:
                        continue
                    
                    text = item.get("text", "")
                    text = self._sanitize_text(text)
                    
                    # 跳过空文本或只有空白字符的文本
                    if not text or not text.strip():
                        continue
                    
                    if text:
                        # 确保消息已开始
                        if not self.state.message_started:
                            self.state.current_message_id = self._generate_message_id()
                            self.state.message_started = True
                            
                            msg_start = TextMessageStartEvent(
                                messageId=self.state.current_message_id,
                                role=MessageRole.ASSISTANT
                            )
                            results.append(msg_start.to_sse())
                        
                        content_event = TextMessageContentEvent(
                            messageId=self.state.current_message_id,
                            delta=text
                        )
                        results.append(content_event.to_sse())
                
                elif item_type == "tool_use":
                    tool_id = item.get("id", str(uuid.uuid4()))
                    
                    # 如果已通过 stream_event 处理过，跳过
                    if tool_id in self._streamed_tool_ids:
                        continue
                    
                    tool_name = item.get("name", "unknown")
                    tool_input = item.get("input", {})
                    
                    # 生成带上下文的显示名称
                    params_json = json.dumps(tool_input, ensure_ascii=False) if tool_input else ""
                    display_name = self._get_tool_display_name(tool_name, params_json)
                    
                    # 发送 ToolCallStart
                    tool_start = ToolCallStartEvent(
                        toolCallId=tool_id,
                        toolCallName=display_name,
                        parentMessageId=self.state.current_message_id
                    )
                    results.append(tool_start.to_sse())
                    
                    # 发送完整参数（只有当 tool_input 非空时）
                    if tool_input:
                        args_str = json.dumps(tool_input, ensure_ascii=False)
                        if args_str and args_str.strip() and args_str != "{}":
                            args_event = ToolCallArgsEvent(
                                toolCallId=tool_id,
                                delta=args_str
                            )
                            results.append(args_event.to_sse())
                    
                    self.state.active_tool_calls[tool_id] = tool_name
        
        # 如果 stop_reason 是 end_turn，发送消息结束
        if stop_reason == "end_turn" and self.state.message_started:
            msg_end = TextMessageEndEvent(messageId=self.state.current_message_id)
            results.append(msg_end.to_sse())
            self.state.message_started = False
        
        return "".join(results) if results else None
    
    def _handle_user_event(self, event: Dict[str, Any]) -> Optional[str]:
        """处理 user 事件（工具结果）

        这里发送 ToolCallResult 和 ToolCallEnd，确保正确的事件顺序：
        ToolCallStart → ToolCallArgs → ToolCallResult → ToolCallEnd
        
        对于 subagent 的工具调用（<tool_call> 格式），会生成嵌套的 ToolCall 事件
        """
        logger.info(f"[AGUI] Handling user event: {json.dumps(event, ensure_ascii=False)[:500]}")
        message = event.get("message", {})
        if not isinstance(message, dict):
            message = {}

        content = message.get("content", [])
        if not isinstance(content, list):
            content = []

        results = []
        processed_tool_ids = set()  # 避免重复处理

        # 处理 content 中的 tool_result
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    tool_use_id = item.get("tool_use_id")
                    is_error = item.get("is_error", False)
                    result_content = item.get("content", "")

                    if not tool_use_id or tool_use_id in processed_tool_ids:
                        continue

                    processed_tool_ids.add(tool_use_id)

                    # 获取原始文本内容
                    raw_result_str = self._get_raw_result_string(result_content)
                    
                    # 解析 subagent 工具调用
                    subagent_calls, cleaned_result = self._parse_subagent_tool_calls(raw_result_str)
                    
                    # 为每个 subagent 工具调用生成事件
                    for call in subagent_calls:
                        subagent_events = self._generate_subagent_tool_events(call)
                        results.extend(subagent_events)
                    
                    # 清理并截断结果
                    result_str = self._sanitize_text(cleaned_result)
                    if is_error:
                        result_str = f"[ERROR] {result_str}"
                    result_str = result_str[:1000] if len(result_str) > 1000 else result_str

                    # 发送 ToolCallResult 事件（结果）
                    tool_result = ToolCallResultEvent(
                        messageId=self.state.current_message_id or self._generate_message_id(),
                        toolCallId=tool_use_id,
                        content=result_str
                    )
                    results.append(tool_result.to_sse())
                    logger.info(f"[AGUI] Sending ToolCallResult: tool_id={tool_use_id}, content_len={len(result_str)}, subagent_calls={len(subagent_calls)}")

                    # 紧接着发送 ToolCallEnd，确保正确的事件顺序
                    tool_end = ToolCallEndEvent(toolCallId=tool_use_id)
                    results.append(tool_end.to_sse())
                    logger.info(f"[AGUI] Sending ToolCallEnd: tool_id={tool_use_id}")

                    # 从 active_tool_calls 中移除（如果存在）
                    if tool_use_id in self.state.active_tool_calls:
                        del self.state.active_tool_calls[tool_use_id]

        return "".join(results) if results else None
    
    def _get_raw_result_string(self, result_content: Any) -> str:
        """获取 tool_result 的原始字符串内容（不清理标签）"""
        if isinstance(result_content, str):
            return result_content
        elif isinstance(result_content, list):
            text_parts = []
            for item in result_content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    if isinstance(text, str):
                        text_parts.append(text)
                elif isinstance(item, str):
                    text_parts.append(item)
                else:
                    text_parts.append(str(item))
            return "\n".join(text_parts) if text_parts else ""
        elif result_content is None:
            return ""
        else:
            return str(result_content)
    
    def _generate_subagent_tool_events(self, call: ParsedToolCall) -> List[str]:
        """为 subagent 工具调用生成 ToolCall 事件序列
        
        Args:
            call: 解析后的工具调用
            
        Returns:
            SSE 事件字符串列表
        """
        events = []
        
        # 生成带上下文的显示名称
        params_json = json.dumps(call.arguments, ensure_ascii=False) if call.arguments else ""
        display_name = self._get_tool_display_name(call.tool_name, params_json)
        
        # ToolCallStart
        tool_start = ToolCallStartEvent(
            toolCallId=call.tool_id,
            toolCallName=display_name,
            parentMessageId=self.state.current_message_id
        )
        events.append(tool_start.to_sse())
        logger.info(f"[AGUI] Subagent ToolCallStart: tool_id={call.tool_id}, name={display_name}")
        
        # ToolCallArgs（如果有参数）
        if call.arguments:
            args_str = json.dumps(call.arguments, ensure_ascii=False)
            if args_str and args_str.strip() and args_str != "{}":
                args_event = ToolCallArgsEvent(
                    toolCallId=call.tool_id,
                    delta=args_str
                )
                events.append(args_event.to_sse())
        
        # ToolCallEnd
        tool_end = ToolCallEndEvent(toolCallId=call.tool_id)
        events.append(tool_end.to_sse())
        logger.info(f"[AGUI] Subagent ToolCallEnd: tool_id={call.tool_id}")
        
        return events
    
    def _convert_result_to_string(self, result_content: Any) -> str:
        """将 tool_result 的 content 转换为字符串
        
        注意：会清理结果中的特殊标签（如 <think>）
        注意：<tool_call> 标签由 _parse_subagent_tool_calls 单独处理
        """
        result_str = ""
        if isinstance(result_content, str):
            result_str = result_content
        elif isinstance(result_content, list):
            # 提取文本内容
            text_parts = []
            for item in result_content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    if isinstance(text, str):
                        text_parts.append(text)
                elif isinstance(item, str):
                    text_parts.append(item)
                else:
                    text_parts.append(str(item))
            result_str = "\n".join(text_parts) if text_parts else "(empty result)"
        elif result_content is None:
            return "(no result)"
        else:
            result_str = str(result_content)
        
        # 清理结果中的特殊标签（不包括 tool_call，由单独的方法处理）
        # 先解析并移除 tool_call 标签
        _, cleaned = self._parse_subagent_tool_calls(result_str)
        return self._sanitize_text(cleaned)
    
    def _handle_result_event(self, event: Dict[str, Any]) -> Optional[str]:
        """处理 result 事件
        
        当 CLI 返回错误时（is_error=true），发送错误文本消息和 RUN_ERROR 事件通知前端
        """
        is_error = event.get("is_error", False)
        
        if is_error:
            # 获取错误信息
            error_msg = event.get("result", "Unknown error")
            
            # 记录错误日志
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"CLI returned error: {error_msg}")
            
            results = []
            
            # 先发送错误文本消息，确保前端能看到错误内容
            error_text = f"\n\n⚠️ **错误**: {error_msg}"
            
            # 如果当前没有消息在进行，创建一个新消息
            if self.state and not self.state.message_started:
                msg_id = f"error-msg-{uuid.uuid4()}"
                self.state.current_message_id = msg_id
                self.state.message_started = True
                msg_start = TextMessageStartEvent(
                    messageId=msg_id,
                    role=MessageRole.ASSISTANT
                )
                results.append(msg_start.to_sse())
            
            # 发送错误文本内容
            if self.state and self.state.current_message_id:
                msg_content = TextMessageContentEvent(
                    messageId=self.state.current_message_id,
                    delta=error_text
                )
                results.append(msg_content.to_sse())
                
                # 结束消息
                msg_end = TextMessageEndEvent(messageId=self.state.current_message_id)
                results.append(msg_end.to_sse())
                self.state.message_started = False
            
            # 发送 RUN_ERROR 事件
            run_error = RunErrorEvent(
                threadId=self.state.thread_id if self.state else "unknown",
                runId=self.state.run_id if self.state else "unknown",
                message=error_msg
            )
            results.append(run_error.to_sse())
            
            # 标记已发生错误，供 create_end_event 使用
            if self.state:
                self.state.has_error = True
            
            return "".join(results)
        
        # 处理斜杠命令的成功响应
        subtype = event.get("subtype")
        if subtype == "slash_command":
            content = event.get("content", "")
            if content:
                results = []
                
                # 创建新消息
                if self.state and not self.state.message_started:
                    msg_id = f"slash-msg-{uuid.uuid4()}"
                    self.state.current_message_id = msg_id
                    self.state.message_started = True
                    msg_start = TextMessageStartEvent(
                        messageId=msg_id,
                        role=MessageRole.ASSISTANT
                    )
                    results.append(msg_start.to_sse())
                
                # 发送内容
                if self.state and self.state.current_message_id:
                    msg_content = TextMessageContentEvent(
                        messageId=self.state.current_message_id,
                        delta=content
                    )
                    results.append(msg_content.to_sse())
                    
                    # 结束消息
                    msg_end = TextMessageEndEvent(messageId=self.state.current_message_id)
                    results.append(msg_end.to_sse())
                    self.state.message_started = False
                
                return "".join(results)
        
        # 非错误情况，在 create_end_event 中处理
        return None
    
    def format_sse(self, data: Any) -> str:
        """格式化为 AG-UI SSE 格式"""
        if hasattr(data, "to_sse"):
            return data.to_sse()
        
        json_str = json.dumps(data, ensure_ascii=False)
        return f"data: {json_str}\n\n"
    
    def create_start_event(self) -> Optional[str]:
        """创建运行开始事件"""
        if not self.state:
            return None
        
        if self.state.run_started:
            return None
        
        self.state.run_started = True
        
        run_started = RunStartedEvent(
            threadId=self.state.thread_id,
            runId=self.state.run_id
        )
        return run_started.to_sse()
    
    def create_end_event(self, is_error: bool = False, error_msg: str = "") -> str:
        """创建运行结束事件"""
        if not self.state:
            return ""
        
        results = []
        
        # 如果消息还在进行中，先结束消息
        if self.state.message_started and self.state.current_message_id:
            msg_end = TextMessageEndEvent(messageId=self.state.current_message_id)
            results.append(msg_end.to_sse())
            self.state.message_started = False
        
        # 发送运行结束事件
        if is_error:
            run_error = RunErrorEvent(
                threadId=self.state.thread_id,
                runId=self.state.run_id,
                message=error_msg
            )
            results.append(run_error.to_sse())
        
        run_finished = RunFinishedEvent(
            threadId=self.state.thread_id,
            runId=self.state.run_id
        )
        results.append(run_finished.to_sse())
        
        self.state.run_finished = True
        
        return "".join(results)
    
    def create_error_event(self, error_msg: str) -> str:
        """创建错误事件"""
        if not self.state:
            thread_id = f"error-{uuid.uuid4()}"
            run_id = f"error-run-{uuid.uuid4()}"
        else:
            thread_id = self.state.thread_id
            run_id = self.state.run_id
        
        run_error = RunErrorEvent(
            threadId=thread_id,
            runId=run_id,
            message=error_msg
        )
        return run_error.to_sse()

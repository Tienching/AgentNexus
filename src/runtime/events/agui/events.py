"""AG-UI 协议事件模型定义

基于 AG-UI Protocol 规范定义事件类型
参考: https://docs.ag-ui.com/concepts/events
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import json
import uuid as uuid_lib


class AGUIEventType(str, Enum):
    """AG-UI 事件类型
    
    根据 ag-ui-protocol 官方 SDK，事件类型使用全大写下划线格式
    """
    # Lifecycle Events
    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_ERROR = "RUN_ERROR"
    STEP_STARTED = "STEP_STARTED"
    STEP_FINISHED = "STEP_FINISHED"
    
    # Text Message Events
    TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
    TEXT_MESSAGE_END = "TEXT_MESSAGE_END"
    
    # Tool Call Events
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_ARGS = "TOOL_CALL_ARGS"
    TOOL_CALL_END = "TOOL_CALL_END"
    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"
    
    # State Events
    STATE_SNAPSHOT = "STATE_SNAPSHOT"
    STATE_DELTA = "STATE_DELTA"
    
    # Activity Events
    ACTIVITY_SNAPSHOT = "ACTIVITY_SNAPSHOT"
    ACTIVITY_DELTA = "ACTIVITY_DELTA"
    
    # Message Events
    MESSAGES_SNAPSHOT = "MESSAGES_SNAPSHOT"
    
    # Custom Events
    CUSTOM = "CUSTOM"
    RAW = "RAW"


class MessageRole(str, Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


# ============ Base Event ============

class AGUIBaseEvent(BaseModel):
    """AG-UI 事件基类"""
    type: AGUIEventType
    
    def to_sse(self, include_event_line: bool = False) -> str:
        """转换为SSE格式
        
        根据 ag-ui-protocol 官方 SDK (EventEncoder)，SSE 格式为：
        data: <json_payload>\n\n
        
        type 字段在 JSON 内部，使用全大写下划线格式
        
        Args:
            include_event_line: 是否包含 event: 行（某些客户端可能需要）
        """
        data = self.model_dump(exclude_none=True, by_alias=True)
        # 获取事件类型字符串
        event_type = data["type"].value if isinstance(data["type"], AGUIEventType) else data["type"]
        # 将 type 转换为字符串值
        data["type"] = event_type
        # 使用紧凑格式（无空格），与官方 SDK 一致
        json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        
        if include_event_line:
            # 某些客户端可能需要 event: 行
            return f"event: {event_type}\ndata: {json_str}\n\n"
        return f"data: {json_str}\n\n"


# ============ Lifecycle Events ============

class RunStartedEvent(AGUIBaseEvent):
    """运行开始事件"""
    type: AGUIEventType = Field(default=AGUIEventType.RUN_STARTED)
    threadId: str
    runId: str


class RunFinishedEvent(AGUIBaseEvent):
    """运行完成事件"""
    type: AGUIEventType = Field(default=AGUIEventType.RUN_FINISHED)
    threadId: str
    runId: str


class RunErrorEvent(AGUIBaseEvent):
    """运行错误事件"""
    type: AGUIEventType = Field(default=AGUIEventType.RUN_ERROR)
    threadId: str
    runId: str
    message: str
    code: Optional[str] = None


class StepStartedEvent(AGUIBaseEvent):
    """步骤开始事件 - 用于表示子agent调用开始"""
    type: AGUIEventType = Field(default=AGUIEventType.STEP_STARTED)
    stepName: str
    parentToolUseId: Optional[str] = None


class StepFinishedEvent(AGUIBaseEvent):
    """步骤结束事件 - 用于表示子agent调用结束"""
    type: AGUIEventType = Field(default=AGUIEventType.STEP_FINISHED)
    stepName: str
    parentToolUseId: Optional[str] = None


# ============ Text Message Events ============

class TextMessageStartEvent(AGUIBaseEvent):
    """文本消息开始事件"""
    type: AGUIEventType = Field(default=AGUIEventType.TEXT_MESSAGE_START)
    messageId: str
    role: MessageRole = Field(default=MessageRole.ASSISTANT)


class TextMessageContentEvent(AGUIBaseEvent):
    """文本消息内容事件（流式增量）"""
    type: AGUIEventType = Field(default=AGUIEventType.TEXT_MESSAGE_CONTENT)
    messageId: str
    delta: str = Field(..., min_length=1, description="文本增量，不能为空字符串")


class TextMessageEndEvent(AGUIBaseEvent):
    """文本消息结束事件"""
    type: AGUIEventType = Field(default=AGUIEventType.TEXT_MESSAGE_END)
    messageId: str


# ============ Tool Call Events ============

class ToolCallStartEvent(AGUIBaseEvent):
    """工具调用开始事件"""
    type: AGUIEventType = Field(default=AGUIEventType.TOOL_CALL_START)
    toolCallId: str
    toolCallName: str
    parentMessageId: Optional[str] = None


_TOOL_CALL_DESCRIPTION_KEYS = (
    "description",
    "explanation",
    "query",
    "command",
    "pattern",
    "path",
    "file_path",
    "filePath",
)


def extract_tool_call_description(arguments: Any) -> Optional[str]:
    """Extract a concise human-readable description from known tool arguments."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return None

    if not isinstance(arguments, dict):
        return None

    for key in _TOOL_CALL_DESCRIPTION_KEYS:
        value = arguments.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped

    return None


def build_tool_call_name(
    tool_name: str,
    arguments: Any = None,
    *,
    description: Optional[str] = None,
    display_name: Optional[str] = None,
) -> str:
    """Build the AG-UI standard toolCallName with provider/context details."""
    resolved_display_name = display_name.strip() if isinstance(display_name, str) else ""
    if resolved_display_name and resolved_display_name != tool_name:
        return resolved_display_name

    params = arguments
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except json.JSONDecodeError:
            params = None

    if isinstance(params, dict):
        tool_key = (tool_name or "").strip().lower()
        if tool_key == "taskoutput":
            if params.get("block") is True:
                return "TaskOutput: 等待任务输出"
            return "TaskOutput: 读取任务输出"

        if tool_key in ("skill", "use_skill"):
            skill = (
                params.get("skill")
                or params.get("skill_name")
                or params.get("name")
                or params.get("command")
            )
            if isinstance(skill, str) and skill.strip():
                return f"Skill: {skill.strip()}"

    explicit_description = description.strip() if isinstance(description, str) else ""
    resolved_description = explicit_description or extract_tool_call_description(arguments)
    if resolved_description and resolved_description not in tool_name:
        return f"{tool_name}: {resolved_description}"

    return tool_name


class ToolCallArgsEvent(AGUIBaseEvent):
    """工具调用参数事件（流式增量）"""
    type: AGUIEventType = Field(default=AGUIEventType.TOOL_CALL_ARGS)
    toolCallId: str
    delta: str = Field(..., min_length=1, description="参数增量，不能为空字符串")


class ToolCallEndEvent(AGUIBaseEvent):
    """工具调用结束事件"""
    type: AGUIEventType = Field(default=AGUIEventType.TOOL_CALL_END)
    toolCallId: str
    result: Optional[str] = Field(default=None, description="工具调用结果，必须是字符串")
    
    def model_post_init(self, __context) -> None:
        """确保 result 是字符串类型"""
        if self.result is not None and not isinstance(self.result, str):
            object.__setattr__(self, 'result', str(self.result))


class ToolCallResultEvent(AGUIBaseEvent):
    """工具调用结果事件 - 用于返回工具执行结果"""
    type: AGUIEventType = Field(default=AGUIEventType.TOOL_CALL_RESULT)
    messageId: str = Field(description="此结果所属的消息ID")
    toolCallId: str = Field(description="对应的工具调用ID")
    content: str = Field(description="工具执行结果内容")
    role: Optional[str] = Field(default="tool", description="角色标识")


# ============ State Events ============

class StateSnapshotEvent(AGUIBaseEvent):
    """状态快照事件"""
    type: AGUIEventType = Field(default=AGUIEventType.STATE_SNAPSHOT)
    snapshot: Dict[str, Any] = Field(default_factory=dict)


class StateDeltaEvent(AGUIBaseEvent):
    """状态增量事件"""
    type: AGUIEventType = Field(default=AGUIEventType.STATE_DELTA)
    delta: List[Dict[str, Any]] = Field(default_factory=list)


# ============ Message Models ============

class AGUIMessage(BaseModel):
    """AG-UI 消息模型"""
    id: str
    role: MessageRole
    content: str
    createdAt: Optional[str] = None


class MessagesSnapshotEvent(AGUIBaseEvent):
    """消息快照事件"""
    type: AGUIEventType = Field(default=AGUIEventType.MESSAGES_SNAPSHOT)
    messages: List[AGUIMessage] = Field(default_factory=list)


# ============ Custom Events ============

class CustomEvent(AGUIBaseEvent):
    """自定义事件"""
    type: AGUIEventType = Field(default=AGUIEventType.CUSTOM)
    name: str
    value: Any = None


class RawEvent(AGUIBaseEvent):
    """原始事件（透传）"""
    type: AGUIEventType = Field(default=AGUIEventType.RAW)
    event: Dict[str, Any] = Field(default_factory=dict)


# ============ Request Models ============

class AGUIToolDefinition(BaseModel):
    """AG-UI 工具定义"""
    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class AGUIContext(BaseModel):
    """AG-UI 上下文"""
    type: str
    content: Any


class AGUIRequest(BaseModel):
    """AG-UI 请求模型"""
    threadId: str = Field(description="会话ID")
    runId: str = Field(description="本次运行ID")
    messages: List[Dict[str, Any]] = Field(default_factory=list, description="消息列表")
    tools: List[AGUIToolDefinition] = Field(default_factory=list, description="可用工具列表")
    context: List[AGUIContext] = Field(default_factory=list, description="上下文信息")
    forwardedProps: Dict[str, Any] = Field(default_factory=dict, description="转发的属性")
    state: Dict[str, Any] = Field(default_factory=dict, description="状态信息")
    cwd: Optional[str] = Field(default=None, description="Working directory for inplace runs")
    cwd_mode: Optional[str] = Field(default=None, description="CWD mode (e.g. inplace)")
    run_kind: Optional[str] = Field(default=None, description="Run kind hint for legacy bridge")
    cli_session_id: Optional[str] = Field(default=None, description="Underlying CLI session id for precise resume")
    image_paths: List[str] = Field(default_factory=list, description="Local image paths")
    file_paths: List[str] = Field(default_factory=list, description="Local file paths")
    content_parts: List[Dict[str, Any]] = Field(default_factory=list, description="Ordered content parts")

    @staticmethod
    def _normalize_content_parts(content: Any) -> List[Dict[str, Any]]:
        """Normalize AG-UI message content into ordered text/media parts."""
        if isinstance(content, str):
            return [{"type": "text", "content": content}] if content else []

        if not isinstance(content, list):
            return [{"type": "text", "content": str(content)}] if content not in (None, "") else []

        parts: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, str):
                if item:
                    parts.append({"type": "text", "content": item})
                continue
            if not isinstance(item, dict):
                continue

            part_type = str(item.get("type") or "").strip().lower()
            if part_type in ("text", "input_text"):
                text = item.get("text", item.get("content", ""))
                if text:
                    parts.append({"type": "text", "content": str(text)})
                continue

            url = item.get("url")
            if not url and isinstance(item.get("image_url"), dict):
                url = item["image_url"].get("url")
            if not url:
                url = item.get("path")

            mime_type = item.get("mimeType") or item.get("mime_type") or item.get("mediaType")
            file_name = (
                item.get("fileName")
                or item.get("file_name")
                or item.get("filename")
                or item.get("name")
            )
            if part_type in ("binary", "image", "image_url", "input_image") and url:
                media_type = "image" if str(mime_type or "").lower().startswith("image/") or part_type != "binary" else "file"
                normalized = {"type": media_type, "url": str(url)}
                if mime_type:
                    normalized["mime_type"] = str(mime_type)
                if media_type == "file" and file_name:
                    normalized["file_name"] = str(file_name)
                parts.append(normalized)
                continue

            if part_type == "file" and url:
                normalized = {"type": "file", "url": str(url)}
                if mime_type:
                    normalized["mime_type"] = str(mime_type)
                if file_name:
                    normalized["file_name"] = str(file_name)
                parts.append(normalized)

        return parts

    def get_user_content_parts(self) -> List[Dict[str, Any]]:
        """获取最后一条用户消息的有序内容部件。"""
        for msg in reversed(self.messages):
            if msg.get("role") == "user":
                return self._normalize_content_parts(msg.get("content", ""))
        return []
    
    def get_user_content(self) -> str:
        """获取最后一条用户消息内容"""
        text_parts = [
            str(part.get("content", ""))
            for part in self.get_user_content_parts()
            if part.get("type") == "text" and part.get("content")
        ]
        return "\n".join(text_parts)
    
    def get_username(self) -> Optional[str]:
        """从 forwardedProps 获取用户名"""
        return self.forwardedProps.get("username")

    def get_alias(self) -> Optional[str]:
        """从 forwardedProps 获取别名"""
        return self.forwardedProps.get("alias")
    
    def get_response_url(self) -> Optional[str]:
        """从 forwardedProps.rawCallback 获取 response_url"""
        raw_callback = self.forwardedProps.get("rawCallback", {})
        if isinstance(raw_callback, dict):
            return raw_callback.get("response_url")
        return None
    
    def get_msg_id(self) -> Optional[str]:
        """从 forwardedProps.rawCallback 获取 msgid"""
        raw_callback = self.forwardedProps.get("rawCallback", {})
        if isinstance(raw_callback, dict):
            return raw_callback.get("msgid")
        return None
    
    def to_legacy_request(self) -> Dict[str, Any]:
        """转换为 Legacy 请求格式"""
        content_parts = self.get_user_content_parts()
        result = {
            "user": self.get_username(),
            "content": self.get_user_content(),
            "session_id": self.threadId,
            "msg_id": self.get_msg_id() or self.runId,
            "msg_type": "text",
            "response_url": self.get_response_url() or "",
        }
        if content_parts:
            result["content_parts"] = content_parts
        # Include alias from forwardedProps if present
        alias = self.get_alias()
        if alias:
            result["alias"] = alias
        if self.cwd:
            result["cwd"] = self.cwd
        if self.cwd_mode:
            result["cwd_mode"] = self.cwd_mode
        if self.run_kind:
            result["run_kind"] = self.run_kind
        if self.cli_session_id:
            result["cli_session_id"] = self.cli_session_id
        if self.image_paths:
            result["image_paths"] = self.image_paths
        if self.file_paths:
            result["file_paths"] = self.file_paths
        if self.content_parts:
            result["content_parts"] = self.content_parts
        return result


# ============ Event Factory ============

class AGUIEventFactory:
    """AG-UI 事件工厂"""
    
    @staticmethod
    def generate_id() -> str:
        """生成唯一ID"""
        return str(uuid_lib.uuid4())
    
    @classmethod
    def run_started(cls, thread_id: str, run_id: str) -> RunStartedEvent:
        """创建运行开始事件"""
        return RunStartedEvent(threadId=thread_id, runId=run_id)
    
    @classmethod
    def run_finished(cls, thread_id: str, run_id: str) -> RunFinishedEvent:
        """创建运行完成事件"""
        return RunFinishedEvent(threadId=thread_id, runId=run_id)
    
    @classmethod
    def run_error(cls, thread_id: str, run_id: str, message: str, code: Optional[str] = None) -> RunErrorEvent:
        """创建运行错误事件"""
        return RunErrorEvent(threadId=thread_id, runId=run_id, message=message, code=code)
    
    @classmethod
    def text_message_start(cls, message_id: Optional[str] = None, role: MessageRole = MessageRole.ASSISTANT) -> TextMessageStartEvent:
        """创建文本消息开始事件"""
        return TextMessageStartEvent(
            messageId=message_id or cls.generate_id(),
            role=role
        )
    
    @classmethod
    def text_message_content(cls, message_id: str, delta: str) -> TextMessageContentEvent:
        """创建文本消息内容事件"""
        return TextMessageContentEvent(messageId=message_id, delta=delta)
    
    @classmethod
    def text_message_end(cls, message_id: str) -> TextMessageEndEvent:
        """创建文本消息结束事件"""
        return TextMessageEndEvent(messageId=message_id)
    
    @classmethod
    def tool_call_start(cls, tool_call_id: str, tool_name: str, parent_message_id: Optional[str] = None) -> ToolCallStartEvent:
        """创建工具调用开始事件"""
        return ToolCallStartEvent(
            toolCallId=tool_call_id,
            toolCallName=tool_name,
            parentMessageId=parent_message_id
        )
    
    @classmethod
    def tool_call_args(cls, tool_call_id: str, delta: str) -> ToolCallArgsEvent:
        """创建工具调用参数事件"""
        return ToolCallArgsEvent(toolCallId=tool_call_id, delta=delta)
    
    @classmethod
    def tool_call_end(cls, tool_call_id: str, result: Optional[str] = None) -> ToolCallEndEvent:
        """创建工具调用结束事件"""
        return ToolCallEndEvent(toolCallId=tool_call_id, result=result)
    
    @classmethod
    def tool_call_result(cls, message_id: str, tool_call_id: str, content: str) -> ToolCallResultEvent:
        """创建工具调用结果事件"""
        return ToolCallResultEvent(
            messageId=message_id,
            toolCallId=tool_call_id,
            content=content
        )
    
    @classmethod
    def state_snapshot(cls, snapshot: Dict[str, Any]) -> StateSnapshotEvent:
        """创建状态快照事件"""
        return StateSnapshotEvent(snapshot=snapshot)

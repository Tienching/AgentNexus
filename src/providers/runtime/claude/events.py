"""Claude Code stream-json 事件模型定义

基于真实采集的stream-json数据定义事件类型
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class ClaudeEventType(str, Enum):
    """Claude Code 事件类型"""
    SYSTEM = "system"
    ASSISTANT = "assistant"
    USER = "user"
    RESULT = "result"


class SystemSubtype(str, Enum):
    """System事件子类型"""
    INIT = "init"


class ContentBlockType(str, Enum):
    """内容块类型"""
    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"


class DeltaType(str, Enum):
    """增量类型"""
    TEXT_DELTA = "text_delta"
    INPUT_JSON_DELTA = "input_json_delta"


class StreamEventType(str, Enum):
    """Stream事件内部类型"""
    CONTENT_BLOCK_START = "content_block_start"
    CONTENT_BLOCK_DELTA = "content_block_delta"
    CONTENT_BLOCK_STOP = "content_block_stop"
    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_STOP = "message_stop"


# ============ System Event Models ============

class MCPServer(BaseModel):
    """MCP服务器信息"""
    name: str
    status: str


class SystemInitEvent(BaseModel):
    """System init 事件"""
    type: str = Field(default="system")
    subtype: str = Field(default="init")
    cwd: Optional[str] = None
    session_id: str
    tools: List[str] = Field(default_factory=list)
    mcp_servers: List[MCPServer] = Field(default_factory=list)
    model: Optional[str] = None
    permissionMode: Optional[str] = None
    slash_commands: List[str] = Field(default_factory=list)
    apiKeySource: Optional[str] = None
    claude_code_version: Optional[str] = None
    output_style: Optional[str] = None
    agents: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    plugins: List[Dict[str, Any]] = Field(default_factory=list)
    uuid: Optional[str] = None


# ============ Content Block Models ============

class TextContent(BaseModel):
    """文本内容"""
    type: str = Field(default="text")
    text: str


class ToolUseContent(BaseModel):
    """工具使用内容"""
    type: str = Field(default="tool_use")
    id: str
    name: str
    input: Dict[str, Any] = Field(default_factory=dict)


class ToolResultContent(BaseModel):
    """工具结果内容"""
    type: str = Field(default="tool_result")
    tool_use_id: Optional[str] = None
    content: Union[str, List[Dict[str, Any]]] = ""
    is_error: bool = False


ContentItem = Union[TextContent, ToolUseContent, ToolResultContent, Dict[str, Any]]


# ============ Message Models ============

class UsageInfo(BaseModel):
    """Token使用信息"""
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0


class AssistantMessage(BaseModel):
    """Assistant消息体"""
    id: str
    type: str = Field(default="message")
    role: str = Field(default="assistant")
    model: Optional[str] = None
    content: List[ContentItem] = Field(default_factory=list)
    stop_reason: Optional[str] = None
    stop_sequence: Optional[str] = None
    usage: Optional[UsageInfo] = None
    context_management: Optional[Any] = None


class ToolUseResult(BaseModel):
    """工具使用结果"""
    status: Optional[str] = None
    prompt: Optional[str] = None
    agentId: Optional[str] = None
    content: Optional[List[Dict[str, Any]]] = None
    totalDurationMs: Optional[int] = None
    totalTokens: Optional[int] = None
    totalToolUseCount: Optional[int] = None
    usage: Optional[UsageInfo] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    interrupted: Optional[bool] = None
    isImage: Optional[bool] = None
    success: Optional[bool] = None
    commandName: Optional[str] = None


# ============ Event Models ============

class AssistantEvent(BaseModel):
    """Assistant事件"""
    type: str = Field(default="assistant")
    message: AssistantMessage
    parent_tool_use_id: Optional[str] = None
    session_id: str
    uuid: str


class UserMessage(BaseModel):
    """User消息体"""
    role: str = Field(default="user")
    content: Union[str, List[ContentItem]]


class UserEvent(BaseModel):
    """User事件（包含工具结果）"""
    type: str = Field(default="user")
    message: UserMessage
    parent_tool_use_id: Optional[str] = None
    session_id: str
    uuid: str
    tool_use_result: Optional[ToolUseResult] = None


# ============ Stream Event Models ============

class TextDelta(BaseModel):
    """文本增量"""
    type: str = Field(default="text_delta")
    text: str


class InputJsonDelta(BaseModel):
    """JSON输入增量"""
    type: str = Field(default="input_json_delta")
    partial_json: str


class ContentBlockStartBlock(BaseModel):
    """内容块开始的块信息"""
    type: str
    id: Optional[str] = None
    name: Optional[str] = None
    text: Optional[str] = None


class ContentBlockStartEvent(BaseModel):
    """内容块开始事件"""
    type: str = Field(default="content_block_start")
    index: int
    content_block: ContentBlockStartBlock


class ContentBlockDeltaEvent(BaseModel):
    """内容块增量事件"""
    type: str = Field(default="content_block_delta")
    index: int
    delta: Union[TextDelta, InputJsonDelta, Dict[str, Any]]


class ContentBlockStopEvent(BaseModel):
    """内容块结束事件"""
    type: str = Field(default="content_block_stop")
    index: int


class StreamEvent(BaseModel):
    """Stream事件包装"""
    type: str = Field(default="stream_event")
    event: Union[ContentBlockStartEvent, ContentBlockDeltaEvent, ContentBlockStopEvent, Dict[str, Any]]


# ============ Result Event ============

class ResultEvent(BaseModel):
    """结果事件"""
    type: str = Field(default="result")
    result: str
    is_error: bool = False


# ============ Unified Event ============

class ClaudeEvent(BaseModel):
    """统一的Claude事件模型"""
    type: ClaudeEventType
    subtype: Optional[str] = None
    
    # System event fields
    session_id: Optional[str] = None
    tools: Optional[List[str]] = None
    mcp_servers: Optional[List[MCPServer]] = None
    model: Optional[str] = None
    uuid: Optional[str] = None
    
    # Assistant/User event fields
    message: Optional[Union[AssistantMessage, UserMessage, Dict[str, Any]]] = None
    parent_tool_use_id: Optional[str] = None
    tool_use_result: Optional[ToolUseResult] = None
    
    # Stream event fields
    event: Optional[Dict[str, Any]] = None
    
    # Result event fields
    result: Optional[str] = None
    is_error: Optional[bool] = None
    
    class Config:
        extra = "allow"

    @classmethod
    def parse_line(cls, line: str) -> "ClaudeEvent":
        """从JSON行解析事件"""
        import json
        data = json.loads(line)
        return cls(**data)

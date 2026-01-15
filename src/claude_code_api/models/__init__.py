"""数据模型模块"""

# Legacy models (易事厅格式)
from .legacy_models import (
    RequestModel,
    Document,
    GlobalOutput,
    StreamResponse,
    HealthResponse,
    MetricsResponse,
)

# Claude Events
from .claude_events import (
    ClaudeEventType,
    SystemSubtype,
    ContentBlockType,
    DeltaType,
    StreamEventType,
    ClaudeEvent,
    SystemInitEvent,
    AssistantEvent,
    UserEvent,
    StreamEvent,
    ResultEvent,
    AssistantMessage,
    UserMessage,
    TextContent,
    ToolUseContent,
    ToolResultContent,
    UsageInfo,
    ToolUseResult,
)

# AG-UI Events
from .agui_events import (
    AGUIEventType,
    MessageRole,
    AGUIBaseEvent,
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    StateSnapshotEvent,
    StateDeltaEvent,
    MessagesSnapshotEvent,
    CustomEvent,
    RawEvent,
    AGUIRequest,
    AGUIMessage,
    AGUIEventFactory,
)

# Task Models
from .task_models import (
    Task,
    TaskPriority,
    TaskStatus,
    ExecutorConfig,
)

# Session Models (NexusHub)
from .session import (
    SessionStatus,
    SessionMeta,
    MessageStatus,
    StoredMessage,
    ToolCallStatus,
    StoredToolCall,
    SessionListResponse,
    SessionMessagesResponse,
)

__all__ = [
    # Legacy Models
    "RequestModel",
    "Document",
    "GlobalOutput",
    "StreamResponse",
    "HealthResponse",
    "MetricsResponse",
    # Claude Events
    "ClaudeEventType",
    "SystemSubtype", 
    "ContentBlockType",
    "DeltaType",
    "StreamEventType",
    "ClaudeEvent",
    "SystemInitEvent",
    "AssistantEvent",
    "UserEvent",
    "StreamEvent",
    "ResultEvent",
    "AssistantMessage",
    "UserMessage",
    "TextContent",
    "ToolUseContent",
    "ToolResultContent",
    "UsageInfo",
    "ToolUseResult",
    # AG-UI Events
    "AGUIEventType",
    "MessageRole",
    "AGUIBaseEvent",
    "RunStartedEvent",
    "RunFinishedEvent",
    "RunErrorEvent",
    "TextMessageStartEvent",
    "TextMessageContentEvent",
    "TextMessageEndEvent",
    "ToolCallStartEvent",
    "ToolCallArgsEvent",
    "ToolCallEndEvent",
    "StateSnapshotEvent",
    "StateDeltaEvent",
    "MessagesSnapshotEvent",
    "CustomEvent",
    "RawEvent",
    "AGUIRequest",
    "AGUIMessage",
    "AGUIEventFactory",
    # Task Models
    "Task",
    "TaskPriority",
    "TaskStatus",
    "ExecutorConfig",
    # Session Models (NexusHub)
    "SessionStatus",
    "SessionMeta",
    "MessageStatus",
    "StoredMessage",
    "ToolCallStatus",
    "StoredToolCall",
    "SessionListResponse",
    "SessionMessagesResponse",
]

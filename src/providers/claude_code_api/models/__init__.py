# -*- coding: utf-8 -*-
"""数据模型模块

Core event models and data structures used by the API layer.
Session and Task models are re-exported from src.runtime.
"""

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
    ToolCallResultEvent,
    StateSnapshotEvent,
    StateDeltaEvent,
    MessagesSnapshotEvent,
    CustomEvent,
    RawEvent,
    AGUIRequest,
    AGUIMessage,
    AGUIEventFactory,
)

# Task Models (re-export from src.runtime)
from src.runtime.models.task_models import (
    Task,
    TaskPriority,
    TaskStatus,
    ExecutorConfig,
)

# Session Models (re-export from src.runtime)
from src.runtime.models.session import (
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
    "ToolCallResultEvent",
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

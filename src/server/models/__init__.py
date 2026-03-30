# -*- coding: utf-8 -*-
"""Server Models

Re-exports data models from their canonical locations for backward compatibility.
"""

# Legacy request/response models
from .legacy import (
    RequestModel,
    Document,
    GlobalOutput,
    StreamResponse,
    HealthCheck,
    HealthResponse,
    MetricsResponse,
)

# Task Models (from src.runtime)
from src.runtime.models.task_models import (
    Task,
    TaskPriority,
    TaskStatus,
    ExecutorConfig,
)

# Session Models (from src.runtime)
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
    "HealthCheck",
    "HealthResponse",
    "MetricsResponse",
    # Task Models
    "Task",
    "TaskPriority",
    "TaskStatus",
    "ExecutorConfig",
    # Session Models
    "SessionStatus",
    "SessionMeta",
    "MessageStatus",
    "StoredMessage",
    "ToolCallStatus",
    "StoredToolCall",
    "SessionListResponse",
    "SessionMessagesResponse",
]

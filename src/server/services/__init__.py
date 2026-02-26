# -*- coding: utf-8 -*-
"""Server services

Core implementations live in `src.runtime`; this module provides
API-layer adapters and factory functions with the correct Redis/config bindings.
"""

from .cli_executor import CLIExecutor
from .stream_handler import StreamHandler
from .user_directory import UserDirectoryManager
from .callback_handler import CallbackHandler
from .redis_client import RedisClient, get_redis_client
from .session_storage import SessionStorage, get_session_storage
from .stream_archiver import StreamArchiver, create_archiver
from .task_storage import TaskQueue
from src.runtime.commands.slash.worktree import (
    WorktreeError,
    NotGitRepoError,
    WorktreeDirConflictError,
    WorktreeCommandError,
    WorktreeResult,
    ensure_task_worktree,
)

from src.runtime.commands.slash.handler import SlashCommandHandler, SLASH_COMMANDS
from src.runtime.commands.slash.parser import (
    SlashCommandParseError,
    parse_slash_command,
    usage_for,
)
from src.runtime.execution.task_executor import (
    TaskExecutor,
    ExecutorState,
    TaskHandler,
    get_executor,
    set_executor,
    create_and_start_executor,
)
from src.runtime.execution.workspace_queue import WorkspaceQueueManager

# Unified notification system
from .notification import (
    NotificationTarget,
    NotificationResult,
    NotificationSink,
    UnifiedNotificationHandler,
    get_notification_handler,
)

__all__ = [
    "CLIExecutor",
    "StreamHandler",
    "UserDirectoryManager",
    "CallbackHandler",
    "SlashCommandHandler",
    "SLASH_COMMANDS",
    "SlashCommandParseError",
    "parse_slash_command",
    "usage_for",
    "TaskQueue",
    "RedisClient",
    "get_redis_client",
    "WorkspaceQueueManager",

    "TaskExecutor",
    "ExecutorState",
    "TaskHandler",
    "get_executor",
    "set_executor",
    "create_and_start_executor",
    "SessionStorage",
    "get_session_storage",
    "StreamArchiver",
    "create_archiver",
    "WorktreeError",
    "NotGitRepoError",
    "WorktreeDirConflictError",
    "WorktreeCommandError",
    "WorktreeResult",
    "ensure_task_worktree",

    # Unified notification system
    "NotificationTarget",
    "NotificationResult",
    "NotificationSink",
    "UnifiedNotificationHandler",
    "get_notification_handler",
]

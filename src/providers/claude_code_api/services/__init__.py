# -*- coding: utf-8 -*-
"""服务层模块 (lazy re-export from src.server)

避免在包初始化阶段引入 `src.server.services`，以规避循环依赖。
"""

from __future__ import annotations

import importlib
from typing import Any, List


_EXPORTS = [
    "CCRExecutor",
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
    "WorkspaceState",
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
]

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        mod = importlib.import_module("src.server.services")
        return getattr(mod, name)
    raise AttributeError(f"module 'src.providers.claude_code_api.services' has no attribute {name!r}")


def __dir__() -> List[str]:
    return sorted(list(globals().keys()) + _EXPORTS)

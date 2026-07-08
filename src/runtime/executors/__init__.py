# -*- coding: utf-8 -*-
"""
CLI Executors - unified abstraction for subprocess CLI execution.

This module provides the base interfaces and implementations for
executing CLI tools (Claude, Codex, CodeBuddy) as subprocesses.
"""

from .base import BaseExecutor, ExecutorConfig, RequestContext
from .cli_executor import CLIExecutor, CLIExecutorConfig

__all__ = [
    "BaseExecutor",
    "ExecutorConfig",
    "RequestContext",
    "CLIExecutor",
    "CLIExecutorConfig",
]

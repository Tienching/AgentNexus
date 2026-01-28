# -*- coding: utf-8 -*-
"""
CLI Executors - unified abstraction for subprocess CLI execution.

This module provides the base interfaces and implementations for
executing CLI tools (CCR, Gemini CLI) as subprocesses.
"""

from .base import BaseExecutor, ExecutorConfig, RequestContext
from .ccr_executor import CCRExecutor
from .gemini_executor import GeminiExecutor

__all__ = [
    "BaseExecutor",
    "ExecutorConfig",
    "RequestContext",
    "CCRExecutor",
    "GeminiExecutor",
]

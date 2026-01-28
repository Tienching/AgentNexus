# -*- coding: utf-8 -*-
"""AI Backend Providers

This module contains provider implementations for different AI backends.
Each provider includes:
- executor.py: CLI subprocess execution
- adapter.py: Event transformation to unified format
"""

from .base import BaseExecutor, ExecutorConfig, RequestContext

__all__ = [
    # Base
    "BaseExecutor",
    "ExecutorConfig",
    "RequestContext",
    # Submodules
    "claude",
    "gemini",
    "channels",
    # Legacy (for backward compatibility)
    "runtime",
    "claude_code_api",
    "gemini_cli_api",
]

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
    # Submodules (actual implementations)
    "claude",
    # Provider registry
    "runtime",
]

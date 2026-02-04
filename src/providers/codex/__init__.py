# -*- coding: utf-8 -*-
"""Codex Provider

Codex CLI integration.
- CodexCLIExecutor: Uses `codex exec --json` non-interactive mode (recommended)
- CodexExecutor: Uses MCP JSON-RPC protocol (legacy, not integrated)
"""

from .cli_executor import CodexCLIExecutor, CodexCLIExecutorConfig
from .executor import CodexExecutor, CodexExecutorConfig
from .connection import CodexConnection

__all__ = [
    # Recommended CLI executor
    "CodexCLIExecutor",
    "CodexCLIExecutorConfig",
    # Legacy MCP executor
    "CodexExecutor",
    "CodexExecutorConfig",
    "CodexConnection",
]

# -*- coding: utf-8 -*-
"""Centralized provider dispatch — single source of truth for
executor and adapter creation.

Replaces 4 duplicate if/elif dispatch chains in stream_handler.py
and app.py.  New providers only need to register here.
"""

from __future__ import annotations

from typing import Optional


def normalize_provider(name: Optional[str]) -> str:
    """Normalize a provider name to its canonical key.

    Unknown / empty values fall back to ``"claude"``.
    """
    n = (name or "").strip().lower()
    if n in ("gemini", "codex", "codebuddy"):
        return n
    return "claude"


# ---------------------------------------------------------------------------
# Executor factories
# ---------------------------------------------------------------------------
# Imports are deferred inside each factory to avoid circular-import issues
# (providers may import from server.config which may transitively touch app).

def create_executor(provider: str, *, config=None):
    """Create a **new** executor instance for *provider*.

    Args:
        provider: Raw provider name (will be normalized).
        config:   Optional settings object; defaults to ``settings``.
    """
    if config is None:
        from src.server.config import settings as _settings
        config = _settings

    key = normalize_provider(provider)

    if key == "gemini":
        from src.providers.gemini import GeminiExecutor
        return GeminiExecutor(config=config)

    if key == "codex":
        from src.providers.codex import CodexCLIExecutor
        return CodexCLIExecutor(config=config)

    if key == "codebuddy":
        from src.providers.codebuddy import CodebuddyCLIExecutor
        return CodebuddyCLIExecutor(config=config)

    # Default: Claude
    from src.server.services.cli_executor import CLIExecutor
    return CLIExecutor(config=config)


def create_all_executors(*, config=None) -> dict:
    """Pre-create one executor per known provider.

    Used by ``StreamHandler.__init__`` which keeps long-lived instances.
    """
    if config is None:
        from src.server.config import settings as _settings
        config = _settings

    return {
        "claude":    create_executor("claude", config=config),
        "gemini":    create_executor("gemini", config=config),
        "codex":     create_executor("codex", config=config),
        "codebuddy": create_executor("codebuddy", config=config),
    }


# ---------------------------------------------------------------------------
# Adapter factories
# ---------------------------------------------------------------------------

def create_adapter(provider: str):
    """Create a **new** AG-UI adapter instance for *provider*."""
    key = normalize_provider(provider)

    if key == "gemini":
        from src.runtime.adapters.gemini import GeminiAGUIAdapter
        return GeminiAGUIAdapter()

    if key == "codex":
        from src.runtime.adapters.codex import CodexCLIAGUIAdapter
        return CodexCLIAGUIAdapter()

    if key == "codebuddy":
        from src.runtime.adapters.codebuddy import CodebuddyAGUIAdapter
        return CodebuddyAGUIAdapter()

    # Default: Claude
    from src.runtime.adapters.claude import AGUIAdapter
    return AGUIAdapter()

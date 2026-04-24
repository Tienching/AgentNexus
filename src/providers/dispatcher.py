# -*- coding: utf-8 -*-
"""Centralized provider dispatch — single source of truth for
executor and adapter creation.

Replaces 4 duplicate if/elif dispatch chains in stream_handler.py
and app.py.  New providers only need to register here.
"""

from __future__ import annotations

from typing import Optional


class ProviderExecutorMap(dict):
    """Dictionary-like executor registry with legacy provider aliases."""

    _ALIASES = {"nanobot": "nexus"}

    def _resolve_key(self, key):
        if isinstance(key, str):
            return self._ALIASES.get(key, key)
        return key

    def __getitem__(self, key):
        return super().__getitem__(self._resolve_key(key))

    def get(self, key, default=None):
        return super().get(self._resolve_key(key), default)

    def __contains__(self, key):
        return super().__contains__(self._resolve_key(key))


def normalize_provider(name: Optional[str]) -> str:
    """Normalize a provider name to its canonical key.

    Unknown / empty values fall back to the default provider.
    """
    n = (name or "").strip().lower()
    if n in ("gemini", "codex", "codebuddy", "claude", "nexus", "nanobot"):
        if n == "nanobot":
            return "nexus"
        return n
    return _default_provider()


def _default_provider() -> str:
    """Return the default provider key (configurable via env var)."""
    import os
    default = os.environ.get("AGENT_NEXUS_DEFAULT_PROVIDER", "nexus").strip().lower()
    return "nexus" if default == "nanobot" else default


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

    if key == "nexus":
        from src.providers.nexus import NexusExecutor
        return NexusExecutor(config=config)

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

    nexus_executor = create_executor("nexus", config=config)
    executors = ProviderExecutorMap({
        "claude":    create_executor("claude", config=config),
        "gemini":    create_executor("gemini", config=config),
        "codex":     create_executor("codex", config=config),
        "codebuddy": create_executor("codebuddy", config=config),
        "nexus":     nexus_executor,
        "nanobot":   nexus_executor,
    })
    return executors


# ---------------------------------------------------------------------------
# Adapter factories
# ---------------------------------------------------------------------------

def create_adapter(provider: str):
    """Create a **new** AG-UI adapter instance for *provider*."""
    key = normalize_provider(provider)

    if key == "nexus":
        from src.providers.nexus import NexusAGUIAdapter
        return NexusAGUIAdapter()

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

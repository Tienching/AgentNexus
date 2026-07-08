# -*- coding: utf-8 -*-
"""Centralized provider dispatch — single source of truth for
executor and adapter creation.

Replaces 4 duplicate if/elif dispatch chains in stream_handler.py
and app.py.  New providers only need to register here.
"""

from __future__ import annotations

from typing import Optional


def normalize_provider(name: Optional[str]) -> str:
    """Normalize a provider name or custom alias to a supported provider key."""
    n = (name or "").strip().lower()
    if not n:
        return _default_provider()

    if n == "nanobot":
        return "nexus"
    if n in ("claude", "codex", "codebuddy", "hermes", "nexus"):
        return n

    try:
        from src.runtime.stores.alias_registry import AliasRegistry

        builtin = AliasRegistry.BUILTIN.get(n)
        if builtin in ("claude", "codex", "codebuddy", "hermes", "nexus"):
            return builtin
        try:
            registry = AliasRegistry()
            resolved = registry.resolve(n)
            if resolved in ("claude", "codex", "codebuddy", "hermes", "nexus"):
                return resolved
        except Exception:
            pass
    except Exception:
        pass

    for canonical in ("claude", "codex", "codebuddy", "hermes", "nexus"):
        if n == canonical or n.startswith(canonical + "-"):
            return canonical

    return _default_provider()


def _default_provider() -> str:
    """Return the default provider key (configurable via env var)."""
    import os

    default = os.environ.get("AGENT_NEXUS_DEFAULT_PROVIDER", "claude").strip().lower()
    return default if default in {"claude", "codex", "codebuddy", "hermes", "nexus"} else "claude"


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

    if key == "codex":
        from src.providers.codex import CodexCLIExecutor
        return CodexCLIExecutor(config=config)

    if key == "codebuddy":
        from src.providers.codebuddy import CodebuddyCLIExecutor
        return CodebuddyCLIExecutor(config=config)

    if key == "hermes":
        from src.providers.hermes.acp_executor import HermesACPExecutor
        return HermesACPExecutor(config=config)

    if key == "nexus":
        from src.providers.nexus import NexusExecutor
        return NexusExecutor(config=config)

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
        "claude": create_executor("claude", config=config),
        "codex": create_executor("codex", config=config),
        "codebuddy": create_executor("codebuddy", config=config),
        "hermes": create_executor("hermes", config=config),
        "nexus": create_executor("nexus", config=config),
    }


# ---------------------------------------------------------------------------
# Adapter factories
# ---------------------------------------------------------------------------

def create_adapter(provider: str):
    """Create a **new** AG-UI adapter instance for *provider*."""
    key = normalize_provider(provider)

    if key == "codex":
        from src.runtime.adapters.codex import CodexCLIAGUIAdapter
        return CodexCLIAGUIAdapter()

    if key == "codebuddy":
        from src.runtime.adapters.codebuddy import CodebuddyAGUIAdapter
        return CodebuddyAGUIAdapter()

    if key == "hermes":
        from src.runtime.adapters.hermes import HermesACPAGUIAdapter
        return HermesACPAGUIAdapter()

    if key == "nexus":
        from src.runtime.adapters.nexus import NexusAGUIAdapter
        return NexusAGUIAdapter()

    # Default: Claude
    from src.runtime.adapters.claude import AGUIAdapter
    return AGUIAdapter()

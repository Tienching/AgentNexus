# -*- coding: utf-8 -*-
"""Centralized provider dispatch — single source of truth for
executor and adapter creation.

Replaces 4 duplicate if/elif dispatch chains in stream_handler.py
and app.py.  New providers only need to register here.
"""

from __future__ import annotations

from typing import Optional


class ProviderExecutorMap(dict):
    """Dictionary-like executor registry (canonical provider keys only)."""


def normalize_provider(name: Optional[str]) -> str:
    """Normalize a provider name (or alias) to its canonical key.

    Accepts:
    - canonical provider names (``claude``/``codex``/``gemini``/``codebuddy``)
    - aliases registered via :class:`AliasRegistry` (e.g. ``claude-internal``
      -> ``claude``, ``codex-internal`` -> ``codex``)

    Unknown / empty values fall back to the default provider.
    """
    n = (name or "").strip().lower()
    if not n:
        return _default_provider()

    # Canonical provider names
    if n in ("gemini", "codex", "codebuddy", "claude", "hermes", "openclaw"):
        return n

    # Alias lookup — consult the global alias registry so that UI selections
    # like ``claude-internal`` correctly resolve to ``claude`` instead of
    # silently falling through to the default provider.
    try:
        from src.runtime.stores.alias_registry import AliasRegistry

        builtin = AliasRegistry.BUILTIN.get(n)
        if builtin:
            return builtin
        # Fall back to the DB-backed registry for user-registered aliases.
        # Wrapped in try/except because the DB may not be initialised in
        # some CLI/test contexts where this function is still called.
        try:
            registry = AliasRegistry()
            resolved = registry.resolve(n)
            if resolved:
                return resolved
        except Exception:
            pass
    except Exception:
        pass

    # Heuristic fallback: ``<provider>-<suffix>`` where <provider> is a known
    # canonical name (e.g. a user-defined ``claude-work`` without an explicit
    # registry entry). This mirrors the behaviour in
    # ``cli_executor._PROVIDER_COMMAND_MAP`` / ``AliasRegistry.BUILTIN``.
    for canonical in ("claude", "codex", "gemini", "codebuddy", "hermes", "openclaw"):
        if n == canonical or n.startswith(canonical + "-"):
            return canonical

    return _default_provider()


def _default_provider() -> str:
    """Return the default provider key (configurable via env var).

    Defaults to providers.registry.DEFAULT_PROVIDER (claude).
    """
    import os
    from src.providers.registry import DEFAULT_PROVIDER
    return os.environ.get("AGENT_NEXUS_DEFAULT_PROVIDER", DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER


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

    if key == "hermes":
        from src.providers.hermes import HermesCLIExecutor
        return HermesCLIExecutor(config=config)

    if key == "openclaw":
        from src.providers.openclaw import OpenClawCLIExecutor
        return OpenClawCLIExecutor(config=config)

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

    return ProviderExecutorMap({
        "claude":    create_executor("claude", config=config),
        "gemini":    create_executor("gemini", config=config),
        "codex":     create_executor("codex", config=config),
        "codebuddy": create_executor("codebuddy", config=config),
        "hermes":    create_executor("hermes", config=config),
        "openclaw":  create_executor("openclaw", config=config),
    })


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

    if key == "hermes":
        from src.runtime.adapters.hermes import HermesAGUIAdapter
        return HermesAGUIAdapter()

    if key == "openclaw":
        from src.runtime.adapters.openclaw import OpenClawAGUIAdapter
        return OpenClawAGUIAdapter()

    # Default: Claude
    from src.runtime.adapters.claude import AGUIAdapter
    return AGUIAdapter()

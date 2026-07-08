# -*- coding: utf-8 -*-
"""Agent Registry service — singleton wrapper for AgentLifecycle registry."""

from src.core.agent_runtime.agent.lifecycle import AgentRegistry

_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    """Get the global AgentRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry

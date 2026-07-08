# -*- coding: utf-8 -*-
"""Framework adapters: OpenClaw, CrewAI, LangGraph, AutoGen, Claude SDK."""

from src.core.agent_runtime.adapters.base import AdapterRequest, AdapterResponse, AgentFrameworkAdapter
from src.core.agent_runtime.adapters.registry import AdapterRegistry, get_adapter_registry
from src.core.agent_runtime.adapters.openclaw import OpenClawAdapter
from src.core.agent_runtime.adapters.crewai import CrewAIAdapter
from src.core.agent_runtime.adapters.langgraph import LangGraphAdapter
from src.core.agent_runtime.adapters.autogen import AutoGenAdapter
from src.core.agent_runtime.adapters.claude_sdk import ClaudeSDKAdapter


def register_builtin_adapters(registry: AdapterRegistry | None = None) -> AdapterRegistry:
    reg = registry or get_adapter_registry()
    reg.register(OpenClawAdapter())
    reg.register(CrewAIAdapter())
    reg.register(LangGraphAdapter())
    reg.register(AutoGenAdapter())
    reg.register(ClaudeSDKAdapter())
    return reg


__all__ = [
    "AdapterRequest",
    "AdapterResponse",
    "AgentFrameworkAdapter",
    "AdapterRegistry",
    "get_adapter_registry",
    "register_builtin_adapters",
    "OpenClawAdapter",
    "CrewAIAdapter",
    "LangGraphAdapter",
    "AutoGenAdapter",
    "ClaudeSDKAdapter",
]

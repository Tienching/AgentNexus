# -*- coding: utf-8 -*-
"""Framework adapters: OpenClaw, CrewAI, LangGraph, AutoGen, Claude SDK."""

from src.nanobot.adapters.base import AdapterRequest, AdapterResponse, AgentFrameworkAdapter
from src.nanobot.adapters.registry import AdapterRegistry, get_adapter_registry
from src.nanobot.adapters.openclaw import OpenClawAdapter
from src.nanobot.adapters.crewai import CrewAIAdapter
from src.nanobot.adapters.langgraph import LangGraphAdapter
from src.nanobot.adapters.autogen import AutoGenAdapter
from src.nanobot.adapters.claude_sdk import ClaudeSDKAdapter


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

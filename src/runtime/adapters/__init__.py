# -*- coding: utf-8 -*-
"""Adapters layer - convert provider events to protocol formats"""

from .base import BaseAdapter, AdapterState, ProtocolType
from .claude import AGUIAdapter, ParsedToolCall
from .codex import CodexAGUIAdapter
from .codebuddy import CodebuddyAGUIAdapter
from .nexus import NexusAGUIAdapter, NanobotAGUIAdapter

__all__ = [
    # Base
    "BaseAdapter",
    "AdapterState",
    "ProtocolType",
    # Claude adapters
    "AGUIAdapter",
    "ParsedToolCall",
    # Codex adapters
    "CodexAGUIAdapter",
    # Codebuddy adapters
    "CodebuddyAGUIAdapter",
    # Nexus / legacy Nanobot adapters
    "NexusAGUIAdapter",
    "NanobotAGUIAdapter",
]

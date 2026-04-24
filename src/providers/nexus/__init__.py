# -*- coding: utf-8 -*-
"""Nexus provider package for agent-nexus.

Exposes the in-process executor and AG-UI adapter that allow Nexus to serve
as a chat provider alongside Claude, Gemini, etc. Legacy nanobot aliases are
kept for compatibility.
"""

from src.providers.nexus.adapter import NexusAGUIAdapter, NanobotAGUIAdapter
from src.providers.nexus.executor import NexusExecutor, NanobotExecutor

__all__ = [
    "NexusExecutor",
    "NanobotExecutor",
    "NexusAGUIAdapter",
    "NanobotAGUIAdapter",
]

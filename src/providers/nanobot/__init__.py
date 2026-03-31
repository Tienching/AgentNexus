# -*- coding: utf-8 -*-
"""Nanobot provider package for agent-nexus.

Exposes the in-process executor and AG-UI adapter that allow nanobot's
AgentLoop to serve as a chat provider alongside Claude, Gemini, etc.
"""

from src.providers.nanobot.adapter import NanobotAGUIAdapter
from src.providers.nanobot.executor import NanobotExecutor

__all__ = ["NanobotExecutor", "NanobotAGUIAdapter"]

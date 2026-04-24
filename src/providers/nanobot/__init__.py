# -*- coding: utf-8 -*-
"""Legacy nanobot provider package.

This module now re-exports the canonical nexus provider implementation.
"""

from src.providers.nexus import NexusAGUIAdapter, NexusExecutor

NanobotAGUIAdapter = NexusAGUIAdapter
NanobotExecutor = NexusExecutor

__all__ = ["NexusExecutor", "NexusAGUIAdapter", "NanobotExecutor", "NanobotAGUIAdapter"]

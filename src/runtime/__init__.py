# -*- coding: utf-8 -*-
"""
Agent Runtime Core Package

Single source of truth for:
  - src.runtime.events      — event types (base + AG-UI protocol)
  - src.runtime.models       — session / task data models
  - src.runtime.stores       — Redis client, session & task storage
  - src.runtime.streaming    — SSE stream orchestrator
  - src.runtime.adapters     — AG-UI protocol adapters (Claude/Gemini/Codex/Codebuddy)
  - src.runtime.execution    — task executor, workspace queue
  - src.runtime.commands     — slash commands
  - src.runtime.archiving    — stream archiver
"""

from .events import Event, EventType, TokenEvent, ToolCallStartEvent, ErrorEvent

__version__ = "0.1.0"

__all__ = [
    "Event",
    "EventType", 
    "TokenEvent",
    "ToolCallStartEvent",
    "ErrorEvent",
]

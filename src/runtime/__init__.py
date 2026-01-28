# -*- coding: utf-8 -*-
"""
Agent Runtime Core Package (Legacy alias)

This module is now an alias to src.core for backward compatibility.
New code should import from src.core directly.

Migration path:
  - src.runtime.events -> src.core.events
  - src.runtime.models -> src.core.models
  - src.runtime.stores -> src.core.stores
  - src.runtime.streaming -> src.core.streaming
  - src.runtime.adapters -> src.protocols
  - src.runtime.executors -> src.providers.{claude,gemini}.executor
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

# -*- coding: utf-8 -*-
"""Internal event schema for the Nexus provider.

These dataclasses are the bridge between NexusExecutor (producer) and
NexusAGUIAdapter (consumer). They flow through an asyncio.Queue.
Legacy nanobot aliases are kept for compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(slots=True)
class TextStartEvent:
    """The model started producing a new text message."""
    message_id: str
    type: str = field(default="text_start", init=False)


@dataclass(slots=True)
class TextDeltaEvent:
    """Incremental text token from the model."""
    message_id: str
    delta: str
    type: str = field(default="text_delta", init=False)


@dataclass(slots=True)
class TextEndEvent:
    """The model finished the current text message."""
    message_id: str
    type: str = field(default="text_end", init=False)


@dataclass(slots=True)
class ToolStartEvent:
    """A tool call has been initiated."""
    tool_call_id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    type: str = field(default="tool_start", init=False)


@dataclass(slots=True)
class ToolResultEvent:
    """A tool call has returned its result."""
    tool_call_id: str
    content: str
    type: str = field(default="tool_result", init=False)


@dataclass(slots=True)
class ToolEndEvent:
    """Clean-up signal after ToolResultEvent has been sent."""
    tool_call_id: str
    type: str = field(default="tool_end", init=False)


@dataclass(slots=True)
class ThinkingEvent:
    """Model reasoning / chain-of-thought (may be suppressed)."""
    content: str
    type: str = field(default="thinking", init=False)


@dataclass(slots=True)
class DoneEvent:
    """Sentinel: the AgentLoop turn has completed."""
    type: str = field(default="done", init=False)


@dataclass(slots=True)
class ErrorEvent:
    """An error occurred during processing."""
    message: str
    type: str = field(default="error", init=False)


NexusEvent = (
    TextStartEvent
    | TextDeltaEvent
    | TextEndEvent
    | ToolStartEvent
    | ToolResultEvent
    | ToolEndEvent
    | ThinkingEvent
    | DoneEvent
    | ErrorEvent
)

NanobotEvent = NexusEvent

__all__ = [
    "TextStartEvent",
    "TextDeltaEvent",
    "TextEndEvent",
    "ToolStartEvent",
    "ToolResultEvent",
    "ToolEndEvent",
    "ThinkingEvent",
    "DoneEvent",
    "ErrorEvent",
    "NexusEvent",
    "NanobotEvent",
]

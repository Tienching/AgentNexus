# -*- coding: utf-8 -*-
"""Adapters layer - convert provider events to protocol formats"""

from .base import BaseAdapter, AdapterState, ProtocolType
from .claude import AGUIAdapter, ParsedToolCall
from .gemini import GeminiAGUIAdapter
from .codex import CodexAGUIAdapter

__all__ = [
    # Base
    "BaseAdapter",
    "AdapterState",
    "ProtocolType",
    # Claude adapters
    "AGUIAdapter",
    "ParsedToolCall",
    # Gemini adapters
    "GeminiAGUIAdapter",
    # Codex adapters
    "CodexAGUIAdapter",
]

# -*- coding: utf-8 -*-
"""Adapters layer - convert provider events to protocol formats"""

from .base import BaseAdapter, AdapterState, ProtocolType
from .claude import AGUIAdapter, LegacyAdapter, ParsedToolCall
from .gemini import GeminiAGUIAdapter, GeminiLegacyAdapter

__all__ = [
    # Base
    "BaseAdapter",
    "AdapterState",
    "ProtocolType",
    # Claude adapters
    "AGUIAdapter",
    "LegacyAdapter",
    "ParsedToolCall",
    # Gemini adapters
    "GeminiAGUIAdapter",
    "GeminiLegacyAdapter",
]

# -*- coding: utf-8 -*-
"""Gemini CLI adapters"""

from .agui_adapter import GeminiAGUIAdapter
from .legacy_adapter import GeminiLegacyAdapter

__all__ = [
    "GeminiAGUIAdapter",
    "GeminiLegacyAdapter",
]

# -*- coding: utf-8 -*-
"""Gemini CLI API package

Adapters are now in src.runtime.adapters.gemini, re-exported here for compatibility.
"""

from .services.gemini_executor import GeminiExecutor
from src.runtime.adapters.gemini import GeminiAGUIAdapter, GeminiLegacyAdapter

__all__ = [
    "GeminiExecutor",
    "GeminiAGUIAdapter",
    "GeminiLegacyAdapter",
]

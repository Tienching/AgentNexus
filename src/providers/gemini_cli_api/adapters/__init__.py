# -*- coding: utf-8 -*-
"""Gemini CLI adapters - re-exports from src.runtime

New code should prefer importing from src.runtime.adapters.gemini
"""

from src.runtime.adapters.gemini import GeminiAGUIAdapter, GeminiLegacyAdapter

__all__ = [
    "GeminiAGUIAdapter",
    "GeminiLegacyAdapter",
]

# -*- coding: utf-8 -*-
"""Gemini Provider

Implements Gemini CLI execution and event transformation.
"""

from .executor import GeminiExecutor
from .adapter import GeminiAGUIAdapter

__all__ = [
    "GeminiExecutor",
    "GeminiAGUIAdapter",
]

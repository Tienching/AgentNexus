# -*- coding: utf-8 -*-
"""Claude Provider

Implements Claude Code (CCR) CLI execution and event transformation.
"""

from .executor import CCRExecutor
from .adapter import AGUIAdapter

__all__ = [
    "CCRExecutor",
    "AGUIAdapter",
]

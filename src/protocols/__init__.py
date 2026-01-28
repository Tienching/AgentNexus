# -*- coding: utf-8 -*-
"""Output protocol adapters

Convert unified events to various output formats (AG-UI SSE, Legacy SSE, etc.)
"""

from .base import BaseAdapter, AdapterState, ProtocolType
from .agui import AGUIAdapter
from .legacy import LegacyAdapter

__all__ = [
    "BaseAdapter",
    "AdapterState",
    "ProtocolType",
    "AGUIAdapter",
    "LegacyAdapter",
]

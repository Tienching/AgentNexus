# -*- coding: utf-8 -*-
"""Output protocol adapters

Convert unified events to AG-UI SSE format.
"""

from .base import BaseAdapter, AdapterState, ProtocolType
from .agui import AGUIAdapter

__all__ = [
    "BaseAdapter",
    "AdapterState",
    "ProtocolType",
    "AGUIAdapter",
]

# -*- coding: utf-8 -*-
"""Adapters — protocol detection helpers for the HTTP layer."""

# Re-export core adapter types from src.runtime
from src.runtime.adapters import (
    BaseAdapter,
    AdapterState,
    ProtocolType,
    AGUIAdapter,
    ParsedToolCall,
)

# Protocol detection utilities
from .protocol_router import (
    detect_protocol,
    detect_protocol_from_body,
)

__all__ = [
    # Core adapter types
    "BaseAdapter",
    "AdapterState",
    "ProtocolType",
    "AGUIAdapter",
    "ParsedToolCall",
    # Protocol detection
    "detect_protocol",
    "detect_protocol_from_body",
]

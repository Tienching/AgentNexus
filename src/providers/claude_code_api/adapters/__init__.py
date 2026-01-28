"""Adapters - re-exports from src.runtime"""

# Re-export from src.runtime
from src.runtime.adapters import (
    BaseAdapter,
    AdapterState,
    ProtocolType,
    AGUIAdapter,
    LegacyAdapter,
    ParsedToolCall,
)
from .protocol_router import (
    ProtocolRouter,
    get_router,
    reset_router,
    detect_protocol,
    detect_protocol_from_body,
)

__all__ = [
    # From src.runtime
    "BaseAdapter",
    "AdapterState",
    "ProtocolType",
    "AGUIAdapter",
    "LegacyAdapter",
    "ParsedToolCall",
    # Local
    "ProtocolRouter",
    "get_router",
    "reset_router",
    "detect_protocol",
    "detect_protocol_from_body",
]

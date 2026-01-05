"""协议适配器模块"""

from .base_adapter import BaseAdapter, ProtocolType
from .agui_adapter import AGUIAdapter
from .legacy_adapter import LegacyAdapter
from .protocol_router import ProtocolRouter, detect_protocol, detect_protocol_from_body, get_router

__all__ = [
    "BaseAdapter",
    "ProtocolType",
    "AGUIAdapter",
    "LegacyAdapter",
    "ProtocolRouter",
    "detect_protocol",
    "detect_protocol_from_body",
    "get_router",
]

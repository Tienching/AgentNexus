# -*- coding: utf-8 -*-
"""
Protocol 层

将统一事件转换为各种输出协议格式（AGUI/企微）。
"""

from .base import Protocol, ProtocolType
from .agui import AGUIProtocol
from .wecom import WeComProtocol

__all__ = [
    "Protocol",
    "ProtocolType",
    "AGUIProtocol",
    "WeComProtocol",
]

# -*- coding: utf-8 -*-
"""
Protocol 基础接口
"""

from enum import Enum
from typing import Protocol as TypingProtocol, Optional, Any
from dataclasses import dataclass

from ..events import Event


class ProtocolType(Enum):
    """协议类型"""
    AGUI = "agui"
    WECOM = "wecom"  # 企微协议（原 legacy）
    RAW = "raw"


@dataclass
class ProtocolState:
    """协议状态"""
    thread_id: str
    run_id: str
    message_id: Optional[str] = None


class Protocol(TypingProtocol):
    """Protocol 接口 - 将统一事件转换为特定协议格式"""
    
    @property
    def protocol_type(self) -> ProtocolType:
        """协议类型"""
        ...
    
    def init_state(self, thread_id: str, run_id: str) -> None:
        """初始化状态"""
        ...
    
    def convert(self, event: Event) -> Optional[str]:
        """将统一事件转换为协议格式字符串"""
        ...
    
    def finalize(self) -> Optional[str]:
        """结束转换，返回可能的结束事件"""
        ...

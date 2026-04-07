# -*- coding: utf-8 -*-
"""
事件基类
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import time


class EventType(Enum):
    """事件类型枚举"""
    TOKEN = "token"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    TOOL_RESULT = "tool_result"
    MESSAGE_START = "message_start"
    MESSAGE_END = "message_end"
    ERROR = "error"
    SYSTEM = "system"


@dataclass
class Event:
    """统一事件基类"""
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    provider: str = ""
    session_id: Optional[str] = None
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp,
            "provider": self.provider,
            "session_id": self.session_id,
        }
    
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Event":
        """从字典创建"""
        return cls(
            type=EventType(d["type"]),
            data=d.get("data", {}),
            timestamp=d.get("timestamp", time.time()),
            provider=d.get("provider", ""),
            session_id=d.get("session_id"),
        )

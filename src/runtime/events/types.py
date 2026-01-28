# -*- coding: utf-8 -*-
"""
具体事件类型
"""

from dataclasses import dataclass, field
from typing import Any, Optional
import time

from .base import Event, EventType


@dataclass
class TokenEvent(Event):
    """文本 token 事件"""
    type: EventType = field(default=EventType.TOKEN, init=False)
    text: str = ""
    
    def __post_init__(self):
        self.data["text"] = self.text


@dataclass
class ToolCallStartEvent(Event):
    """工具调用开始事件"""
    type: EventType = field(default=EventType.TOOL_CALL_START, init=False)
    tool_name: str = ""
    tool_id: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        self.data.update({
            "tool_name": self.tool_name,
            "tool_id": self.tool_id,
            "arguments": self.arguments,
        })


@dataclass
class ToolCallEndEvent(Event):
    """工具调用结束事件"""
    type: EventType = field(default=EventType.TOOL_CALL_END, init=False)
    tool_id: str = ""
    
    def __post_init__(self):
        self.data["tool_id"] = self.tool_id


@dataclass
class ToolResultEvent(Event):
    """工具执行结果事件"""
    type: EventType = field(default=EventType.TOOL_RESULT, init=False)
    tool_id: str = ""
    result: Any = None
    success: bool = True
    
    def __post_init__(self):
        self.data.update({
            "tool_id": self.tool_id,
            "result": self.result,
            "success": self.success,
        })


@dataclass
class MessageStartEvent(Event):
    """消息开始事件"""
    type: EventType = field(default=EventType.MESSAGE_START, init=False)
    message_id: str = ""
    role: str = "assistant"
    
    def __post_init__(self):
        self.data.update({
            "message_id": self.message_id,
            "role": self.role,
        })


@dataclass
class MessageEndEvent(Event):
    """消息结束事件"""
    type: EventType = field(default=EventType.MESSAGE_END, init=False)
    message_id: str = ""
    stop_reason: str = ""
    
    def __post_init__(self):
        self.data.update({
            "message_id": self.message_id,
            "stop_reason": self.stop_reason,
        })


@dataclass
class ErrorEvent(Event):
    """错误事件"""
    type: EventType = field(default=EventType.ERROR, init=False)
    code: str = ""
    message: str = ""
    recoverable: bool = True
    
    def __post_init__(self):
        self.data.update({
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
        })


@dataclass
class SystemEvent(Event):
    """系统事件"""
    type: EventType = field(default=EventType.SYSTEM, init=False)
    action: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        self.data.update({
            "action": self.action,
            "details": self.details,
        })

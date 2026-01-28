# -*- coding: utf-8 -*-
"""
Channel 基础接口
"""

from dataclasses import dataclass, field
from typing import Protocol, AsyncIterator, Optional, Any, List
from enum import Enum


class MessageFormat(Enum):
    """消息格式"""
    TEXT = "text"
    MARKDOWN = "markdown"
    RICH = "rich"


@dataclass
class InboundMessage:
    """入站消息"""
    channel: str
    peer_id: str  # 用户/发送者 ID
    content: str
    message_id: str = ""
    group_id: Optional[str] = None  # 群组 ID（如果是群消息）
    thread_id: Optional[str] = None  # 线程 ID（如果在线程中）
    attachments: List[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "peer_id": self.peer_id,
            "content": self.content,
            "message_id": self.message_id,
            "group_id": self.group_id,
            "thread_id": self.thread_id,
            "attachments": self.attachments,
            "metadata": self.metadata,
        }


@dataclass
class OutboundMessage:
    """出站消息"""
    channel: str
    peer_id: str  # 接收者 ID
    content: str
    format: MessageFormat = MessageFormat.TEXT
    group_id: Optional[str] = None
    thread_id: Optional[str] = None
    reply_to: Optional[str] = None  # 回复的消息 ID
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "peer_id": self.peer_id,
            "content": self.content,
            "format": self.format.value,
            "group_id": self.group_id,
            "thread_id": self.thread_id,
            "reply_to": self.reply_to,
            "metadata": self.metadata,
        }


class Channel(Protocol):
    """Channel 接口"""
    
    name: str
    
    async def receive(self) -> AsyncIterator["InboundMessage"]:
        """接收消息（webhook/轮询）"""
        ...
    
    async def send(self, message: OutboundMessage) -> bool:
        """发送消息"""
        ...
    
    def get_session_key(self, msg: InboundMessage) -> str:
        """生成 session key（确定性路由）"""
        ...
    
    def supports_capability(self, cap: str) -> bool:
        """检查是否支持某能力（markdown/embeds/buttons 等）"""
        ...

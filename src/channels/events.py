"""消息事件定义"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class MessageType(str, Enum):
    """消息类型"""
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    LOCATION = "location"
    CONTACT = "contact"
    STICKER = "sticker"
    VOICE = "voice"
    UNKNOWN = "unknown"


@dataclass
class MediaAttachment:
    """媒体附件"""
    url: Optional[str] = None
    file_path: Optional[str] = None
    mime_type: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    duration: Optional[int] = None  # 音频/视频时长（秒）
    width: Optional[int] = None     # 图片/视频宽度
    height: Optional[int] = None    # 图片/视频高度
    caption: Optional[str] = None   # 媒体说明文字

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            k: v for k, v in {
                "url": self.url,
                "file_path": self.file_path,
                "mime_type": self.mime_type,
                "file_name": self.file_name,
                "file_size": self.file_size,
                "duration": self.duration,
                "width": self.width,
                "height": self.height,
                "caption": self.caption,
            }.items() if v is not None
        }


@dataclass
class InboundMessage:
    """
    入站消息 - 从外部平台接收的消息

    Attributes:
        channel: 通道名称 (telegram, slack, discord, whatsapp, signal)
        sender_id: 发送者唯一标识
        sender_name: 发送者显示名称
        chat_id: 聊天/频道/群组 ID
        chat_type: 聊天类型 (private, group, channel, supergroup)
        message_id: 平台消息 ID
        content: 消息文本内容
        message_type: 消息类型
        media: 媒体附件列表
        reply_to: 回复的消息 ID（如果是回复）
        mentions: 被提及的用户 ID 列表
        metadata: 平台特定的原始元数据
        timestamp: 消息时间戳
        internal_id: 内部唯一标识符
    """
    channel: str
    sender_id: str
    sender_name: Optional[str] = None
    chat_id: str = ""
    chat_type: str = "private"
    message_id: Optional[str] = None
    content: str = ""
    message_type: MessageType = MessageType.TEXT
    media: List[MediaAttachment] = field(default_factory=list)
    content_parts: List[Dict[str, Any]] = field(default_factory=list)
    """Ordered list of content parts preserving interleaving of text and media.
    Each part is {"type": "text", "content": "..."} or {"type": "image", "url": "..."}.
    When empty, fall back to content + media fields."""
    reply_to: Optional[str] = None
    mentions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    internal_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self):
        """后处理"""
        if not self.chat_id:
            self.chat_id = self.sender_id

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "internal_id": self.internal_id,
            "channel": self.channel,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "chat_id": self.chat_id,
            "chat_type": self.chat_type,
            "message_id": self.message_id,
            "content": self.content,
            "message_type": self.message_type.value,
            "media": [m.to_dict() for m in self.media],
            "reply_to": self.reply_to,
            "mentions": self.mentions,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }

    @property
    def is_group(self) -> bool:
        """是否为群组消息"""
        return self.chat_type in ("group", "supergroup", "channel")

    @property
    def has_media(self) -> bool:
        """是否包含媒体"""
        return len(self.media) > 0


@dataclass
class OutboundMessage:
    """
    出站消息 - 发送到外部平台的消息

    Attributes:
        channel: 目标通道名称
        chat_id: 目标聊天 ID
        content: 消息内容
        media_urls: 媒体 URL 列表
        media_paths: 本地媒体文件路径列表
        reply_to: 回复的消息 ID
        parse_mode: 解析模式 (HTML, Markdown, MarkdownV2)
        silent: 是否静默发送（不触发通知）
        metadata: 平台特定的额外参数
    """
    channel: str
    chat_id: str
    content: str = ""
    media_urls: List[str] = field(default_factory=list)
    media_paths: List[str] = field(default_factory=list)
    reply_to: Optional[str] = None
    parse_mode: Optional[str] = None
    silent: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "channel": self.channel,
            "chat_id": self.chat_id,
            "content": self.content,
            "media_urls": self.media_urls,
            "media_paths": self.media_paths,
            "reply_to": self.reply_to,
            "parse_mode": self.parse_mode,
            "silent": self.silent,
            "metadata": self.metadata,
        }

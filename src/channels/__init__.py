"""Channels 模块 - 多平台消息通道支持

提供统一的接口连接各种即时通讯平台，包括 Telegram、Slack、Discord、WhatsApp、Signal 等。

Usage:
    from src.channels import ChannelManager, InboundMessage

    # 初始化管理器
    manager = ChannelManager(config)
    await manager.initialize()

    # 注册消息处理器
    async def handle_message(msg: InboundMessage):
        print(f"收到消息: {msg.content} from {msg.sender_id}")

    manager.on_message = handle_message

    # 启动所有通道
    await manager.start()
"""

from .base import BaseChannel, ChannelState
from .events import InboundMessage, OutboundMessage, MessageType, MediaAttachment
from .config import (
    ChannelConfig,
    ChannelType,
    TelegramConfig,
    SlackConfig,
    DiscordConfig,
    WhatsAppConfig,
    SignalConfig,
    FeishuConfig,
    WeComConfig,
    WeComBotConfig,
)
from .manager import ChannelManager
from .registry import ChannelRegistry

__all__ = [
    # 基础类
    "BaseChannel",
    "ChannelState",
    # 事件类
    "InboundMessage",
    "OutboundMessage",
    "MessageType",
    "MediaAttachment",
    # 配置类
    "ChannelConfig",
    "ChannelType",
    "TelegramConfig",
    "SlackConfig",
    "DiscordConfig",
    "WhatsAppConfig",
    "SignalConfig",
    "FeishuConfig",
    "WeComConfig",
    "WeComBotConfig",
    # 管理类
    "ChannelManager",
    "ChannelRegistry",
]

# 延迟导入具体实现（避免强制依赖）
def _get_telegram():
    from .telegram import TelegramChannel
    return TelegramChannel

def _get_slack():
    from .slack import SlackChannel
    return SlackChannel

def _get_discord():
    from .discord import DiscordChannel
    return DiscordChannel

def _get_whatsapp():
    from .whatsapp import WhatsAppChannel
    return WhatsAppChannel

def _get_signal():
    from .signal_ import SignalChannel
    return SignalChannel

def _get_feishu():
    from .feishu import FeishuChannel
    return FeishuChannel

def _get_wecom():
    from .wecom_aibot import WeComChannel
    return WeComChannel

def _get_wecom_bot():
    from .wecom_bot import WeComBotChannel
    return WeComBotChannel

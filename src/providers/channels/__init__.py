# -*- coding: utf-8 -*-
"""
Channel 层

消息通道插件，支持企微/Slack/Telegram 等。
"""

from .base import Channel, InboundMessage, OutboundMessage
from .registry import ChannelRegistry, get_channel_registry

__all__ = [
    "Channel",
    "InboundMessage",
    "OutboundMessage",
    "ChannelRegistry",
    "get_channel_registry",
]

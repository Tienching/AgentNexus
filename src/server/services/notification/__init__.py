# -*- coding: utf-8 -*-
"""Unified Notification System

Provides a common abstraction for sending notifications across different
delivery channels: HTTP webhooks (response_url), Telegram, Slack, etc.
"""

from .models import NotificationTarget, NotificationResult
from .base import NotificationSink
from .http_webhook_sink import HttpWebhookSink
from .telegram_sink import TelegramSink
from .discord_sink import DiscordSink
from .feishu_sink import FeishuSink
from .slack_sink import SlackSink
from .unified_handler import UnifiedNotificationHandler, get_notification_handler

__all__ = [
    "NotificationTarget",
    "NotificationResult",
    "NotificationSink",
    "HttpWebhookSink",
    "TelegramSink",
    "DiscordSink",
    "FeishuSink",
    "SlackSink",
    "UnifiedNotificationHandler",
    "get_notification_handler",
]

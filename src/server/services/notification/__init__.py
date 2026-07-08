# -*- coding: utf-8 -*-
"""Unified Notification System.

Retained core currently supports HTTP webhook notifications only.
"""

from .models import NotificationTarget, NotificationResult
from .base import NotificationSink
from .http_webhook_sink import HttpWebhookSink
from .unified_handler import UnifiedNotificationHandler, get_notification_handler

__all__ = [
    "NotificationTarget",
    "NotificationResult",
    "NotificationSink",
    "HttpWebhookSink",
    "UnifiedNotificationHandler",
    "get_notification_handler",
]

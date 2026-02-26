# -*- coding: utf-8 -*-
"""Unified Notification Handler

Central dispatcher that routes notifications to the appropriate sink
based on the ``NotificationTarget.sink_type``.
"""

import logging
from typing import Dict, Optional

from .base import NotificationSink
from .models import NotificationTarget, NotificationResult
from .http_webhook_sink import HttpWebhookSink
from .telegram_sink import TelegramSink
from .discord_sink import DiscordSink
from .feishu_sink import FeishuSink
from .slack_sink import SlackSink

logger = logging.getLogger(__name__)

# Singleton instance
_handler: Optional["UnifiedNotificationHandler"] = None


class UnifiedNotificationHandler:
    """Routes notifications to the correct delivery sink."""

    def __init__(self):
        self._sinks: Dict[str, NotificationSink] = {
            "response_url": HttpWebhookSink(),
            "telegram": TelegramSink(),
            "discord": DiscordSink(),
            "feishu": FeishuSink(),
            "slack": SlackSink(),
        }

    def register_sink(self, sink_type: str, sink: NotificationSink) -> None:
        """Register a custom notification sink."""
        self._sinks[sink_type] = sink

    def _get_sink(self, sink_type: str) -> Optional[NotificationSink]:
        return self._sinks.get(sink_type)

    async def notify(
        self,
        target: NotificationTarget,
        content: str,
    ) -> NotificationResult:
        """Send a text notification to the target."""
        sink = self._get_sink(target.sink_type)
        if not sink:
            logger.warning(f"Unknown notification sink type: {target.sink_type}")
            return NotificationResult(
                success=False,
                sink_type=target.sink_type,
                error=f"Unknown sink type: {target.sink_type}",
            )
        return await sink.send_text(target, content)

    async def notify_progress(
        self,
        target: NotificationTarget,
        status: str,
    ) -> NotificationResult:
        """Send or update a progress notification.

        Returns the result which may contain a new message_id for
        subsequent updates.
        """
        sink = self._get_sink(target.sink_type)
        if not sink:
            return NotificationResult(
                success=False,
                sink_type=target.sink_type,
                error=f"Unknown sink type: {target.sink_type}",
            )
        return await sink.send_progress(target, status)

    async def notify_completion(
        self,
        target: NotificationTarget,
        content: str,
        success: bool = True,
    ) -> NotificationResult:
        """Send a completion notification."""
        sink = self._get_sink(target.sink_type)
        if not sink:
            return NotificationResult(
                success=False,
                sink_type=target.sink_type,
                error=f"Unknown sink type: {target.sink_type}",
            )
        return await sink.send_completion(target, content, success)

    @staticmethod
    def build_target_from_response_url(
        response_url: str,
        request_data: Optional[dict] = None,
    ) -> NotificationTarget:
        """Convenience: create a target for an HTTP webhook."""
        return NotificationTarget(
            sink_type="response_url",
            response_url=response_url,
            request_data=request_data or {},
        )

    @staticmethod
    def build_target_from_channel(
        channel_name: str,
        chat_id: str,
        message_id: str = "",
    ) -> NotificationTarget:
        """Convenience: create a target for a messaging channel."""
        return NotificationTarget(
            sink_type=channel_name,
            channel_name=channel_name,
            chat_id=chat_id,
            message_id=message_id,
        )


def get_notification_handler() -> UnifiedNotificationHandler:
    """Get or create the global notification handler singleton."""
    global _handler
    if _handler is None:
        _handler = UnifiedNotificationHandler()
    return _handler

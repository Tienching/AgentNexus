# -*- coding: utf-8 -*-
"""HTTP Webhook notification sink (wraps existing CallbackHandler)"""

import logging
from typing import List

from .base import NotificationSink
from .models import NotificationTarget, NotificationResult

logger = logging.getLogger(__name__)


class HttpWebhookSink(NotificationSink):
    """Delivers notifications via HTTP POST to a response_url.

    Delegates to the existing ``CallbackHandler`` for actual HTTP transport
    and payload formatting (IM AI 助手 markdown format).
    """

    def __init__(self):
        # Lazy import to avoid circular imports
        from ..callback_handler import CallbackHandler
        self._handler = CallbackHandler()

    async def send_text(
        self,
        target: NotificationTarget,
        content: str,
    ) -> NotificationResult:
        if not target.response_url:
            return NotificationResult(
                success=False,
                sink_type="response_url",
                error="No response_url provided",
            )

        success = await self._handler.send_callback(
            response_url=target.response_url,
            messages=[content],
            request_data=target.request_data or None,
        )
        return NotificationResult(success=success, sink_type="response_url")

    async def send_progress(
        self,
        target: NotificationTarget,
        status: str,
    ) -> NotificationResult:
        # HTTP webhooks do not support editing; just send a new message.
        return await self.send_text(target, status)

    async def send_completion(
        self,
        target: NotificationTarget,
        content: str,
        success: bool = True,
    ) -> NotificationResult:
        prefix = "✅ " if success else "❌ "
        return await self.send_text(target, prefix + content)

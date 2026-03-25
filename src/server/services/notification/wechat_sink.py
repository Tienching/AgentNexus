# -*- coding: utf-8 -*-
"""WeChat Personal notification sink

Delivers notifications via the WeChat iLink Bot API through the running
WeChatChannel instance.  WeChat does not support message editing.
"""

import logging
from typing import Optional

from .base import NotificationSink
from .models import NotificationTarget, NotificationResult

logger = logging.getLogger(__name__)

# WeChat text message length limit (chars)
WECHAT_MAX_LENGTH = 4000


def _split_text(text: str, max_len: int = WECHAT_MAX_LENGTH) -> list[str]:
    """Split long text into chunks that respect WeChat limits."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at last newline within limit
        split_pos = text.rfind("\n", 0, max_len)
        if split_pos <= 0:
            split_pos = max_len
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    return chunks


class WeChatSink(NotificationSink):
    """Delivers notifications via WeChat iLink Bot API.

    Uses the running ChannelManager / WeChatChannel for actual sending.
    WeChat does not support message editing, so progress updates are
    sent as new messages.
    """

    def _get_channel(self):
        """Get the running WeChat channel instance."""
        from ..channel_service import get_channel_service
        service = get_channel_service()
        if not service or not service.manager:
            return None
        return service.manager.get_channel("wechat")

    async def _send_via_channel(
        self,
        chat_id: str,
        content: str,
    ) -> Optional[str]:
        """Send a message through the WeChatChannel and return success."""
        channel = self._get_channel()
        if not channel:
            return None

        from src.channels.events import OutboundMessage
        msg = OutboundMessage(
            channel="wechat",
            chat_id=chat_id,
            content=content,
        )
        result = await channel._send_message(msg)
        return str(result) if result else None

    async def send_text(
        self,
        target: NotificationTarget,
        content: str,
    ) -> NotificationResult:
        channel = self._get_channel()
        if not channel:
            return NotificationResult(
                success=False,
                sink_type="wechat",
                error="WeChat channel not available",
            )

        if not target.chat_id:
            return NotificationResult(
                success=False,
                sink_type="wechat",
                error="No chat_id provided",
            )

        try:
            chunks = _split_text(content, WECHAT_MAX_LENGTH)
            last_result = None

            for chunk in chunks:
                result = await self._send_via_channel(target.chat_id, chunk)
                if result:
                    last_result = result

            if last_result:
                return NotificationResult(
                    success=True,
                    sink_type="wechat",
                    message_id=last_result,
                )
            else:
                return NotificationResult(
                    success=False,
                    sink_type="wechat",
                    error="Failed to send message via WeChat channel",
                )
        except Exception as e:
            logger.error(f"WeChat send_text failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="wechat",
                error=str(e),
            )

    async def send_progress(
        self,
        target: NotificationTarget,
        status: str,
    ) -> NotificationResult:
        # WeChat does not support message editing.  Sending every progress
        # update as a new message creates a poor UX (multiple "正在处理"
        # messages).  Skip intermediate progress silently; the user will
        # receive the final result via send_completion / send_text.
        logger.debug(f"[wechat] Skipping progress message (no edit support): {status[:60]}")
        return NotificationResult(
            success=True,
            sink_type="wechat",
        )

    async def send_completion(
        self,
        target: NotificationTarget,
        content: str,
        success: bool = True,
    ) -> NotificationResult:
        if not success:
            content = f"❌ 处理失败\n\n{content}"
        return await self.send_text(target, content)

# -*- coding: utf-8 -*-
"""WeCom Bot (企业微信普通机器人) notification sink

Delivers notifications via the WeCom Bot through the running
WeComBotChannel instance. Uses webhook/send.
"""

import logging
from typing import Optional

from .base import NotificationSink
from .models import NotificationTarget, NotificationResult

logger = logging.getLogger(__name__)

# WeCom Bot message length limit (bytes, UTF-8)
WECOM_BOT_MAX_LENGTH = 20480


def _split_text(text: str, max_len: int = WECOM_BOT_MAX_LENGTH) -> list[str]:
    """Split long text into chunks that respect WeCom Bot limits."""
    if len(text.encode("utf-8")) <= max_len:
        return [text]

    chunks = []
    while text:
        encoded = text.encode("utf-8")
        if len(encoded) <= max_len:
            chunks.append(text)
            break
        approx_pos = max_len
        while len(text[:approx_pos].encode("utf-8")) > max_len:
            approx_pos -= 100
        split_pos = text.rfind("\n", 0, approx_pos)
        if split_pos <= 0:
            split_pos = approx_pos
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    return chunks


class WeComBotSink(NotificationSink):
    """Delivers notifications via WeCom Bot.

    Uses the running ChannelManager / WeComBotChannel for actual sending.
    """

    def _get_channel(self):
        """Get the running WeCom Bot channel instance."""
        from ..channel_service import get_channel_service
        service = get_channel_service()
        if not service or not service.manager:
            return None
        return service.manager.get_channel("wecom_bot")

    async def _send_via_channel(
        self,
        chat_id: str,
        content: str,
    ) -> Optional[str]:
        """Send a message through the WeComBotChannel."""
        channel = self._get_channel()
        if not channel:
            return None

        from src.channels.events import OutboundMessage
        msg = OutboundMessage(
            channel="wecom_bot",
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
                sink_type="wecom_bot",
                error="WeCom Bot channel not available",
            )

        if not target.chat_id:
            return NotificationResult(
                success=False,
                sink_type="wecom_bot",
                error="No chat_id provided",
            )

        try:
            chunks = _split_text(content, WECOM_BOT_MAX_LENGTH)
            last_result = None

            for chunk in chunks:
                result = await self._send_via_channel(target.chat_id, chunk)
                if result:
                    last_result = result

            if last_result:
                return NotificationResult(
                    success=True,
                    sink_type="wecom_bot",
                    message_id=last_result,
                )
            else:
                return NotificationResult(
                    success=False,
                    sink_type="wecom_bot",
                    error="Failed to send message",
                )
        except Exception as e:
            logger.error(f"WeCom Bot send_text failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="wecom_bot",
                error=str(e),
            )

    async def send_progress(
        self,
        target: NotificationTarget,
        status: str,
    ) -> NotificationResult:
        # 普通机器人可以发送进度消息（不像智能机器人 response_url 一次性使用）
        return await self.send_text(target, f"⏳ {status}")

    async def send_completion(
        self,
        target: NotificationTarget,
        content: str,
        success: bool = True,
    ) -> NotificationResult:
        if not success:
            content = f"❌ 处理失败\n\n{content}"
        return await self.send_text(target, content)

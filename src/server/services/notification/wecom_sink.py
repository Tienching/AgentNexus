# -*- coding: utf-8 -*-
"""WeCom (企业微信) notification sink

Delivers notifications via the WeCom AI Bot through the running
WeComChannel instance. Uses response_url for message delivery.
"""

import logging
from typing import Optional

from .base import NotificationSink
from .models import NotificationTarget, NotificationResult

logger = logging.getLogger(__name__)

# WeCom message length limit (bytes, UTF-8)
WECOM_MAX_LENGTH = 20480


def _split_text(text: str, max_len: int = WECOM_MAX_LENGTH) -> list[str]:
    """Split long text into chunks that respect WeCom limits."""
    if len(text.encode("utf-8")) <= max_len:
        return [text]

    chunks = []
    while text:
        encoded = text.encode("utf-8")
        if len(encoded) <= max_len:
            chunks.append(text)
            break
        # Try to split at last newline within limit
        # Use char-based approximation then verify
        approx_pos = max_len
        while len(text[:approx_pos].encode("utf-8")) > max_len:
            approx_pos -= 100
        split_pos = text.rfind("\n", 0, approx_pos)
        if split_pos <= 0:
            split_pos = approx_pos
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    return chunks


class WeComSink(NotificationSink):
    """Delivers notifications via WeCom AI Bot.

    Uses the running ChannelManager / WeComChannel for actual sending.
    WeCom AI Bot does not support message editing.
    """

    def _get_channel(self):
        """Get the running WeCom channel instance."""
        from ..channel_service import get_channel_service
        service = get_channel_service()
        if not service or not service.manager:
            return None
        return service.manager.get_channel("wecom")

    async def _send_via_channel(
        self,
        chat_id: str,
        content: str,
    ) -> Optional[str]:
        """Send a message through the WeComChannel and return success."""
        channel = self._get_channel()
        if not channel:
            return None

        from src.channels.events import OutboundMessage
        msg = OutboundMessage(
            channel="wecom",
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
                sink_type="wecom",
                error="WeCom channel not available",
            )

        if not target.chat_id:
            return NotificationResult(
                success=False,
                sink_type="wecom",
                error="No chat_id provided",
            )

        try:
            chunks = _split_text(content, WECOM_MAX_LENGTH)
            last_result = None

            for chunk in chunks:
                result = await self._send_via_channel(target.chat_id, chunk)
                if result:
                    last_result = result

            if last_result:
                return NotificationResult(
                    success=True,
                    sink_type="wecom",
                    message_id=last_result,
                )
            else:
                return NotificationResult(
                    success=False,
                    sink_type="wecom",
                    error="Failed to send message (no response_url available?)",
                )
        except Exception as e:
            logger.error(f"WeCom send_text failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="wecom",
                error=str(e),
            )

    async def send_progress(
        self,
        target: NotificationTarget,
        status: str,
    ) -> NotificationResult:
        # WeCom's response_url is single-use. We must NOT consume it
        # for intermediate progress messages — save it for the final reply.
        # Simply return success without actually sending anything.
        logger.debug(
            f"[wecom] Skipping progress message (response_url is single-use): "
            f"{status[:60]}"
        )
        return NotificationResult(
            success=True,
            sink_type="wecom",
        )

    async def send_completion(
        self,
        target: NotificationTarget,
        content: str,
        success: bool = True,
    ) -> NotificationResult:
        # Send the content directly without emoji prefixes for WeCom.
        # If it failed, add a short indicator.
        if not success:
            content = f"❌ 处理失败\n\n{content}"
        return await self.send_text(target, content)

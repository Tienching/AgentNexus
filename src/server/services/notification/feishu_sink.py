# -*- coding: utf-8 -*-
"""Feishu (飞书) notification sink

Delivers notifications via the Feishu Bot API through the running
FeishuChannel instance.  Supports in-place message editing for
progress updates.
"""

import json
import logging
from typing import Any, Optional

from .base import NotificationSink
from .models import NotificationTarget, NotificationResult

logger = logging.getLogger(__name__)

# Feishu text message length limit
FEISHU_MAX_LENGTH = 4000
# Threshold for in-place editing (leave margin)
FEISHU_EDIT_THRESHOLD = 3800


def _split_text(text: str, max_len: int = FEISHU_MAX_LENGTH) -> list[str]:
    """Split long text into chunks that respect Feishu limits."""
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


class FeishuSink(NotificationSink):
    """Delivers notifications via Feishu Bot API.

    Uses the running ChannelManager / FeishuChannel for actual sending.
    Supports editing existing messages for progress updates.
    """

    def _get_channel(self):
        """Get the running Feishu channel instance."""
        from ..channel_service import get_channel_service
        service = get_channel_service()
        if not service or not service.manager:
            return None
        return service.manager.get_channel("feishu")

    async def _send_via_channel(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
    ) -> Optional[str]:
        """Send a message through the FeishuChannel and return the message_id."""
        channel = self._get_channel()
        if not channel:
            return None

        from src.channels.events import OutboundMessage
        msg = OutboundMessage(
            channel="feishu",
            chat_id=chat_id,
            content=content,
            reply_to=reply_to or "",
        )
        result = await channel._send_message(msg)
        # result is the message_id string from FeishuChannel
        return str(result) if result else None

    async def _edit_message(self, message_id: str, content: str) -> bool:
        """Edit an existing message via FeishuChannel."""
        channel = self._get_channel()
        if not channel:
            return False
        return await channel.edit_message(message_id, content)

    async def send_text(
        self,
        target: NotificationTarget,
        content: str,
    ) -> NotificationResult:
        channel = self._get_channel()
        if not channel:
            return NotificationResult(
                success=False,
                sink_type="feishu",
                error="Feishu channel not available",
            )

        if not target.chat_id:
            return NotificationResult(
                success=False,
                sink_type="feishu",
                error="No chat_id provided",
            )

        try:
            chunks = _split_text(content, FEISHU_MAX_LENGTH)
            last_msg_id = None

            for chunk in chunks:
                msg_id = await self._send_via_channel(target.chat_id, chunk)
                if msg_id:
                    last_msg_id = msg_id

            if last_msg_id:
                return NotificationResult(
                    success=True,
                    sink_type="feishu",
                    message_id=last_msg_id,
                )
            else:
                return NotificationResult(
                    success=False,
                    sink_type="feishu",
                    error="Failed to send message",
                )
        except Exception as e:
            logger.error(f"Feishu send_text failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="feishu",
                error=str(e),
            )

    async def send_progress(
        self,
        target: NotificationTarget,
        status: str,
    ) -> NotificationResult:
        channel = self._get_channel()
        if not channel:
            return NotificationResult(
                success=False,
                sink_type="feishu",
                error="Feishu channel not available",
            )

        if not target.chat_id:
            return NotificationResult(
                success=False,
                sink_type="feishu",
                error="No chat_id provided",
            )

        try:
            if target.message_id:
                # Try to edit the existing progress message in place
                truncated = status[:FEISHU_EDIT_THRESHOLD]
                try:
                    success = await self._edit_message(target.message_id, truncated)
                    if success:
                        return NotificationResult(
                            success=True,
                            sink_type="feishu",
                            message_id=target.message_id,
                        )
                except Exception as e:
                    logger.warning(
                        f"Feishu send_progress edit failed, falling back to new message: {e}"
                    )

            # No existing message or edit failed — send a new one
            msg_id = await self._send_via_channel(
                target.chat_id, status[:FEISHU_MAX_LENGTH]
            )
            return NotificationResult(
                success=True,
                sink_type="feishu",
                message_id=msg_id,
            )
        except Exception as e:
            logger.error(f"Feishu send_progress failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="feishu",
                error=str(e),
            )

    async def send_completion(
        self,
        target: NotificationTarget,
        content: str,
        success: bool = True,
    ) -> NotificationResult:
        prefix = "✅ **完成**\n\n" if success else "❌ **失败**\n\n"
        full_content = prefix + content

        channel = self._get_channel()
        if not channel:
            return NotificationResult(
                success=False,
                sink_type="feishu",
                error="Feishu channel not available",
            )

        if not target.chat_id:
            return NotificationResult(
                success=False,
                sink_type="feishu",
                error="No chat_id provided",
            )

        try:
            # If we have a progress message and content is short, edit in place
            if target.message_id and len(full_content) <= FEISHU_EDIT_THRESHOLD:
                try:
                    ok = await self._edit_message(target.message_id, full_content)
                    if ok:
                        return NotificationResult(
                            success=True,
                            sink_type="feishu",
                            message_id=target.message_id,
                        )
                except Exception:
                    pass  # Fall through to send new messages

            # Send as new message(s), potentially splitting
            return await self.send_text(target, full_content)

        except Exception as e:
            logger.error(f"Feishu send_completion failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="feishu",
                error=str(e),
            )

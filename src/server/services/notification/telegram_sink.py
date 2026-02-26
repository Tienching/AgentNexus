# -*- coding: utf-8 -*-
"""Telegram notification sink

Delivers notifications via the Telegram Bot API through the running
TelegramChannel instance.  Supports in-place message editing for
progress updates.
"""

import logging
from typing import Optional

from .base import NotificationSink
from .models import NotificationTarget, NotificationResult

logger = logging.getLogger(__name__)

# Telegram message length limit
TELEGRAM_MAX_LENGTH = 4096
# Threshold to decide between editing and new messages
TELEGRAM_EDIT_THRESHOLD = 4000


def _split_text(text: str, max_len: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    """Split long text into chunks that respect Telegram limits."""
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


class TelegramSink(NotificationSink):
    """Delivers notifications via Telegram Bot API.

    Uses the running ChannelManager / TelegramChannel for actual sending.
    Supports editing existing messages for progress updates.
    """

    def _get_channel(self):
        """Get the running Telegram channel instance."""
        from ..channel_service import get_channel_service
        service = get_channel_service()
        if not service or not service.manager:
            return None
        return service.manager.get_channel("telegram")

    def _get_bot(self):
        """Get the underlying telegram Bot instance."""
        channel = self._get_channel()
        if not channel:
            return None
        return getattr(channel, "_app", None) and channel._app.bot

    async def send_text(
        self,
        target: NotificationTarget,
        content: str,
    ) -> NotificationResult:
        bot = self._get_bot()
        if not bot:
            return NotificationResult(
                success=False,
                sink_type="telegram",
                error="Telegram bot not available",
            )

        if not target.chat_id:
            return NotificationResult(
                success=False,
                sink_type="telegram",
                error="No chat_id provided",
            )

        try:
            chat_id = int(target.chat_id) if target.chat_id.lstrip("-").isdigit() else target.chat_id
            chunks = _split_text(content, TELEGRAM_MAX_LENGTH)
            last_msg_id = None

            for chunk in chunks:
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    disable_notification=False,
                )
                last_msg_id = str(msg.message_id)

            return NotificationResult(
                success=True,
                sink_type="telegram",
                message_id=last_msg_id,
            )
        except Exception as e:
            logger.error(f"Telegram send_text failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="telegram",
                error=str(e),
            )

    async def send_progress(
        self,
        target: NotificationTarget,
        status: str,
    ) -> NotificationResult:
        bot = self._get_bot()
        if not bot:
            return NotificationResult(
                success=False,
                sink_type="telegram",
                error="Telegram bot not available",
            )

        chat_id = int(target.chat_id) if target.chat_id.lstrip("-").isdigit() else target.chat_id

        try:
            if target.message_id:
                # Edit the existing progress message in place
                msg_id = int(target.message_id)
                # Truncate to fit Telegram edit limit
                truncated = status[:TELEGRAM_EDIT_THRESHOLD]
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=truncated,
                )
                return NotificationResult(
                    success=True,
                    sink_type="telegram",
                    message_id=target.message_id,
                )
            else:
                # No existing message — send a new one and return its ID
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=status[:TELEGRAM_MAX_LENGTH],
                )
                new_msg_id = str(msg.message_id)
                return NotificationResult(
                    success=True,
                    sink_type="telegram",
                    message_id=new_msg_id,
                )
        except Exception as e:
            # If editing fails (e.g., message too old), fall back to sending a new message
            logger.warning(f"Telegram send_progress edit failed, falling back to new message: {e}")
            try:
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=status[:TELEGRAM_MAX_LENGTH],
                )
                return NotificationResult(
                    success=True,
                    sink_type="telegram",
                    message_id=str(msg.message_id),
                )
            except Exception as e2:
                logger.error(f"Telegram send_progress fallback failed: {e2}")
                return NotificationResult(
                    success=False,
                    sink_type="telegram",
                    error=str(e2),
                )

    async def send_completion(
        self,
        target: NotificationTarget,
        content: str,
        success: bool = True,
    ) -> NotificationResult:
        prefix = "✅ **完成**\n\n" if success else "❌ **失败**\n\n"
        full_content = prefix + content

        bot = self._get_bot()
        if not bot:
            return NotificationResult(
                success=False,
                sink_type="telegram",
                error="Telegram bot not available",
            )

        chat_id = int(target.chat_id) if target.chat_id.lstrip("-").isdigit() else target.chat_id

        try:
            # If we have a progress message, try to edit it with the final result
            if target.message_id and len(full_content) <= TELEGRAM_EDIT_THRESHOLD:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=int(target.message_id),
                        text=full_content,
                    )
                    return NotificationResult(
                        success=True,
                        sink_type="telegram",
                        message_id=target.message_id,
                    )
                except Exception:
                    pass  # Fall through to send new messages

            # Send as new message(s), potentially splitting
            return await self.send_text(target, full_content)

        except Exception as e:
            logger.error(f"Telegram send_completion failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="telegram",
                error=str(e),
            )

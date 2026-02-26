# -*- coding: utf-8 -*-
"""Discord notification sink

Delivers notifications via the Discord Bot API through the running
DiscordChannel instance.  Supports in-place message editing for
progress updates.
"""

import logging
from typing import Any, Optional

from .base import NotificationSink
from .models import NotificationTarget, NotificationResult

logger = logging.getLogger(__name__)

# Discord message length limit
DISCORD_MAX_LENGTH = 2000
# Threshold to decide between editing and new messages
DISCORD_EDIT_THRESHOLD = 1900


def _split_text(text: str, max_len: int = DISCORD_MAX_LENGTH) -> list[str]:
    """Split long text into chunks that respect Discord limits."""
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


class DiscordSink(NotificationSink):
    """Delivers notifications via Discord Bot API.

    Uses the running ChannelManager / DiscordChannel for actual sending.
    Supports editing existing messages for progress updates.
    """

    def _get_channel(self):
        """Get the running Discord channel instance."""
        from ..channel_service import get_channel_service
        service = get_channel_service()
        if not service or not service.manager:
            return None
        return service.manager.get_channel("discord")

    def _get_client(self):
        """Get the underlying discord.Client instance."""
        channel = self._get_channel()
        if not channel:
            return None
        return getattr(channel, "_client", None)

    async def _resolve_channel(self, client: Any, chat_id: str) -> Optional[Any]:
        """Resolve a chat_id to a discord channel object.

        Tries get_channel (cached) first, then falls back to fetch_user +
        create_dm for DM channels.
        """
        channel_id = int(chat_id)
        ch = client.get_channel(channel_id)
        if ch:
            return ch
        # Fallback: try as a user ID and open a DM
        try:
            user = await client.fetch_user(channel_id)
            if user:
                return await user.create_dm()
        except Exception:
            pass
        return None

    async def send_text(
        self,
        target: NotificationTarget,
        content: str,
    ) -> NotificationResult:
        client = self._get_client()
        if not client:
            return NotificationResult(
                success=False,
                sink_type="discord",
                error="Discord client not available",
            )

        if not target.chat_id:
            return NotificationResult(
                success=False,
                sink_type="discord",
                error="No chat_id provided",
            )

        try:
            ch = await self._resolve_channel(client, target.chat_id)
            if not ch:
                return NotificationResult(
                    success=False,
                    sink_type="discord",
                    error=f"Channel not found: {target.chat_id}",
                )

            chunks = _split_text(content, DISCORD_MAX_LENGTH)
            last_msg_id = None

            for chunk in chunks:
                msg = await ch.send(content=chunk)
                last_msg_id = str(msg.id)

            return NotificationResult(
                success=True,
                sink_type="discord",
                message_id=last_msg_id,
            )
        except Exception as e:
            logger.error(f"Discord send_text failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="discord",
                error=str(e),
            )

    async def send_progress(
        self,
        target: NotificationTarget,
        status: str,
    ) -> NotificationResult:
        client = self._get_client()
        if not client:
            return NotificationResult(
                success=False,
                sink_type="discord",
                error="Discord client not available",
            )

        if not target.chat_id:
            return NotificationResult(
                success=False,
                sink_type="discord",
                error="No chat_id provided",
            )

        try:
            ch = await self._resolve_channel(client, target.chat_id)
            if not ch:
                return NotificationResult(
                    success=False,
                    sink_type="discord",
                    error=f"Channel not found: {target.chat_id}",
                )

            if target.message_id:
                # Edit the existing progress message in place
                truncated = status[:DISCORD_EDIT_THRESHOLD]
                try:
                    msg = await ch.fetch_message(int(target.message_id))
                    await msg.edit(content=truncated)
                    return NotificationResult(
                        success=True,
                        sink_type="discord",
                        message_id=target.message_id,
                    )
                except Exception as e:
                    # Edit failed — fall through to send a new message
                    logger.warning(
                        f"Discord send_progress edit failed, falling back to new message: {e}"
                    )

            # No existing message or edit failed — send a new one
            msg = await ch.send(content=status[:DISCORD_MAX_LENGTH])
            return NotificationResult(
                success=True,
                sink_type="discord",
                message_id=str(msg.id),
            )
        except Exception as e:
            logger.error(f"Discord send_progress failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="discord",
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

        client = self._get_client()
        if not client:
            return NotificationResult(
                success=False,
                sink_type="discord",
                error="Discord client not available",
            )

        if not target.chat_id:
            return NotificationResult(
                success=False,
                sink_type="discord",
                error="No chat_id provided",
            )

        try:
            ch = await self._resolve_channel(client, target.chat_id)
            if not ch:
                return NotificationResult(
                    success=False,
                    sink_type="discord",
                    error=f"Channel not found: {target.chat_id}",
                )

            # If we have a progress message, try to edit it with the final result
            if target.message_id and len(full_content) <= DISCORD_EDIT_THRESHOLD:
                try:
                    msg = await ch.fetch_message(int(target.message_id))
                    await msg.edit(content=full_content)
                    return NotificationResult(
                        success=True,
                        sink_type="discord",
                        message_id=target.message_id,
                    )
                except Exception:
                    pass  # Fall through to send new messages

            # Send as new message(s), potentially splitting
            return await self.send_text(target, full_content)

        except Exception as e:
            logger.error(f"Discord send_completion failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="discord",
                error=str(e),
            )

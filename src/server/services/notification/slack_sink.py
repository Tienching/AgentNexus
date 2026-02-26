# -*- coding: utf-8 -*-
"""Slack notification sink

Delivers notifications via the Slack Web API through the running
SlackChannel instance.  Supports in-place message editing for
progress updates using chat.update.
"""

import logging
from typing import Any, Optional

from .base import NotificationSink
from .models import NotificationTarget, NotificationResult

logger = logging.getLogger(__name__)

# Slack message length limit (text field for chat.postMessage)
SLACK_MAX_LENGTH = 4000
# Threshold for in-place editing (leave margin for formatting)
SLACK_EDIT_THRESHOLD = 3800


def _split_text(text: str, max_len: int = SLACK_MAX_LENGTH) -> list[str]:
    """Split long text into chunks that respect Slack limits."""
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


class SlackSink(NotificationSink):
    """Delivers notifications via Slack Web API.

    Uses the running ChannelManager / SlackChannel for actual sending.
    Supports editing existing messages for progress updates via chat.update.
    """

    def _get_channel(self):
        """Get the running Slack channel instance."""
        from ..channel_service import get_channel_service
        service = get_channel_service()
        if not service or not service.manager:
            return None
        return service.manager.get_channel("slack")

    def _get_web_client(self):
        """Get the underlying Slack AsyncWebClient."""
        channel = self._get_channel()
        if not channel:
            return None
        return getattr(channel, "_web_client", None)

    async def send_text(
        self,
        target: NotificationTarget,
        content: str,
    ) -> NotificationResult:
        client = self._get_web_client()
        if not client:
            return NotificationResult(
                success=False,
                sink_type="slack",
                error="Slack client not available",
            )

        if not target.chat_id:
            return NotificationResult(
                success=False,
                sink_type="slack",
                error="No chat_id provided",
            )

        try:
            chunks = _split_text(content, SLACK_MAX_LENGTH)
            last_msg_ts = None

            for chunk in chunks:
                resp = await client.chat_postMessage(
                    channel=target.chat_id,
                    text=chunk,
                )
                if resp.get("ok"):
                    last_msg_ts = resp.get("ts")

            if last_msg_ts:
                return NotificationResult(
                    success=True,
                    sink_type="slack",
                    message_id=last_msg_ts,
                )
            else:
                return NotificationResult(
                    success=False,
                    sink_type="slack",
                    error="Failed to send message",
                )
        except Exception as e:
            logger.error(f"Slack send_text failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="slack",
                error=str(e),
            )

    async def send_progress(
        self,
        target: NotificationTarget,
        status: str,
    ) -> NotificationResult:
        client = self._get_web_client()
        if not client:
            return NotificationResult(
                success=False,
                sink_type="slack",
                error="Slack client not available",
            )

        if not target.chat_id:
            return NotificationResult(
                success=False,
                sink_type="slack",
                error="No chat_id provided",
            )

        try:
            if target.message_id:
                # Edit the existing progress message in place via chat.update
                truncated = status[:SLACK_EDIT_THRESHOLD]
                try:
                    resp = await client.chat_update(
                        channel=target.chat_id,
                        ts=target.message_id,
                        text=truncated,
                    )
                    if resp.get("ok"):
                        return NotificationResult(
                            success=True,
                            sink_type="slack",
                            message_id=target.message_id,
                        )
                except Exception as e:
                    # Edit failed — fall through to send a new message
                    logger.warning(
                        f"Slack send_progress edit failed, falling back to new message: {e}"
                    )

            # No existing message or edit failed — send a new one
            resp = await client.chat_postMessage(
                channel=target.chat_id,
                text=status[:SLACK_MAX_LENGTH],
            )
            msg_ts = resp.get("ts") if resp.get("ok") else None
            return NotificationResult(
                success=True,
                sink_type="slack",
                message_id=msg_ts,
            )
        except Exception as e:
            logger.error(f"Slack send_progress failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="slack",
                error=str(e),
            )

    async def send_completion(
        self,
        target: NotificationTarget,
        content: str,
        success: bool = True,
    ) -> NotificationResult:
        prefix = "✅ *完成*\n\n" if success else "❌ *失败*\n\n"
        full_content = prefix + content

        client = self._get_web_client()
        if not client:
            return NotificationResult(
                success=False,
                sink_type="slack",
                error="Slack client not available",
            )

        if not target.chat_id:
            return NotificationResult(
                success=False,
                sink_type="slack",
                error="No chat_id provided",
            )

        try:
            # If we have a progress message and content is short, edit in place
            if target.message_id and len(full_content) <= SLACK_EDIT_THRESHOLD:
                try:
                    resp = await client.chat_update(
                        channel=target.chat_id,
                        ts=target.message_id,
                        text=full_content,
                    )
                    if resp.get("ok"):
                        return NotificationResult(
                            success=True,
                            sink_type="slack",
                            message_id=target.message_id,
                        )
                except Exception:
                    pass  # Fall through to send new messages

            # Send as new message(s), potentially splitting
            return await self.send_text(target, full_content)

        except Exception as e:
            logger.error(f"Slack send_completion failed: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                sink_type="slack",
                error=str(e),
            )

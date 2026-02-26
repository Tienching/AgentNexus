# -*- coding: utf-8 -*-
"""Notification data models"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class NotificationTarget:
    """Notification delivery target descriptor.

    Describes *where* and *how* to deliver a notification.

    Attributes:
        sink_type: Delivery mechanism identifier.
            - "response_url": HTTP POST webhook (for enterprise IM bots)
            - "telegram": Telegram Bot API
            - "slack": Slack Web API
            - "discord": Discord Bot API
            - Other channel names as they are added.
        response_url: HTTP webhook URL (used when sink_type == "response_url").
        channel_name: Channel identifier (e.g. "telegram", "slack").
        chat_id: Target chat / channel ID for the channel sink.
        message_id: Optional platform message ID for editing an existing message
            (e.g., editing a "processing…" placeholder with the final result).
        request_data: Extra metadata carried along for callbacks (msg_id, user, etc.)
    """
    sink_type: str  # "response_url" | "telegram" | "slack" | "discord" | ...
    # HTTP webhook specific
    response_url: str = ""
    # Channel specific
    channel_name: str = ""
    chat_id: str = ""
    message_id: str = ""
    # Extra callback metadata
    request_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationResult:
    """Result of a notification delivery attempt."""
    success: bool
    sink_type: str
    message_id: Optional[str] = None  # Platform message ID (for subsequent edits)
    error: Optional[str] = None

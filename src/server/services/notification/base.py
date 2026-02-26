# -*- coding: utf-8 -*-
"""Abstract base class for notification sinks"""

from abc import ABC, abstractmethod
from typing import List

from .models import NotificationTarget, NotificationResult


class NotificationSink(ABC):
    """Abstract notification delivery sink.

    Subclasses implement the actual delivery mechanism (HTTP POST, Bot API, etc.).
    """

    @abstractmethod
    async def send_text(
        self,
        target: NotificationTarget,
        content: str,
    ) -> NotificationResult:
        """Send a plain-text / markdown notification.

        Args:
            target: Delivery target descriptor.
            content: Text content to send.

        Returns:
            NotificationResult with success status and optional message_id.
        """
        ...

    @abstractmethod
    async def send_progress(
        self,
        target: NotificationTarget,
        status: str,
    ) -> NotificationResult:
        """Send or update a progress indicator.

        Sinks that support message editing (Telegram, Slack) should edit
        the message identified by ``target.message_id`` in place.

        Args:
            target: Delivery target (may include message_id for in-place editing).
            status: Progress text.

        Returns:
            NotificationResult (message_id can be used for subsequent edits).
        """
        ...

    @abstractmethod
    async def send_completion(
        self,
        target: NotificationTarget,
        content: str,
        success: bool = True,
    ) -> NotificationResult:
        """Send a task / request completion notification.

        Args:
            target: Delivery target.
            content: Result text.
            success: Whether the operation succeeded.

        Returns:
            NotificationResult.
        """
        ...

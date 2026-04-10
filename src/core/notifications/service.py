# -*- coding: utf-8 -*-
"""Notification system for in-app notifications.

Provides:
- In-app notification storage and retrieval
- Unread count tracking
- Read/unread status management
- Notification preferences

Usage:
    from src.core.notifications.service import NotificationService

    service = NotificationService()
    service.notify(user_id="user123", title="Task completed", body="Your task is done")
    unread = service.get_unread_count(user_id="user123")
    service.mark_read(user_id="user123", notification_id=1)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Any

from src.runtime.stores.db import get_db


class NotificationType(str, Enum):
    """Notification types."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    TASK_ASSIGNED = "task_assigned"
    TASK_COMPLETED = "task_completed"
    TASK_UPDATED = "task_updated"
    MENTION = "mention"
    COMMENT = "comment"
    SYSTEM = "system"


@dataclass
class Notification:
    """A notification record."""
    id: Optional[int] = None
    user_id: str = ""
    type: NotificationType = NotificationType.INFO
    title: str = ""
    body: str = ""
    data: Optional[dict] = None  # Additional context
    read: bool = False
    read_at: Optional[float] = None
    created_at: float = field(default_factory=time.time)


class NotificationService:
    """Service for managing in-app notifications."""

    def __init__(self):
        self._db = get_db()
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the notifications table."""
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'info',
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                data TEXT,
                read INTEGER NOT NULL DEFAULT 0,
                read_at REAL,
                created_at REAL NOT NULL
            )
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_notifications_user
            ON notifications (user_id, read, created_at DESC)
        """)

    def notify(
        self,
        user_id: str,
        title: str,
        body: str,
        type: NotificationType = NotificationType.INFO,
        data: Optional[dict] = None,
    ) -> Notification:
        """Create a new notification.

        Args:
            user_id: User to notify
            title: Notification title
            body: Notification body text
            type: Notification type
            data: Additional context data

        Returns:
            The created Notification
        """
        self._ensure_table()
        now = time.time()

        cursor = self._db.execute(
            """INSERT INTO notifications (user_id, type, title, body, data, read, created_at)
               VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (user_id, type.value, title, body, json.dumps(data) if data else None, now),
        )

        return Notification(
            id=cursor.lastrowid,
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            data=data,
            read=False,
            created_at=now,
        )

    def get_notifications(
        self,
        user_id: str,
        limit: int = 50,
        unread_only: bool = False,
    ) -> List[Notification]:
        """Get notifications for a user.

        Args:
            user_id: User ID
            limit: Maximum number to return
            unread_only: If True, only return unread notifications

        Returns:
            List of notifications, newest first
        """
        self._ensure_table()

        sql = "SELECT * FROM notifications WHERE user_id = ?"
        params: List[Any] = [user_id]

        if unread_only:
            sql += " AND read = 0"

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._db.execute_fetchall(sql, tuple(params))
        notifications = []

        for row in rows:
            notifications.append(
                Notification(
                    id=row["id"],
                    user_id=row["user_id"],
                    type=NotificationType(row["type"]),
                    title=row["title"],
                    body=row["body"],
                    data=json.loads(row["data"]) if row["data"] else None,
                    read=bool(row["read"]),
                    read_at=row["read_at"],
                    created_at=row["created_at"],
                )
            )

        return notifications

    def get_unread_count(self, user_id: str) -> int:
        """Get the count of unread notifications.

        Args:
            user_id: User ID

        Returns:
            Count of unread notifications
        """
        self._ensure_table()
        row = self._db.execute_fetchone(
            "SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND read = 0",
            (user_id,)
        )
        return row["count"] if row else 0

    def mark_read(
        self,
        user_id: str,
        notification_id: int,
    ) -> bool:
        """Mark a notification as read.

        Args:
            user_id: User ID (for verification)
            notification_id: Notification ID

        Returns:
            True if marked, False if not found
        """
        self._ensure_table()
        now = time.time()
        result = self._db.execute(
            "UPDATE notifications SET read = 1, read_at = ? WHERE id = ? AND user_id = ?",
            (now, notification_id, user_id),
        )
        return result.rowcount > 0

    def mark_all_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user.

        Args:
            user_id: User ID

        Returns:
            Number of notifications marked as read
        """
        self._ensure_table()
        now = time.time()
        result = self._db.execute(
            "UPDATE notifications SET read = 1, read_at = ? WHERE user_id = ? AND read = 0",
            (now, user_id),
        )
        return result.rowcount

    def delete_notification(
        self,
        user_id: str,
        notification_id: int,
    ) -> bool:
        """Delete a notification.

        Args:
            user_id: User ID (for verification)
            notification_id: Notification ID

        Returns:
            True if deleted, False if not found
        """
        self._ensure_table()
        result = self._db.execute(
            "DELETE FROM notifications WHERE id = ? AND user_id = ?",
            (notification_id, user_id),
        )
        return result.rowcount > 0

    def delete_old_notifications(self, days: int = 30) -> int:
        """Delete notifications older than specified days.

        Args:
            days: Delete notifications older than this many days

        Returns:
            Number of notifications deleted
        """
        self._ensure_table()
        cutoff = time.time() - (days * 24 * 60 * 60)
        result = self._db.execute(
            "DELETE FROM notifications WHERE created_at < ? AND read = 1",
            (cutoff,),
        )
        return result.rowcount


# Global service instance
_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Get the global NotificationService instance."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service

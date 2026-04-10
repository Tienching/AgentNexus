# -*- coding: utf-8 -*-
"""Task broadcast helpers.

MC-038: one-to-many notification helper for task subscribers.
"""

from __future__ import annotations

from typing import Iterable, List

from .service import NotificationType, get_notification_service


def broadcast_to_recipients(
    task_id: str,
    sender: str,
    message: str,
    recipients: Iterable[str],
) -> int:
    """Send one broadcast message to all recipients.

    Returns number of notifications successfully created.
    """
    service = get_notification_service()
    delivered = 0

    title = f"Task #{task_id[:8]} broadcast"
    body = message.strip()
    if not body:
        return 0

    for raw in recipients:
        uid = (raw or "").strip()
        if not uid:
            continue
        service.notify(
            user_id=uid,
            title=title,
            body=body,
            type=NotificationType.COMMENT,
            data={"task_id": str(task_id), "sender": sender},
        )
        delivered += 1

    return delivered


def normalize_recipients(values: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for raw in values:
        uid = (raw or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        ordered.append(uid)
    return ordered

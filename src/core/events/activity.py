# -*- coding: utf-8 -*-
"""Activity stream system - real-time recording of agent, task, and system events.

Provides centralized activity logging with SQLite persistence and real-time
SSE broadcasting for UI updates.

Activity Types:
    - task_created, task_updated, task_status_changed, task_deleted
    - task_assigned, task_completed, task_comment_added
    - agent_created, agent_registered, agent_deregistered, agent_status_change
    - session_created, session_ended
    - webhook_triggered, webhook_failed

Usage:
    from src.core.events.activity import log_activity, get_recent_activities

    log_activity(
        type="task_created",
        entity_type="task",
        entity_id=123,
        actor="user@example.com",
        description="Task 'Fix login bug' created"
    )
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any

import logging

from src.runtime.stores.db import get_db

logger = logging.getLogger(__name__)


class ActivityType(str, Enum):
    """Supported activity event types."""

    # Task activities
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    TASK_STATUS_CHANGED = "task_status_changed"
    TASK_DELETED = "task_deleted"
    TASK_ASSIGNED = "task_assigned"
    TASK_COMPLETED = "task_completed"
    TASK_COMMENT_ADDED = "task_comment_added"

    # Agent activities
    AGENT_CREATED = "agent_created"
    AGENT_REGISTERED = "agent_registered"
    AGENT_DEREGISTERED = "agent_deregistered"
    AGENT_STATUS_CHANGE = "agent_status_change"
    AGENT_HEARTBEAT = "agent_heartbeat"

    # Session activities
    SESSION_CREATED = "session_created"
    SESSION_ENDED = "session_ended"

    # System activities
    SYSTEM_STARTUP = "system_startup"
    SYSTEM_SHUTDOWN = "system_shutdown"

    # Integration activities
    WEBHOOK_TRIGGERED = "webhook_triggered"
    WEBHOOK_FAILED = "webhook_failed"
    PIPELINE_STARTED = "pipeline_started"
    PIPELINE_COMPLETED = "pipeline_completed"

    # Generic
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Activity:
    """Activity event record matching Mission Control's Activity interface."""

    type: str
    entity_type: str
    entity_id: int
    actor: str
    description: str
    data: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=lambda: time.time())
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        if d["data"] is not None:
            d["data"] = json.dumps(d["data"])
        return d

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Activity":
        """Create Activity from a database row."""
        data = row.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                data = None

        return cls(
            id=row.get("id"),
            type=row["type"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            actor=row["actor"],
            description=row["description"],
            data=data,
            created_at=row.get("created_at", time.time()),
        )


def log_activity(
    type: str,
    entity_type: str,
    entity_id: int,
    actor: str,
    description: str,
    data: Optional[Dict[str, Any]] = None,
) -> Optional[Activity]:
    """Log an activity event to the database.

    Args:
        type: Activity type (e.g., "task_created", "agent_status_change")
        entity_type: Type of entity (e.g., "task", "agent", "session")
        entity_id: ID of the entity
        actor: Who performed the action (e.g., "user@example.com", "agent:backend-dev")
        description: Human-readable description
        data: Optional additional context as dict

    Returns:
        The created Activity record, or None if logging failed
    """
    db = get_db()

    activity = Activity(
        type=type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        description=description,
        data=data,
    )

    try:
        with db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO activities (type, entity_type, entity_id, actor, description, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    activity.type,
                    activity.entity_type,
                    activity.entity_id,
                    activity.actor,
                    activity.description,
                    json.dumps(activity.data) if activity.data else None,
                    activity.created_at,
                ),
            )
            activity.id = cursor.lastrowid

        logger.debug(f"Activity logged: {type} on {entity_type}:{entity_id} by {actor}")

        # Broadcast via SSE if event bus is available
        _broadcast_activity(activity)

        return activity

    except Exception as e:
        logger.error(f"Failed to log activity: {e}")
        return None


def get_recent_activities(
    limit: int = 50,
    entity_type: Optional[str] = None,
    activity_type: Optional[str] = None,
) -> List[Activity]:
    """Fetch recent activity records.

    Args:
        limit: Maximum number of activities to return (default 50, max 1000)
        entity_type: Filter by entity type (e.g., "task", "agent")
        activity_type: Filter by activity type (e.g., "task_created")

    Returns:
        List of Activity records, newest first
    """
    db = get_db()
    limit = min(limit, 1000)

    sql = "SELECT * FROM activities"
    params: List[Any] = []
    conditions: List[str] = []

    if entity_type:
        conditions.append("entity_type = ?")
        params.append(entity_type)

    if activity_type:
        conditions.append("type = ?")
        params.append(activity_type)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    try:
        rows = db.execute_fetchall(sql, tuple(params))
        activities = [Activity.from_row(row) for row in rows]
        return activities
    except Exception as e:
        logger.error(f"Failed to fetch activities: {e}")
        return []


def get_activities_for_entity(
    entity_type: str,
    entity_id: int,
    limit: int = 20,
) -> List[Activity]:
    """Get activities for a specific entity.

    Args:
        entity_type: Type of entity (e.g., "task", "agent")
        entity_id: ID of the entity
        limit: Maximum number of activities to return

    Returns:
        List of Activity records for the entity, newest first
    """
    db = get_db()
    limit = min(limit, 100)

    try:
        rows = db.execute_fetchall(
            """
            SELECT * FROM activities
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (entity_type, entity_id, limit),
        )
        return [Activity.from_row(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch activities for entity: {e}")
        return []


def _broadcast_activity(activity: Activity) -> None:
    """Broadcast activity via SSE event bus.

    This is a no-op if no event bus is configured. The SSE endpoint
    will poll or subscribe to receive activity updates.
    """
    # Import here to avoid circular dependency
    try:
        from src.server.services import get_event_bus

        event_bus = get_event_bus()
        if event_bus:
            event_bus.broadcast(
                "activity.created",
                {
                    "id": activity.id,
                    "type": activity.type,
                    "entity_type": activity.entity_type,
                    "entity_id": activity.entity_id,
                    "actor": activity.actor,
                    "description": activity.description,
                    "data": activity.data,
                    "created_at": activity.created_at,
                },
            )
    except (ImportError, Exception):
        # Event bus not available - activity is still persisted
        pass

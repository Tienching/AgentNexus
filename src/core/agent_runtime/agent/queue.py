# -*- coding: utf-8 -*-
"""Agent task queue and pull-based assignment.

MC-002: Implements task queue polling with priority ordering and atomic claims.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.runtime.models.task_models import Task, TaskStatus
from src.runtime.stores.db import Database, get_db
from src.runtime.stores.task_storage import _row_to_task


class QueueReason(str, Enum):
    CONTINUE_CURRENT = "continue_current"
    ASSIGNED = "assigned"
    AT_CAPACITY = "at_capacity"
    NO_TASKS_AVAILABLE = "no_tasks_available"


@dataclass
class QueuePullResult:
    task: Optional[Task]
    reason: QueueReason
    agent: str
    timestamp: float


class AgentTaskQueue:
    """Pull-based queue for assigning tasks to agents."""

    def __init__(self, exec_user: str = "default", db: Optional[Database] = None):
        self.exec_user = exec_user
        self._db = db or get_db()

    @staticmethod
    def _priority_rank_sql() -> str:
        return (
            "CASE priority "
            "WHEN 'critical' THEN 0 "
            "WHEN 'project' THEN 0 "
            "WHEN 'high' THEN 1 "
            "WHEN 'serious' THEN 1 "
            "WHEN 'medium' THEN 2 "
            "WHEN 'thought' THEN 2 "
            "WHEN 'low' THEN 3 "
            "ELSE 4 END"
        )

    def pull_next_task(self, agent_name: str, max_capacity: int = 1) -> QueuePullResult:
        """Poll next task for an agent with atomic claim.

        Behavior:
        1. Return currently running task for the agent if exists.
        2. Respect max running capacity.
        3. Atomically claim highest-priority pending task.
        """
        now = time.time()
        max_capacity = max(1, min(int(max_capacity), 20))

        # Keep current/capacity checks in the same write transaction as the
        # claim so concurrent pollers cannot both observe spare capacity.
        with self._db.transaction() as conn:
            current = conn.execute(
                """
                SELECT * FROM tasks
                WHERE exec_user = ? AND assigned_to = ? AND status = ?
                ORDER BY started_at DESC, created_at DESC
                LIMIT 1
                """,
                (self.exec_user, agent_name, TaskStatus.RUNNING.value),
            ).fetchone()
            if current:
                return QueuePullResult(
                    task=_row_to_task(dict(current)),
                    reason=QueueReason.CONTINUE_CURRENT,
                    agent=agent_name,
                    timestamp=now,
                )

            running_count = conn.execute(
                """
                SELECT COUNT(*) AS c FROM tasks
                WHERE exec_user = ? AND assigned_to = ? AND status = ?
                """,
                (self.exec_user, agent_name, TaskStatus.RUNNING.value),
            ).fetchone()
            if running_count and int(running_count["c"] or 0) >= max_capacity:
                return QueuePullResult(
                    task=None,
                    reason=QueueReason.AT_CAPACITY,
                    agent=agent_name,
                    timestamp=now,
                )

            row = conn.execute(
                f"""
                UPDATE tasks
                SET status = ?,
                    assigned_to = ?,
                    started_at = COALESCE(started_at, ?),
                    attempt_count = COALESCE(attempt_count, 0) + 1,
                    runtime_status = 'running',
                    runtime_orphaned = 0,
                    runtime_orphaned_at = NULL,
                    runtime_last_heartbeat = ?
                WHERE id = (
                    SELECT id FROM tasks
                    WHERE exec_user = ?
                      AND status = ?
                      AND (assigned_to IS NULL OR assigned_to = '' OR assigned_to = ?)
                    ORDER BY {self._priority_rank_sql()} ASC,
                             CASE WHEN due_date IS NULL THEN 1 ELSE 0 END ASC,
                             due_date ASC,
                             created_at ASC
                    LIMIT 1
                )
                RETURNING *
                """,
                (
                    TaskStatus.RUNNING.value,
                    agent_name,
                    now,
                    now,
                    self.exec_user,
                    TaskStatus.PENDING.value,
                    agent_name,
                ),
            ).fetchone()

        if row:
            return QueuePullResult(
                task=_row_to_task(dict(row)),
                reason=QueueReason.ASSIGNED,
                agent=agent_name,
                timestamp=now,
            )

        return QueuePullResult(
            task=None,
            reason=QueueReason.NO_TASKS_AVAILABLE,
            agent=agent_name,
            timestamp=now,
        )

    def assign_task(self, task_id: str, agent_name: str) -> bool:
        """Assign a task to an agent without starting execution."""
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET assigned_to = ?
                WHERE exec_user = ? AND id = ?
                """,
                (agent_name, self.exec_user, str(task_id)),
            )
            return cursor.rowcount > 0

    def get_agent_queue_depth(self, agent_name: str) -> int:
        """Get pending task count claimable by an agent."""
        row = self._db.execute_fetchone(
            """
            SELECT COUNT(*) AS c
            FROM tasks
            WHERE exec_user = ?
              AND status = ?
              AND (assigned_to IS NULL OR assigned_to = '' OR assigned_to = ?)
            """,
            (self.exec_user, TaskStatus.PENDING.value, agent_name),
        )
        return int(row.get("c", 0)) if row else 0

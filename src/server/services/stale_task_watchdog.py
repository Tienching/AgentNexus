# -*- coding: utf-8 -*-
"""Stale task watchdog — detects DOING tasks whose executor has gone offline.

Ported from mission-control src/lib/task-dispatch.ts requeueStaleTasks()
(commit 2d171ad). Key differences from storage.requeue_stuck_tasks():

* Uses a shorter 10-minute threshold (MC default) instead of the executor's
  wall-clock timeout (which can be hours).
* Skips tasks that are *actively tracked* in the executor's running_tasks dict
  — those are genuinely in-flight, not stale.
* Returns a structured result dict matching MC's { ok, message } shape.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Set

logger = logging.getLogger(__name__)

# 10 minutes — matches mission-control's staleThreshold (commit 2d171ad).
STALE_THRESHOLD_SECONDS: int = 10 * 60

# Maximum number of dispatch retries before permanently failing a task.
# Kept in sync with TaskQueue.MAX_DISPATCH_RETRIES (== 5).
MAX_DISPATCH_RETRIES: int = 5


def _get_executor_active_task_ids() -> Set[str]:
    """Return the set of task IDs currently executing in the local TaskExecutor.

    Returns an empty set if the executor is not running or not available —
    in which case *all* stale DOING tasks are eligible for requeue (the agent
    is effectively offline, mirroring MC's agent-status check).
    """
    try:
        from ...runtime.execution.task_executor import get_executor
        executor = get_executor()
        if executor is not None and executor.is_running:
            return set(executor._running_tasks.keys())
    except Exception:
        pass
    return set()


def requeue_stale_tasks(
    task_queue,
    stale_threshold_seconds: int = STALE_THRESHOLD_SECONDS,
    max_dispatch_retries: int = MAX_DISPATCH_RETRIES,
) -> dict:
    """Requeue DOING tasks whose executor is no longer running them.

    Equivalent to mission-control requeueStaleTasks() (commit 2d171ad):

    * Find tasks in DOING status whose started_at is older than
      ``stale_threshold_seconds`` (default 10 min).
    * Skip tasks that are actively tracked in the local executor's
      running_tasks map (those are genuinely in-flight).
    * Requeue eligible tasks as TODO with incremented attempt_count.
    * Permanently fail tasks that have reached ``max_dispatch_retries``.

    Args:
        task_queue: A TaskQueue instance whose exec_user scope to check.
        stale_threshold_seconds: Age in seconds at which a DOING task is
            considered stale (default 600 — 10 minutes).
        max_dispatch_retries: Max requeue attempts before failing permanently
            (default 5, matching MC and TaskQueue.MAX_DISPATCH_RETRIES).

    Returns:
        dict with keys ``ok`` (bool), ``requeued`` (int), ``failed`` (int),
        ``skipped`` (int), and ``message`` (str).
    """
    from ...runtime.models.task_models import TaskStatus

    active_task_ids = _get_executor_active_task_ids()

    doing_task_ids = task_queue._redis.smembers(
        task_queue._status_key(TaskStatus.DOING)
    )

    if not doing_task_ids:
        return {"ok": True, "requeued": 0, "failed": 0, "skipped": 0,
                "message": "No stale tasks found"}

    requeued = 0
    failed = 0
    skipped = 0
    now = datetime.now(timezone.utc)

    for task_id in doing_task_ids:
        # Agent still processing this task — leave it alone.
        if task_id in active_task_ids:
            skipped += 1
            continue

        task = task_queue.get_task(task_id)
        if not (task and task.started_at):
            skipped += 1
            continue

        started_at = task.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        elapsed = (now - started_at).total_seconds()
        if elapsed <= stale_threshold_seconds:
            skipped += 1
            continue

        # Task is stale and its executor slot is gone — clean up and requeue.
        eu = getattr(task, "exec_user", None)
        task_queue._redis.srem(
            task_queue._executing_key(task.workspace), task.id
        )

        new_attempts = (task.attempt_count or 0) + 1

        if new_attempts >= max_dispatch_retries:
            error_msg = (
                f"Task stuck in DOING for {elapsed:.0f}s — executor not running. "
                f"Permanently failed after {new_attempts} attempt(s)."
            )
            task.attempt_count = new_attempts
            task.error_message = error_msg
            task_queue._redis.hset(
                task_queue._task_key(task.id, eu),
                {"attempt_count": str(new_attempts), "error_message": error_msg},
            )
            task_queue._update_task_status(task, TaskStatus.FAILED)
            logger.error(
                "stale_task_watchdog: task %s permanently failed after %d attempts "
                "(%ds elapsed)",
                task_id,
                new_attempts,
                int(elapsed),
            )
            failed += 1
        else:
            error_msg = (
                f"Task requeued (attempt {new_attempts}/{max_dispatch_retries}): "
                f"was DOING for {elapsed:.0f}s with no active executor."
            )
            task.attempt_count = new_attempts
            task.error_message = error_msg
            task_queue._redis.hset(
                task_queue._task_key(task.id, eu),
                {"attempt_count": str(new_attempts), "error_message": error_msg},
            )
            task_queue._update_task_status(task, TaskStatus.TODO)
            task_queue._redis.rpush(
                task_queue._queue_key(task.workspace, eu), task.id
            )
            logger.warning(
                "stale_task_watchdog: task %s requeued (attempt %d/%d, %ds elapsed)",
                task_id,
                new_attempts,
                max_dispatch_retries,
                int(elapsed),
            )
            requeued += 1

    total = requeued + failed
    if total:
        logger.info(
            "stale_task_watchdog: requeued=%d failed=%d skipped=%d",
            requeued,
            failed,
            skipped,
        )

    message = (
        f"No stale tasks found"
        if total == 0
        else f"Requeued {requeued}, failed {failed} of {total} stale task(s)"
    )
    return {
        "ok": True,
        "requeued": requeued,
        "failed": failed,
        "skipped": skipped,
        "message": message,
    }

# -*- coding: utf-8 -*-
"""Runtime stale-task watchdog helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Set

logger = logging.getLogger(__name__)

# 10 minutes — matches mission-control's staleThreshold.
STALE_THRESHOLD_SECONDS: int = 10 * 60

# Maximum number of dispatch retries before permanently failing a task.
MAX_DISPATCH_RETRIES: int = 5


def _get_executor_active_task_ids() -> Set[str]:
    """Return the set of task IDs currently executing in the local TaskExecutor."""
    try:
        from .task_executor import get_executor

        executor = get_executor()
        if executor is not None and executor.is_running:
            return executor.get_active_task_ids()
    except Exception:
        pass
    return set()


def requeue_stale_tasks(
    task_queue,
    stale_threshold_seconds: int = STALE_THRESHOLD_SECONDS,
    max_dispatch_retries: int = MAX_DISPATCH_RETRIES,
) -> dict:
    """Requeue DOING tasks whose executor is no longer running them."""
    active_task_ids = _get_executor_active_task_ids()
    doing_tasks = task_queue.get_running_tasks()

    if not doing_tasks:
        return {
            "ok": True,
            "requeued": 0,
            "failed": 0,
            "skipped": 0,
            "message": "No stale tasks found",
        }

    requeued = 0
    failed = 0
    skipped = 0
    now = datetime.now(timezone.utc)

    for task in doing_tasks:
        task_id = task.id

        if task_id in active_task_ids:
            skipped += 1
            continue

        if not task.started_at:
            skipped += 1
            continue

        started_at = task.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        elapsed = (now - started_at).total_seconds()
        if elapsed <= stale_threshold_seconds:
            skipped += 1
            continue

        new_attempts = (task.attempt_count or 0) + 1

        if new_attempts >= max_dispatch_retries:
            error_msg = (
                f"Task stuck in DOING for {elapsed:.0f}s — executor not running. "
                f"Permanently failed after {new_attempts} attempt(s)."
            )
            task_queue.fail_task(
                task.id,
                attempt_count=new_attempts,
                error_message=error_msg,
            )
            logger.error(
                "stale_task_watchdog: task %s permanently failed after %d attempts (%ds elapsed)",
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
            task_queue.requeue_task(
                task.id,
                attempt_count=new_attempts,
                error_message=error_msg,
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
        "No stale tasks found"
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

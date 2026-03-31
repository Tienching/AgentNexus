# -*- coding: utf-8 -*-
"""Task scheduler for cron-based periodic task creation.

Polls for due schedules and spawns child tasks via TaskQueue.add_task().
Runs as a standalone background service alongside TaskExecutor.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from enum import Enum

from ..models.schedule_models import Schedule, ScheduleStatus
from ..models.task_models import TaskPriority
from ..stores.schedule_storage import ScheduleStorage
from ..stores.task_storage import TaskQueue
from ...server.services.stale_task_watchdog import (
    requeue_stale_tasks,
    STALE_THRESHOLD_SECONDS,
)

logger = logging.getLogger(__name__)

# How often (seconds) to run the stale-task watchdog.
# Matches mission-control scheduler tick (TICK_MS = 60_000 → 60s, commit 2d171ad).
_WATCHDOG_INTERVAL_SECONDS: int = 60
# Delay before the first watchdog check after startup (25s, matching MC).
_WATCHDOG_INITIAL_DELAY_SECONDS: int = 25


def _extract_loop_config(context: Dict[str, Any]) -> tuple[bool, int, Optional[list[str]]]:
    """Extract Ralph Loop settings from schedule context while keeping task context clean."""
    loop_enabled = bool(context.pop("loop_enabled", False))
    loop_max_iterations = int(context.pop("loop_max_iterations", 1) or 1)
    loop_keywords = context.pop("loop_keywords", None)
    return loop_enabled, loop_max_iterations, list(loop_keywords) if loop_keywords else None


class SchedulerState(str, Enum):
    """Scheduler lifecycle states"""
    STOPPED = "stopped"
    RUNNING = "running"
    STOPPING = "stopping"


class TaskScheduler:
    """Background service that polls for due schedules and creates child tasks.

    Architecture:
    - Runs its own asyncio polling loop (separate from TaskExecutor)
    - Checks ScheduleStorage.get_due_schedules() every poll_interval seconds
    - For each due schedule, calls TaskQueue.add_task() with the schedule's template
    - Records the run via ScheduleStorage.record_run()
    """

    def __init__(
        self,
        schedule_storage: ScheduleStorage,
        task_queue: TaskQueue,
        poll_interval: float = 15.0,
    ):
        self._schedule_storage = schedule_storage
        self._task_queue = task_queue
        self._poll_interval = poll_interval
        self._state = SchedulerState.STOPPED
        self._main_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Stale-task watchdog state (ported from MC commit 2d171ad).
        self._watchdog_last_run: Optional[float] = None
        # First watchdog check runs _WATCHDOG_INITIAL_DELAY_SECONDS after start.
        self._watchdog_next_run: Optional[float] = None

        logger.info(f"TaskScheduler initialized (poll_interval={poll_interval}s)")

    @property
    def state(self) -> SchedulerState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == SchedulerState.RUNNING

    @property
    def schedule_storage(self) -> ScheduleStorage:
        """Expose schedule storage for API layer access."""
        return self._schedule_storage

    async def start(self) -> None:
        """Start the scheduler background loop."""
        if self._state != SchedulerState.STOPPED:
            logger.warning(f"Scheduler already in state {self._state}")
            return

        self._shutdown_event.clear()
        self._main_task = asyncio.create_task(self._main_loop())
        self._state = SchedulerState.RUNNING
        # Schedule the first watchdog check 25 s after startup.
        import time as _time
        self._watchdog_next_run = _time.monotonic() + _WATCHDOG_INITIAL_DELAY_SECONDS
        logger.info("TaskScheduler started")

    async def stop(self, timeout: float = 10.0) -> None:
        """Graceful shutdown."""
        if self._state != SchedulerState.RUNNING:
            return

        self._state = SchedulerState.STOPPING
        self._shutdown_event.set()

        if self._main_task:
            try:
                await asyncio.wait_for(self._main_task, timeout=timeout)
            except asyncio.TimeoutError:
                self._main_task.cancel()
                try:
                    await self._main_task
                except asyncio.CancelledError:
                    pass

        self._state = SchedulerState.STOPPED
        logger.info("TaskScheduler stopped")

    async def _main_loop(self) -> None:
        """Main polling loop."""
        import time as _time
        logger.info("Scheduler main loop started")

        while not self._shutdown_event.is_set():
            try:
                await self._check_and_fire()
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}", exc_info=True)

            # Run stale-task watchdog when due.
            try:
                now = _time.monotonic()
                if (
                    self._watchdog_next_run is not None
                    and now >= self._watchdog_next_run
                ):
                    await self._run_watchdog()
                    self._watchdog_last_run = now
                    self._watchdog_next_run = now + _WATCHDOG_INTERVAL_SECONDS
            except Exception as e:
                logger.error(f"Stale-task watchdog error: {e}", exc_info=True)

            # Wait for poll_interval or shutdown
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._poll_interval,
                )
            except asyncio.TimeoutError:
                pass

        logger.info("Scheduler main loop exited")

    async def _check_and_fire(self) -> None:
        """Check for due schedules and spawn child tasks."""
        due_schedules = self._schedule_storage.get_due_schedules()

        for schedule in due_schedules:
            try:
                await self._fire_schedule(schedule)
            except Exception as e:
                logger.error(f"Failed to fire schedule {schedule.id}: {e}", exc_info=True)

    async def _run_watchdog(self) -> None:
        """Run the stale-task watchdog — requeue DOING tasks with no active executor.

        Ported from mission-control requeueStaleTasks() (commit 2d171ad).
        Fires every _WATCHDOG_INTERVAL_SECONDS (60s), first run at 25s after startup.
        """
        result = requeue_stale_tasks(
            self._task_queue,
            stale_threshold_seconds=STALE_THRESHOLD_SECONDS,
        )
        if result.get("requeued", 0) or result.get("failed", 0):
            logger.info("stale_task_watchdog: %s", result["message"])

    async def _fire_schedule(self, schedule: Schedule) -> None:
        """Spawn a child task from the schedule template."""
        # Build context linking back to the schedule
        context = dict(schedule.context or {})
        context["schedule_id"] = schedule.id
        context["schedule_name"] = schedule.name
        context["schedule_run_number"] = schedule.run_count + 1

        loop_enabled, loop_max_iterations, loop_keywords = _extract_loop_config(context)

        # Use TaskQueue.add_task() -- same path as regular task creation
        task = self._task_queue.add_task(
            description=schedule.description,
            priority=TaskPriority.GENERATED,
            context=context,
            project_id=schedule.project_id,
            project_name=schedule.project_name,
            workspace=schedule.workspace,
            provider=schedule.provider,
            alias=schedule.alias,
            model=schedule.model,
            exec_user=schedule.exec_user,
            loop_enabled=loop_enabled,
            loop_max_iterations=loop_max_iterations,
            loop_keywords=loop_keywords,
        )

        # Set schedule_id on the task for lineage tracking
        try:
            task.schedule_id = schedule.id
            self._task_queue.update_task(task)
        except Exception:
            pass

        # Record the run in schedule storage
        self._schedule_storage.record_run(schedule, task.id)

        logger.info(
            f"Schedule {schedule.id} ({schedule.name!r}) fired: "
            f"created task {task.id} (run #{schedule.run_count})"
        )

    async def trigger_schedule(self, schedule_id: str) -> Optional[str]:
        """Manually trigger a schedule, bypassing cron timing.

        Returns the created task ID, or None if schedule not found.
        """
        schedule = self._schedule_storage.get_schedule(schedule_id)
        if not schedule:
            return None

        status_val = schedule.status if isinstance(schedule.status, str) else schedule.status.value
        if status_val == ScheduleStatus.CANCELLED.value:
            raise ValueError("Cannot trigger a cancelled schedule")

        await self._fire_schedule(schedule)
        return schedule.last_task_id

    async def get_status(self) -> Dict[str, Any]:
        """Return scheduler status for the API."""
        return {
            "state": self._state.value,
            "poll_interval": self._poll_interval,
            "watchdog": {
                "interval_seconds": _WATCHDOG_INTERVAL_SECONDS,
                "stale_threshold_seconds": STALE_THRESHOLD_SECONDS,
                "last_run": self._watchdog_last_run,
                "next_run": self._watchdog_next_run,
            },
        }


# ---- Global singleton ----

_scheduler: Optional[TaskScheduler] = None


def get_scheduler() -> Optional[TaskScheduler]:
    """Get global scheduler instance."""
    return _scheduler


def set_scheduler(scheduler: TaskScheduler) -> None:
    """Set global scheduler instance."""
    global _scheduler
    _scheduler = scheduler


async def create_and_start_scheduler(
    schedule_storage: ScheduleStorage,
    task_queue: TaskQueue,
    poll_interval: float = 15.0,
) -> TaskScheduler:
    """Create and start a task scheduler.

    Returns:
        Started TaskScheduler instance.
    """
    scheduler = TaskScheduler(schedule_storage, task_queue, poll_interval)
    await scheduler.start()
    set_scheduler(scheduler)
    return scheduler

# -*- coding: utf-8 -*-
"""Redis schedule storage for cron-based periodic tasks.

Provides ScheduleStorage class for managing Schedule definitions in Redis.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import List, Optional, Dict, Any, Tuple

from ..models.schedule_models import Schedule, ScheduleStatus, ScheduleKind
from .redis_client import get_redis_client, RedisClient

logger = logging.getLogger(__name__)


class ScheduleStorage:
    """Schedule storage manager with Redis backend.

    Redis key structure:
    - schedule:{exec_user}:{schedule_id}                - Hash: schedule data
    - schedules:{exec_user}:all                         - Sorted set (score = created_at)
    - schedules:{exec_user}:by_status:{status}          - Set of schedule IDs
    - schedules:{exec_user}:active_next_runs            - Sorted set (score = next_run_at timestamp)
    - schedule:{exec_user}:{schedule_id}:history        - List of spawned task IDs (newest first)
    """

    def __init__(
        self,
        exec_user: str = "default",
        redis_client: Optional[RedisClient] = None,
    ):
        self.exec_user = exec_user
        self._redis: RedisClient = redis_client or get_redis_client()
        logger.info(f"ScheduleStorage initialized for exec_user: {exec_user}")

    # ---- Key helpers ----

    def _schedule_key(self, schedule_id: str) -> str:
        return f"schedule:{self.exec_user}:{schedule_id}"

    def _all_schedules_key(self) -> str:
        return f"schedules:{self.exec_user}:all"

    def _status_key(self, status: ScheduleStatus) -> str:
        return f"schedules:{self.exec_user}:by_status:{status.value}"

    def _active_next_runs_key(self) -> str:
        return f"schedules:{self.exec_user}:active_next_runs"

    def _history_key(self, schedule_id: str) -> str:
        return f"schedule:{self.exec_user}:{schedule_id}:history"

    # ---- CRUD ----

    def add_schedule(
        self,
        name: str,
        description: str,
        cron_expression: Optional[str] = None,
        run_at: Optional[datetime] = None,
        timezone_str: str = "UTC",
        provider: str = "claude",
        alias: Optional[str] = None,
        model: Optional[str] = None,
        workspace: Optional[str] = None,
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
        exec_user: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        max_runs: Optional[int] = None,
        created_by: Optional[str] = None,
        schedule_kind: str = "task",
        evolution_phase: Optional[str] = None,
    ) -> Schedule:
        """Create a new schedule definition (recurring cron or one-time run_at)."""
        schedule = Schedule(
            name=name,
            cron_expression=cron_expression,
            run_at=run_at,
            timezone=timezone_str,
            description=description,
            provider=provider,
            alias=alias,
            model=model,
            workspace=workspace,
            project_id=project_id,
            project_name=project_name,
            exec_user=exec_user or self.exec_user,
            context=context,
            max_runs=max_runs,
            created_by=created_by,
            schedule_kind=ScheduleKind(schedule_kind),
            evolution_phase=evolution_phase,
        )

        # Pre-compute next run
        schedule.next_run_at = schedule.compute_next_run()

        # Store schedule data
        self._redis.hset(self._schedule_key(schedule.id), schedule.to_redis_hash())

        # Add to all schedules sorted set
        timestamp = schedule.created_at.timestamp()
        self._redis.zadd(self._all_schedules_key(), {schedule.id: timestamp})

        # Add to status index
        self._redis.sadd(self._status_key(ScheduleStatus.ACTIVE), schedule.id)

        # Add to active_next_runs sorted set
        if schedule.next_run_at:
            self._redis.zadd(
                self._active_next_runs_key(),
                {schedule.id: schedule.next_run_at.timestamp()},
            )

        trigger_info = f"cron={cron_expression!r}" if cron_expression else f"run_at={run_at!r}"
        logger.info(
            f"Added schedule {schedule.id}: {name!r} "
            f"{trigger_info} next_run={schedule.next_run_at}"
        )
        return schedule

    def get_schedule(self, schedule_id: str) -> Optional[Schedule]:
        """Get schedule by ID."""
        data = self._redis.hgetall(self._schedule_key(schedule_id))
        if not data:
            return None
        try:
            return Schedule.from_redis_hash(data)
        except Exception as e:
            logger.error(f"Failed to parse schedule {schedule_id}: {e}")
            return None

    def update_schedule(self, schedule: Schedule) -> bool:
        """Persist updated schedule fields to Redis.

        Does NOT change status/index membership -- use pause/resume/cancel for that.
        """
        if not self._redis.exists(self._schedule_key(schedule.id)):
            return False

        schedule.updated_at = datetime.now(timezone.utc)
        self._redis.hset(self._schedule_key(schedule.id), schedule.to_redis_hash())

        # Update next_run_at in sorted set if schedule is active
        status_val = schedule.status if isinstance(schedule.status, str) else schedule.status.value
        if status_val == ScheduleStatus.ACTIVE.value and schedule.next_run_at:
            self._redis.zadd(
                self._active_next_runs_key(),
                {schedule.id: schedule.next_run_at.timestamp()},
            )

        return True

    def delete_schedule(self, schedule_id: str) -> bool:
        """Hard delete a schedule and all related indexes."""
        schedule = self.get_schedule(schedule_id)

        # Remove from status index
        for st in ScheduleStatus:
            try:
                self._redis.srem(self._status_key(st), schedule_id)
            except Exception:
                pass

        # Remove from active_next_runs
        try:
            self._redis.zrem(self._active_next_runs_key(), schedule_id)
        except Exception:
            pass

        # Remove from all schedules zset
        try:
            self._redis.zrem(self._all_schedules_key(), schedule_id)
        except Exception:
            pass

        # Remove history list
        try:
            self._redis.delete(self._history_key(schedule_id))
        except Exception:
            pass

        # Remove schedule hash
        try:
            self._redis.delete(self._schedule_key(schedule_id))
        except Exception:
            pass

        logger.info(f"Hard deleted schedule {schedule_id}")
        return True

    # ---- Status transitions ----

    def _update_status(self, schedule: Schedule, new_status: ScheduleStatus) -> None:
        """Update schedule status and related indexes."""
        old_status_val = schedule.status if isinstance(schedule.status, str) else schedule.status.value
        try:
            old_status = ScheduleStatus(old_status_val)
        except ValueError:
            old_status = ScheduleStatus.ACTIVE

        # Remove from old status set
        self._redis.srem(self._status_key(old_status), schedule.id)
        # Add to new status set
        self._redis.sadd(self._status_key(new_status), schedule.id)

        schedule.status = new_status
        now = datetime.now(timezone.utc)
        schedule.updated_at = now

        if new_status == ScheduleStatus.PAUSED:
            schedule.paused_at = now
            # Remove from active_next_runs (paused schedules don't fire)
            self._redis.zrem(self._active_next_runs_key(), schedule.id)
        elif new_status == ScheduleStatus.CANCELLED:
            schedule.cancelled_at = now
            self._redis.zrem(self._active_next_runs_key(), schedule.id)
        elif new_status == ScheduleStatus.ACTIVE:
            schedule.paused_at = None
            # Re-compute and add to active_next_runs
            schedule.next_run_at = schedule.compute_next_run()
            if schedule.next_run_at:
                self._redis.zadd(
                    self._active_next_runs_key(),
                    {schedule.id: schedule.next_run_at.timestamp()},
                )

        self._redis.hset(self._schedule_key(schedule.id), schedule.to_redis_hash())

    def pause_schedule(self, schedule_id: str) -> Optional[Schedule]:
        """Pause an active schedule."""
        schedule = self.get_schedule(schedule_id)
        if not schedule:
            return None
        status_val = schedule.status if isinstance(schedule.status, str) else schedule.status.value
        if status_val != ScheduleStatus.ACTIVE.value:
            return schedule
        self._update_status(schedule, ScheduleStatus.PAUSED)
        logger.info(f"Schedule {schedule_id} paused")
        return schedule

    def resume_schedule(self, schedule_id: str) -> Optional[Schedule]:
        """Resume a paused schedule."""
        schedule = self.get_schedule(schedule_id)
        if not schedule:
            return None
        status_val = schedule.status if isinstance(schedule.status, str) else schedule.status.value
        if status_val != ScheduleStatus.PAUSED.value:
            return schedule
        self._update_status(schedule, ScheduleStatus.ACTIVE)
        logger.info(f"Schedule {schedule_id} resumed")
        return schedule

    def cancel_schedule(self, schedule_id: str) -> Optional[Schedule]:
        """Permanently cancel a schedule."""
        schedule = self.get_schedule(schedule_id)
        if not schedule:
            return None
        status_val = schedule.status if isinstance(schedule.status, str) else schedule.status.value
        if status_val == ScheduleStatus.CANCELLED.value:
            return schedule
        self._update_status(schedule, ScheduleStatus.CANCELLED)
        logger.info(f"Schedule {schedule_id} cancelled")
        return schedule

    # ---- Scheduler engine support ----

    def get_due_schedules(self, now: Optional[datetime] = None) -> List[Schedule]:
        """Get all active schedules whose next_run_at <= now.

        Uses ZRANGEBYSCORE on the active_next_runs sorted set for efficiency.
        """
        now = now or datetime.now(timezone.utc)
        now_ts = now.timestamp()

        schedule_ids = self._redis.zrangebyscore(
            self._active_next_runs_key(), "-inf", str(now_ts)
        )

        schedules = []
        for sid in schedule_ids:
            schedule = self.get_schedule(sid)
            if schedule:
                status_val = schedule.status if isinstance(schedule.status, str) else schedule.status.value
                if status_val == ScheduleStatus.ACTIVE.value:
                    schedules.append(schedule)
        return schedules

    def record_run(self, schedule: Schedule, task_id: str) -> None:
        """Record that the schedule fired and created a child task.

        Updates:
        1. Increments run_count
        2. Sets last_run_at = now
        3. Sets last_task_id = task_id
        4. Computes next_run_at
        5. If max_runs reached, auto-cancels
        6. Updates active_next_runs sorted set
        7. Appends task_id to history list
        """
        now = datetime.now(timezone.utc)

        schedule.run_count += 1
        schedule.last_run_at = now
        schedule.last_task_id = task_id
        schedule.updated_at = now

        # Check max_runs limit
        if schedule.max_runs and schedule.run_count >= schedule.max_runs:
            logger.info(
                f"Schedule {schedule.id} reached max_runs={schedule.max_runs}, auto-cancelling"
            )
            self._update_status(schedule, ScheduleStatus.CANCELLED)
        else:
            # Compute next run
            schedule.next_run_at = schedule.compute_next_run(base_time=now)
            if schedule.next_run_at:
                self._redis.zadd(
                    self._active_next_runs_key(),
                    {schedule.id: schedule.next_run_at.timestamp()},
                )
            # Persist
            self._redis.hset(self._schedule_key(schedule.id), schedule.to_redis_hash())

        # Append to history (newest first, capped)
        self._redis.lpush(self._history_key(schedule.id), task_id)
        self._redis.ltrim(self._history_key(schedule.id), 0, 99)  # Keep last 100

    # ---- Listing ----

    def list_schedules(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ) -> Tuple[List[Schedule], int]:
        """List schedules with pagination and optional status filter."""
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20

        all_ids = self._redis.zrange(self._all_schedules_key(), 0, -1)
        all_ids = list(reversed(all_ids))  # Most recent first

        status_norm = status.lower().strip() if status else None

        filtered: List[Schedule] = []
        for sid in all_ids:
            schedule = self.get_schedule(sid)
            if not schedule:
                continue
            if status_norm:
                s_val = schedule.status if isinstance(schedule.status, str) else schedule.status.value
                if s_val != status_norm:
                    continue
            filtered.append(schedule)

        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        return filtered[start:end], total

    def get_schedule_task_history(self, schedule_id: str, limit: int = 20) -> List[str]:
        """Return recent task IDs spawned by this schedule."""
        return self._redis.lrange(self._history_key(schedule_id), 0, limit - 1)

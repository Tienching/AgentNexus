# -*- coding: utf-8 -*-
"""SQLite schedule storage for cron-based periodic tasks.

Provides ScheduleStorage class for managing Schedule definitions in SQLite.
Replaces the multi-key Redis structure (1 hash + 3 sorted sets + 2 sets + 1 list
per schedule) with a single `schedules` table + `schedule_history` table.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
from typing import List, Optional, Dict, Any, Tuple

from ..models.schedule_models import Schedule, ScheduleStatus, ScheduleKind, ScheduleDurabilityMode
from .db import Database, get_db

logger = logging.getLogger(__name__)


def _dt_to_ts(dt: Optional[datetime]) -> Optional[float]:
    """Convert datetime to Unix timestamp, None-safe."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _ts_to_dt(ts: Optional[float]) -> Optional[datetime]:
    """Convert Unix timestamp to UTC datetime, None-safe."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _schedule_to_row(s: Schedule, exec_user: str) -> dict:
    """Convert Schedule model to a dict suitable for SQLite INSERT/UPDATE."""
    return {
        "id": s.id,
        "exec_user": exec_user,
        "name": s.name,
        "description": s.description,
        "cron_expression": s.cron_expression,
        "run_at": _dt_to_ts(s.run_at),
        "timezone_str": s.timezone,
        "status": s.status if isinstance(s.status, str) else s.status.value,
        "schedule_kind": s.schedule_kind if isinstance(s.schedule_kind, str) else s.schedule_kind.value,
        "evolution_phase": s.evolution_phase,
        "provider": s.provider,
        "alias": s.alias,
        "model": s.model,
        "workspace": s.workspace,
        "project_id": s.project_id,
        "project_name": s.project_name,
        "context_json": json.dumps(s.context) if s.context else None,
        "max_runs": s.max_runs,
        "run_count": s.run_count,
        "durability_mode": s.durability_mode if isinstance(s.durability_mode, str) else s.durability_mode.value,
        "session_id": s.session_id,
        "expires_at": _dt_to_ts(s.expires_at),
        "jitter_seconds": s.jitter_seconds,
        "next_run_at": _dt_to_ts(s.next_run_at),
        "last_run_at": _dt_to_ts(s.last_run_at),
        "last_task_id": s.last_task_id,
        "created_at": _dt_to_ts(s.created_at),
        "updated_at": _dt_to_ts(s.updated_at),
        "paused_at": _dt_to_ts(s.paused_at),
        "cancelled_at": _dt_to_ts(s.cancelled_at),
        "created_by": s.created_by,
    }


def _row_to_schedule(row: dict) -> Schedule:
    """Convert a SQLite row dict back to a Schedule model."""
    return Schedule(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        cron_expression=row.get("cron_expression"),
        run_at=_ts_to_dt(row.get("run_at")),
        timezone=row.get("timezone_str", "UTC"),
        status=ScheduleStatus(row.get("status", "active")),
        schedule_kind=ScheduleKind(row.get("schedule_kind", "task")),
        evolution_phase=row.get("evolution_phase"),
        provider=row.get("provider", "claude"),
        alias=row.get("alias"),
        model=row.get("model"),
        workspace=row.get("workspace"),
        project_id=row.get("project_id"),
        project_name=row.get("project_name"),
        exec_user=row.get("exec_user"),
        context=json.loads(row["context_json"]) if row.get("context_json") else None,
        max_runs=row.get("max_runs"),
        run_count=row.get("run_count", 0),
        durability_mode=ScheduleDurabilityMode(row.get("durability_mode") or "durable"),
        session_id=row.get("session_id"),
        expires_at=_ts_to_dt(row.get("expires_at")),
        jitter_seconds=int(row.get("jitter_seconds") or 0),
        next_run_at=_ts_to_dt(row.get("next_run_at")),
        last_run_at=_ts_to_dt(row.get("last_run_at")),
        last_task_id=row.get("last_task_id"),
        created_at=_ts_to_dt(row.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_ts_to_dt(row.get("updated_at")),
        paused_at=_ts_to_dt(row.get("paused_at")),
        cancelled_at=_ts_to_dt(row.get("cancelled_at")),
        created_by=row.get("created_by"),
    )


_SCHEDULE_FIELDS = list(_schedule_to_row(Schedule(name="__schema__", description="", cron_expression="* * * * *"), "x").keys())
_SCHEDULE_COLUMNS = ", ".join(_SCHEDULE_FIELDS)
_SCHEDULE_PLACEHOLDERS = ", ".join(["?"] * len(_SCHEDULE_FIELDS))


class ScheduleStorage:
    """Schedule storage manager with SQLite backend."""

    def __init__(
        self,
        exec_user: str = "default",
        db: Optional[Database] = None,
    ):
        self.exec_user = exec_user
        self._db = db or get_db()
        logger.info(f"ScheduleStorage initialized for exec_user: {exec_user}")

    @staticmethod
    def _compute_deterministic_jitter_seconds(schedule_id: str, run_count: int, jitter_seconds: int) -> int:
        if jitter_seconds <= 0:
            return 0
        seed = f"{schedule_id}:{run_count}".encode("utf-8")
        digest = hashlib.sha256(seed).hexdigest()
        value = int(digest[:8], 16)
        return (value % (2 * jitter_seconds + 1)) - jitter_seconds

    def _session_exists(self, session_id: Optional[str]) -> bool:
        if not session_id:
            return False
        row = self._db.execute_fetchone("SELECT 1 FROM sessions WHERE id = ?", (session_id,))
        return bool(row)

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
        durability_mode: str = "durable",
        session_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        jitter_seconds: int = 0,
    ) -> Schedule:
        """Create a new schedule definition (recurring cron or one-time run_at)."""
        eu = exec_user or self.exec_user
        expires_at = None
        if ttl_seconds and ttl_seconds > 0:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(ttl_seconds))

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
            exec_user=eu,
            context=context,
            max_runs=max_runs,
            created_by=created_by,
            schedule_kind=ScheduleKind(schedule_kind),
            evolution_phase=evolution_phase,
            durability_mode=ScheduleDurabilityMode(durability_mode),
            session_id=session_id,
            expires_at=expires_at,
            jitter_seconds=max(0, int(jitter_seconds or 0)),
        )

        if schedule.durability_mode == ScheduleDurabilityMode.SESSION_ONLY.value and not self._session_exists(schedule.session_id):
            raise ValueError(f"session_id not found for session-only schedule: {schedule.session_id}")

        # Pre-compute next run
        schedule.next_run_at = schedule.compute_next_run()

        row = _schedule_to_row(schedule, eu)
        values = [row[k] for k in _SCHEDULE_FIELDS]

        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO schedules ({_SCHEDULE_COLUMNS}) VALUES ({_SCHEDULE_PLACEHOLDERS})",
                values,
            )

        trigger_info = f"cron={cron_expression!r}" if cron_expression else f"run_at={run_at!r}"
        logger.info(
            f"Added schedule {schedule.id}: {name!r} "
            f"{trigger_info} next_run={schedule.next_run_at}"
        )
        return schedule

    def get_schedule(self, schedule_id: str) -> Optional[Schedule]:
        """Get schedule by ID."""
        row = self._db.execute_fetchone(
            "SELECT * FROM schedules WHERE exec_user = ? AND id = ?",
            (self.exec_user, schedule_id),
        )
        if not row:
            return None
        try:
            return _row_to_schedule(row)
        except Exception as e:
            logger.error(f"Failed to parse schedule {schedule_id}: {e}")
            return None

    def update_schedule(self, schedule: Schedule) -> bool:
        """Persist updated schedule fields to SQLite.

        Does NOT change status/index membership -- use pause/resume/cancel for that.
        """
        eu = schedule.exec_user or self.exec_user
        exists = self._db.execute_fetchone(
            "SELECT 1 FROM schedules WHERE exec_user = ? AND id = ?",
            (eu, schedule.id),
        )
        if not exists:
            return False

        schedule.updated_at = datetime.now(timezone.utc)
        row = _schedule_to_row(schedule, eu)
        update_cols = [k for k in _SCHEDULE_FIELDS if k not in ("id", "exec_user")]
        set_clause = ", ".join(f"{k} = ?" for k in update_cols)
        values = [row[k] for k in update_cols] + [eu, schedule.id]

        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE schedules SET {set_clause} WHERE exec_user = ? AND id = ?",
                values,
            )

        return True

    def delete_schedule(self, schedule_id: str) -> bool:
        """Hard delete a schedule and all related history."""
        eu = self.exec_user
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM schedule_history WHERE exec_user = ? AND schedule_id = ?",
                (eu, schedule_id),
            )
            conn.execute(
                "DELETE FROM schedules WHERE exec_user = ? AND id = ?",
                (eu, schedule_id),
            )
        logger.info(f"Hard deleted schedule {schedule_id}")
        return True

    # ---- Status transitions ----

    def _update_status(self, schedule: Schedule, new_status: ScheduleStatus) -> None:
        """Update schedule status."""
        now = datetime.now(timezone.utc)
        schedule.status = new_status
        schedule.updated_at = now

        if new_status == ScheduleStatus.PAUSED:
            schedule.paused_at = now
        elif new_status == ScheduleStatus.CANCELLED:
            schedule.cancelled_at = now
        elif new_status == ScheduleStatus.ACTIVE:
            schedule.paused_at = None
            schedule.next_run_at = schedule.compute_next_run()

        self.update_schedule(schedule)

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
        """Get all active schedules whose next_run_at <= now."""
        now = now or datetime.now(timezone.utc)
        now_ts = now.timestamp()

        rows = self._db.execute_fetchall(
            "SELECT * FROM schedules WHERE exec_user = ? AND status = 'active' "
            "AND next_run_at <= ? AND (expires_at IS NULL OR expires_at > ?)",
            (self.exec_user, now_ts, now_ts),
        )

        schedules: List[Schedule] = []
        for row in rows:
            try:
                schedule = _row_to_schedule(row)
            except Exception as e:
                logger.error(f"Failed to parse due schedule: {e}")
                continue

            if schedule.durability_mode == ScheduleDurabilityMode.SESSION_ONLY.value and not self._session_exists(schedule.session_id):
                logger.info(
                    "Auto-cancelling session-only schedule %s because session %s no longer exists",
                    schedule.id,
                    schedule.session_id,
                )
                self.cancel_schedule(schedule.id)
                continue

            schedules.append(schedule)
        return schedules

    def record_run(self, schedule: Schedule, task_id: str) -> None:
        """Record that the schedule fired and created a child task."""
        now = datetime.now(timezone.utc)
        eu = schedule.exec_user or self.exec_user

        schedule.run_count += 1
        schedule.last_run_at = now
        schedule.last_task_id = task_id
        schedule.updated_at = now

        with self._db.transaction() as conn:
            # Check max_runs limit
            if schedule.max_runs and schedule.run_count >= schedule.max_runs:
                logger.info(
                    f"Schedule {schedule.id} reached max_runs={schedule.max_runs}, auto-cancelling"
                )
                schedule.status = ScheduleStatus.CANCELLED
                schedule.cancelled_at = now

            # Compute next run
            if schedule.status != ScheduleStatus.CANCELLED:
                next_run = schedule.compute_next_run(base_time=now)
                jitter = self._compute_deterministic_jitter_seconds(
                    schedule.id,
                    schedule.run_count,
                    int(getattr(schedule, "jitter_seconds", 0) or 0),
                )
                if next_run is not None and jitter:
                    next_run = next_run + timedelta(seconds=jitter)
                if schedule.run_at is not None and next_run is None:
                    schedule.status = ScheduleStatus.CANCELLED
                    schedule.cancelled_at = now
                    schedule.next_run_at = None
                elif schedule.expires_at and next_run and next_run >= schedule.expires_at:
                    schedule.status = ScheduleStatus.CANCELLED
                    schedule.cancelled_at = now
                    schedule.next_run_at = None
                else:
                    schedule.next_run_at = next_run

            # Update schedule row
            row = _schedule_to_row(schedule, eu)
            update_cols = [k for k in _SCHEDULE_FIELDS if k not in ("id", "exec_user")]
            set_clause = ", ".join(f"{k} = ?" for k in update_cols)
            values = [row[k] for k in update_cols] + [eu, schedule.id]
            conn.execute(
                f"UPDATE schedules SET {set_clause} WHERE exec_user = ? AND id = ?",
                values,
            )

            # Append to history (keep last 100)
            conn.execute(
                "INSERT INTO schedule_history (schedule_id, exec_user, task_id, run_at) VALUES (?, ?, ?, ?)",
                (schedule.id, eu, task_id, now.timestamp()),
            )
            # Trim history to 100
            conn.execute(
                "DELETE FROM schedule_history WHERE id IN ("
                "  SELECT id FROM schedule_history WHERE exec_user = ? AND schedule_id = ?"
                "  ORDER BY id DESC LIMIT -1 OFFSET 100"
                ")",
                (eu, schedule.id),
            )

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

        status_norm = status.lower().strip() if status else None

        if status_norm:
            count_row = self._db.execute_fetchone(
                "SELECT COUNT(*) as cnt FROM schedules WHERE exec_user = ? AND status = ?",
                (self.exec_user, status_norm),
            )
            total = count_row["cnt"] if count_row else 0

            rows = self._db.execute_fetchall(
                "SELECT * FROM schedules WHERE exec_user = ? AND status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (self.exec_user, status_norm, page_size, (page - 1) * page_size),
            )
        else:
            count_row = self._db.execute_fetchone(
                "SELECT COUNT(*) as cnt FROM schedules WHERE exec_user = ?",
                (self.exec_user,),
            )
            total = count_row["cnt"] if count_row else 0

            rows = self._db.execute_fetchall(
                "SELECT * FROM schedules WHERE exec_user = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (self.exec_user, page_size, (page - 1) * page_size),
            )

        schedules = []
        for row in rows:
            try:
                schedules.append(_row_to_schedule(row))
            except Exception as e:
                logger.error(f"Failed to parse schedule in list: {e}")

        return schedules, total

    def get_schedule_task_history(self, schedule_id: str, limit: int = 20) -> List[str]:
        """Return recent task IDs spawned by this schedule."""
        rows = self._db.execute_fetchall(
            "SELECT task_id FROM schedule_history WHERE exec_user = ? AND schedule_id = ? ORDER BY id DESC LIMIT ?",
            (self.exec_user, schedule_id, limit),
        )
        return [row["task_id"] for row in rows]

# -*- coding: utf-8 -*-
"""Schedule data models for cron-based periodic task creation.

A Schedule is a persistent template that periodically spawns regular Task instances
via TaskQueue.add_task(). The Schedule itself never enters the task queue.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List
import json
import uuid

from croniter import croniter
from pydantic import BaseModel, Field, ConfigDict, field_validator


def _utcnow() -> datetime:
    """Return current UTC time"""
    return datetime.now(timezone.utc)


def _generate_schedule_id() -> str:
    """Generate a unique schedule ID"""
    return str(uuid.uuid4())[:8]


class ScheduleStatus(str, Enum):
    """Schedule lifecycle states"""
    ACTIVE = "active"         # Schedule is enabled and will fire
    PAUSED = "paused"         # Schedule is temporarily disabled
    CANCELLED = "cancelled"   # Schedule is permanently disabled


class Schedule(BaseModel):
    """Cron-based schedule definition for periodic task creation.

    When the cron expression fires, a new Task is created via TaskQueue.add_task()
    using the template fields stored in this schedule.
    """
    id: str = Field(default_factory=_generate_schedule_id)

    # Human-readable name
    name: str

    # Cron expression (standard 5-field: minute hour day_of_month month day_of_week)
    cron_expression: str

    # Timezone for cron evaluation (default: UTC)
    timezone: str = "UTC"

    # Schedule lifecycle
    status: ScheduleStatus = ScheduleStatus.ACTIVE

    # ---- Task template fields (mirrors TaskQueue.add_task params) ----
    description: str
    provider: str = "claude"
    alias: Optional[str] = None
    model: Optional[str] = None
    workspace: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    exec_user: Optional[str] = None
    context: Optional[Dict[str, Any]] = None

    # Execution limits
    max_runs: Optional[int] = None   # None = unlimited
    run_count: int = 0               # Number of times fired so far

    # Timing metadata
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None     # When last child task was created
    next_run_at: Optional[datetime] = None     # Pre-computed next fire time
    paused_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    # Lineage tracking
    last_task_id: Optional[str] = None         # ID of most recently spawned task

    # Owner tracking
    created_by: Optional[str] = None

    model_config = ConfigDict(use_enum_values=True)

    @field_validator("cron_expression")
    @classmethod
    def validate_cron_expression(cls, v: str) -> str:
        if not croniter.is_valid(v):
            raise ValueError(f"Invalid cron expression: {v}")
        return v

    def compute_next_run(self, base_time: Optional[datetime] = None) -> Optional[datetime]:
        """Compute the next fire time using croniter.

        Args:
            base_time: Base time for computation. Defaults to last_run_at or now.

        Returns:
            Next fire datetime (UTC), or None if cron is invalid.
        """
        base = base_time or self.last_run_at or datetime.now(timezone.utc)
        # Ensure base is timezone-aware
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        try:
            cron = croniter(self.cron_expression, base)
            next_dt = cron.get_next(datetime)
            if next_dt.tzinfo is None:
                next_dt = next_dt.replace(tzinfo=timezone.utc)
            return next_dt
        except Exception:
            return None

    def to_redis_hash(self) -> Dict[str, str]:
        """Convert schedule to Redis hash format"""
        data = self.model_dump()
        result = {}
        for key, value in data.items():
            if value is None:
                continue
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, dict):
                result[key] = json.dumps(value)
            elif isinstance(value, list):
                result[key] = json.dumps(value)
            elif isinstance(value, Enum):
                result[key] = value.value
            else:
                result[key] = str(value)
        return result

    @classmethod
    def from_redis_hash(cls, data: Dict[str, str]) -> "Schedule":
        """Create schedule from Redis hash data"""
        if not data:
            raise ValueError("Empty data")

        parsed = {}
        datetime_fields = (
            "created_at", "updated_at", "last_run_at", "next_run_at",
            "paused_at", "cancelled_at",
        )
        for key, value in data.items():
            if key in datetime_fields:
                parsed[key] = datetime.fromisoformat(value) if value else None
            elif key == "context":
                parsed[key] = json.loads(value) if value else None
            elif key == "run_count":
                parsed[key] = int(value)
            elif key == "max_runs":
                parsed[key] = int(value) if value and value != "None" else None
            elif key == "status":
                parsed[key] = ScheduleStatus(value)
            else:
                parsed[key] = value

        return cls(**parsed)

    def __repr__(self):
        return (
            f"<Schedule(id={self.id}, name={self.name!r}, "
            f"cron={self.cron_expression!r}, status={self.status})>"
        )

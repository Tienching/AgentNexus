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
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


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


class ScheduleKind(str, Enum):
    """What the schedule produces when it fires."""
    TASK = "task"              # Default: creates a Task via TaskQueue
    EVOLUTION = "evolution"    # Triggers EvolutionEngine (evolve or memory_synth)


class Schedule(BaseModel):
    """Schedule definition for periodic or one-time task creation.

    Supports two trigger modes (mutually exclusive):
    - Recurring: cron_expression fires periodically
    - One-time: run_at fires once at a specific datetime
    """
    id: str = Field(default_factory=_generate_schedule_id)

    # Human-readable name
    name: str

    # Cron expression (standard 5-field: minute hour day_of_month month day_of_week)
    # Optional: None for one-time schedules that use run_at instead
    cron_expression: Optional[str] = None

    # One-time trigger datetime (mutually exclusive with cron_expression)
    run_at: Optional[datetime] = None

    # Timezone for cron evaluation (default: UTC)
    timezone: str = "UTC"

    # Schedule lifecycle
    status: ScheduleStatus = ScheduleStatus.ACTIVE

    # Schedule kind — determines what happens when the schedule fires.
    # "task" (default): creates a regular Task via TaskQueue.
    # "evolution": triggers the EvolutionEngine directly (see evolution_phase).
    schedule_kind: ScheduleKind = ScheduleKind.TASK

    # Evolution-specific: which phase to run when schedule_kind == "evolution".
    # "full"      — runs a full evolution cycle (EvolutionEngine.run_full_cycle)
    # "memory_synth" — runs memory synthesis only (EvolutionEngine.run_memory_synthesis)
    # Ignored when schedule_kind != "evolution".
    evolution_phase: Optional[str] = None

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

    @model_validator(mode="after")
    def validate_trigger(self):
        """Require either cron_expression or run_at, not both."""
        # Evolution schedules always use cron_expression; relax validation
        # for other edge cases if needed in the future.
        if not self.cron_expression and not self.run_at:
            raise ValueError("Either cron_expression or run_at is required")
        if self.cron_expression and self.run_at:
            raise ValueError("Cannot set both cron_expression and run_at")
        if self.cron_expression and not croniter.is_valid(self.cron_expression):
            raise ValueError(f"Invalid cron expression: {self.cron_expression}")
        if self.evolution_phase and self.schedule_kind != ScheduleKind.EVOLUTION.value:
            raise ValueError("evolution_phase can only be set when schedule_kind is 'evolution'")
        if self.schedule_kind == ScheduleKind.EVOLUTION.value and not self.evolution_phase:
            raise ValueError("evolution_phase is required when schedule_kind is 'evolution'")
        return self

    def compute_next_run(self, base_time: Optional[datetime] = None) -> Optional[datetime]:
        """Compute the next fire time.

        For one-time schedules (run_at), returns run_at if not yet fired.
        For cron schedules, uses croniter to compute the next fire time.

        Args:
            base_time: Base time for computation. Defaults to last_run_at or now.

        Returns:
            Next fire datetime (UTC), or None if not applicable.
        """
        # One-time schedule: return run_at if not yet fired
        if self.run_at:
            if self.run_count == 0:
                run_at = self.run_at
                if run_at.tzinfo is None:
                    run_at = run_at.replace(tzinfo=timezone.utc)
                return run_at
            return None  # already fired

        # Recurring cron schedule
        if not self.cron_expression:
            return None
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
            "paused_at", "cancelled_at", "run_at",
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
            elif key == "schedule_kind":
                parsed[key] = ScheduleKind(value) if value else ScheduleKind.TASK
            else:
                parsed[key] = value

        return cls(**parsed)

    def __repr__(self):
        trigger = f"cron={self.cron_expression!r}" if self.cron_expression else f"run_at={self.run_at!r}"
        return (
            f"<Schedule(id={self.id}, name={self.name!r}, "
            f"{trigger}, status={self.status})>"
        )

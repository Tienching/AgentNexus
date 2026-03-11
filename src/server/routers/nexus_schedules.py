# -*- coding: utf-8 -*-
"""NexusHub Schedule API Router

Provides REST API endpoints for managing cron-based scheduled tasks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from .nexus_auth import verify_nexus_auth

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-schedules"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ============ Request / Response Models ============


class CreateScheduleRequest(BaseModel):
    model_config = {"populate_by_name": True}

    name: str = Field(..., description="Schedule name")
    cron_expression: Optional[str] = Field(None, description="Cron expression (5-field). Required for recurring schedules.")
    run_at: Optional[datetime] = Field(None, description="One-time trigger datetime (ISO 8601). Mutually exclusive with cron_expression.")
    description: str = Field(..., description="Task description template")
    timezone: str = Field("UTC", description="Timezone for cron evaluation")
    provider: Optional[str] = Field(None, description="Provider name (claude/gemini/codex/codebuddy)")
    alias: Optional[str] = Field(None, description="Alias (defaults to provider)")
    llm_model: Optional[str] = Field(None, alias="model", description="LLM model name")
    workspace: Optional[str] = Field(None, description="Execution workspace")
    project_id: Optional[str] = Field(None, description="Project ID (slug)")
    project_name: Optional[str] = Field(None, description="Project name")
    exec_user: Optional[str] = Field(None, description="Execution user")
    context: Optional[Dict[str, Any]] = Field(None, description="Extra context for task creation")
    max_runs: Optional[int] = Field(None, ge=1, description="Max runs before auto-cancel (null = unlimited)")


class UpdateScheduleRequest(BaseModel):
    model_config = {"populate_by_name": True}

    name: Optional[str] = Field(None, description="Schedule name")
    cron_expression: Optional[str] = Field(None, description="Cron expression (5-field)")
    run_at: Optional[datetime] = Field(None, description="One-time trigger datetime")
    description: Optional[str] = Field(None, description="Task description template")
    timezone: Optional[str] = Field(None, description="Timezone for cron evaluation")
    provider: Optional[str] = Field(None, description="Provider name")
    alias: Optional[str] = Field(None, description="Alias")
    llm_model: Optional[str] = Field(None, alias="model", description="LLM model name")
    workspace: Optional[str] = Field(None, description="Execution workspace")
    project_id: Optional[str] = Field(None, description="Project ID")
    project_name: Optional[str] = Field(None, description="Project name")
    exec_user: Optional[str] = Field(None, description="Execution user")
    context: Optional[Dict[str, Any]] = Field(None, description="Extra context")
    max_runs: Optional[int] = Field(None, ge=1, description="Max runs")


class ScheduleItem(BaseModel):
    id: str
    name: str
    cron_expression: Optional[str] = None
    run_at: Optional[datetime] = None
    timezone: str = "UTC"
    status: str
    description: str
    provider: str = "claude"
    alias: Optional[str] = None
    model: Optional[str] = None
    workspace: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    exec_user: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    max_runs: Optional[int] = None
    run_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    last_task_id: Optional[str] = None
    created_by: Optional[str] = None


class ScheduleListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    schedules: List[ScheduleItem] = []


class SuccessResponse(BaseModel):
    success: bool = True
    message: Optional[str] = None


class ScheduleHistoryResponse(BaseModel):
    schedule_id: str
    task_ids: List[str] = []


# ============ Helpers ============


def _get_schedule_storage():
    """Get ScheduleStorage for the current exec_user."""
    import os
    from ..services.schedule_storage import ScheduleStorage
    exec_user = os.environ.get("EXEC_USER", "ubuntu")
    return ScheduleStorage(exec_user=exec_user)


def _schedule_to_item(schedule) -> ScheduleItem:
    """Convert a Schedule model to API response item."""
    status_val = schedule.status if isinstance(schedule.status, str) else schedule.status.value
    return ScheduleItem(
        id=schedule.id,
        name=schedule.name,
        cron_expression=schedule.cron_expression,
        run_at=schedule.run_at,
        timezone=schedule.timezone,
        status=status_val,
        description=schedule.description,
        provider=schedule.provider,
        alias=schedule.alias,
        model=schedule.model,
        workspace=schedule.workspace,
        project_id=schedule.project_id,
        project_name=schedule.project_name,
        exec_user=schedule.exec_user,
        context=schedule.context,
        max_runs=schedule.max_runs,
        run_count=schedule.run_count,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        paused_at=schedule.paused_at,
        cancelled_at=schedule.cancelled_at,
        last_task_id=schedule.last_task_id,
        created_by=schedule.created_by,
    )


# ============ List Schedules ============


@router.get("/schedules", response_model=ScheduleListResponse)
async def list_schedules(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    status_param: Optional[str] = Query(None, alias="status", description="Filter by status (active/paused/cancelled)"),
):
    """List schedules with pagination and optional status filter."""
    storage = _get_schedule_storage()

    schedules, total = storage.list_schedules(
        page=page,
        page_size=page_size,
        status=status_param,
    )

    return ScheduleListResponse(
        total=total,
        page=page,
        page_size=page_size,
        schedules=[_schedule_to_item(s) for s in schedules],
    )


# ============ Get Schedule ============


@router.get("/schedules/{schedule_id}", response_model=ScheduleItem)
async def get_schedule(schedule_id: str):
    """Get schedule detail by ID."""
    storage = _get_schedule_storage()
    schedule = storage.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule not found: {schedule_id}",
        )
    return _schedule_to_item(schedule)


# ============ Create Schedule ============


@router.post("/schedules", response_model=ScheduleItem)
async def create_schedule(request: CreateScheduleRequest):
    """Create a new schedule (recurring cron or one-time run_at).

    Exactly one of cron_expression or run_at must be provided.
    The schedule starts in ACTIVE state and will fire at the appropriate time.
    """
    name = (request.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    desc = (request.description or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="description is required")

    cron_expr = (request.cron_expression or "").strip() or None
    run_at_val = request.run_at

    # Validate mutually exclusive trigger
    if not cron_expr and not run_at_val:
        raise HTTPException(status_code=400, detail="Either cron_expression or run_at is required")
    if cron_expr and run_at_val:
        raise HTTPException(status_code=400, detail="Cannot set both cron_expression and run_at")

    # Validate cron expression if provided
    if cron_expr:
        try:
            from croniter import croniter
            if not croniter.is_valid(cron_expr):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid cron expression: {cron_expr}",
                )
        except ImportError:
            raise HTTPException(status_code=500, detail="croniter library not installed")

    # For one-time schedules, auto-set max_runs=1 if not provided
    max_runs = request.max_runs
    if run_at_val and max_runs is None:
        max_runs = 1

    # Resolve defaults
    default_provider = (settings.default_provider or "").strip().lower() or "codebuddy"
    provider = (request.provider or "").strip().lower() or default_provider

    from ..providers import get_provider_registry
    allowed = set(get_provider_registry().list_providers())
    if provider not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}")

    default_alias = (settings.default_alias or "").strip().lower()
    alias_value = (request.alias or "").strip() or default_alias or provider

    default_exec_user = (settings.default_exec_user or "").strip() or None
    effective_exec_user = (request.exec_user or "").strip() or default_exec_user

    storage = _get_schedule_storage()

    try:
        schedule = storage.add_schedule(
            name=name,
            description=desc,
            cron_expression=cron_expr,
            run_at=run_at_val,
            timezone_str=(request.timezone or "UTC").strip(),
            provider=provider,
            alias=alias_value,
            model=(request.llm_model or "").strip() or None,
            workspace=(request.workspace or "").strip() or None,
            project_id=(request.project_id or "").strip() or None,
            project_name=(request.project_name or "").strip() or None,
            exec_user=effective_exec_user,
            context=request.context,
            max_runs=max_runs,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create schedule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create schedule: {e}")

    return _schedule_to_item(schedule)


# ============ Update Schedule ============


@router.put("/schedules/{schedule_id}", response_model=ScheduleItem)
async def update_schedule(schedule_id: str, request: UpdateScheduleRequest):
    """Update schedule fields.

    Only provided (non-null) fields are updated. Does not change status — use
    pause/resume/cancel endpoints for status transitions.
    """
    storage = _get_schedule_storage()
    schedule = storage.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule not found: {schedule_id}",
        )

    # Validate new cron expression if provided
    if request.cron_expression is not None:
        cron_expr = request.cron_expression.strip()
        try:
            from croniter import croniter
            if not croniter.is_valid(cron_expr):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid cron expression: {cron_expr}",
                )
        except ImportError:
            raise HTTPException(status_code=500, detail="croniter library not installed")
        schedule.cron_expression = cron_expr
        schedule.run_at = None  # Clear run_at if switching to cron

    # Handle run_at update
    if request.run_at is not None:
        schedule.run_at = request.run_at
        schedule.cron_expression = None  # Clear cron if switching to one-time

    # Apply updates for provided fields
    if request.name is not None:
        schedule.name = request.name.strip()
    if request.description is not None:
        schedule.description = request.description.strip()
    if request.timezone is not None:
        schedule.timezone = request.timezone.strip()
    if request.provider is not None:
        schedule.provider = request.provider.strip().lower()
    if request.alias is not None:
        schedule.alias = request.alias.strip()
    if request.llm_model is not None:
        schedule.model = request.llm_model.strip() or None
    if request.workspace is not None:
        schedule.workspace = request.workspace.strip() or None
    if request.project_id is not None:
        schedule.project_id = request.project_id.strip() or None
    if request.project_name is not None:
        schedule.project_name = request.project_name.strip() or None
    if request.exec_user is not None:
        schedule.exec_user = request.exec_user.strip() or None
    if request.context is not None:
        schedule.context = request.context
    if request.max_runs is not None:
        schedule.max_runs = request.max_runs

    # Re-compute next_run_at if trigger or timezone changed
    if request.cron_expression is not None or request.run_at is not None or request.timezone is not None:
        schedule.next_run_at = schedule.compute_next_run()

    ok = storage.update_schedule(schedule)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update schedule")

    return _schedule_to_item(schedule)


# ============ Delete Schedule ============


@router.delete("/schedules/{schedule_id}", response_model=SuccessResponse)
async def delete_schedule(schedule_id: str):
    """Hard delete a schedule and all related data."""
    storage = _get_schedule_storage()
    storage.delete_schedule(schedule_id)
    return SuccessResponse(message=f"Schedule {schedule_id} deleted")


# ============ Status Transitions ============


@router.post("/schedules/{schedule_id}/pause", response_model=ScheduleItem)
async def pause_schedule(schedule_id: str):
    """Pause an active schedule. Paused schedules do not fire."""
    storage = _get_schedule_storage()
    schedule = storage.pause_schedule(schedule_id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule not found: {schedule_id}",
        )
    return _schedule_to_item(schedule)


@router.post("/schedules/{schedule_id}/resume", response_model=ScheduleItem)
async def resume_schedule(schedule_id: str):
    """Resume a paused schedule."""
    storage = _get_schedule_storage()
    schedule = storage.resume_schedule(schedule_id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule not found: {schedule_id}",
        )
    return _schedule_to_item(schedule)


@router.post("/schedules/{schedule_id}/cancel", response_model=ScheduleItem)
async def cancel_schedule(schedule_id: str):
    """Permanently cancel a schedule. Cancelled schedules cannot be resumed."""
    storage = _get_schedule_storage()
    schedule = storage.cancel_schedule(schedule_id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule not found: {schedule_id}",
        )
    return _schedule_to_item(schedule)


# ============ Manual Trigger ============


@router.post("/schedules/{schedule_id}/trigger", response_model=SuccessResponse)
async def trigger_schedule(schedule_id: str):
    """Manually trigger a schedule, bypassing cron timing.

    Creates a child task immediately without waiting for the next cron fire time.
    """
    from src.runtime.execution.scheduler import get_scheduler

    scheduler = get_scheduler()
    if not scheduler:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler is not running",
        )

    try:
        task_id = await scheduler.trigger_schedule(schedule_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if task_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule not found: {schedule_id}",
        )

    return SuccessResponse(message=f"Schedule triggered, created task {task_id}")


# ============ History ============


@router.get("/schedules/{schedule_id}/history", response_model=ScheduleHistoryResponse)
async def get_schedule_history(
    schedule_id: str,
    limit: int = Query(20, ge=1, le=100, description="Max number of task IDs to return"),
):
    """Get recent task IDs spawned by this schedule."""
    storage = _get_schedule_storage()

    # Verify schedule exists
    schedule = storage.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule not found: {schedule_id}",
        )

    task_ids = storage.get_schedule_task_history(schedule_id, limit=limit)
    return ScheduleHistoryResponse(schedule_id=schedule_id, task_ids=task_ids)

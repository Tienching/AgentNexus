# -*- coding: utf-8 -*-
"""Nexus schedule API router."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from ..security.exec_user_guard import validate_exec_user
from ..services.schedule_storage import ScheduleStorage
from ..services.workspace_validation import normalize_workspace_path
from .nexus_auth import verify_nexus_auth

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-schedules"],
    dependencies=[Depends(verify_nexus_auth)],
)


class ScheduleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    cron_expression: Optional[str] = None
    run_at: Optional[datetime] = None
    timezone: str = "UTC"
    provider: str = "claude"
    alias: Optional[str] = None
    model: Optional[str] = None
    workspace: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    exec_user: Optional[str] = None
    context: Optional[dict[str, Any]] = None
    max_runs: Optional[int] = None
    schedule_kind: str = "task"
    evolution_phase: Optional[str] = None
    durability_mode: str = "durable"
    session_id: Optional[str] = None
    ttl_seconds: Optional[int] = None
    jitter_seconds: int = 0


class ScheduleUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cron_expression: Optional[str] = None
    run_at: Optional[datetime] = None
    timezone: Optional[str] = None
    provider: Optional[str] = None
    alias: Optional[str] = None
    model: Optional[str] = None
    workspace: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    context: Optional[dict[str, Any]] = None
    max_runs: Optional[int] = None


def _schedule_to_dict(schedule) -> dict[str, Any]:
    return schedule.model_dump(mode="json")


def _storage(exec_user: str) -> ScheduleStorage:
    return ScheduleStorage(exec_user=exec_user)


@router.get("/schedules")
async def list_schedules(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    status_filter: Optional[str] = Query(None, alias="status"),
    exec_user: str = Query(settings.exec_user),
):
    effective_exec_user = await validate_exec_user(exec_user)
    items, total = _storage(effective_exec_user).list_schedules(
        page=page,
        page_size=page_size,
        status=status_filter,
    )
    payload = [_schedule_to_dict(item) for item in items]
    return {"items": payload, "schedules": payload, "total": total, "page": page, "page_size": page_size}


@router.get("/schedules/{schedule_id}")
async def get_schedule(schedule_id: str, exec_user: str = Query(settings.exec_user)):
    effective_exec_user = await validate_exec_user(exec_user)
    schedule = _storage(effective_exec_user).get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return _schedule_to_dict(schedule)


@router.post("/schedules", status_code=status.HTTP_201_CREATED)
async def create_schedule(request: ScheduleCreateRequest, exec_user: str = Query(settings.exec_user)):
    default_exec_user = (request.exec_user or exec_user or settings.exec_user).strip()
    effective_exec_user = await validate_exec_user(default_exec_user)
    workspace = normalize_workspace_path(request.workspace)
    try:
        schedule = _storage(effective_exec_user).add_schedule(
            name=request.name.strip(),
            description=request.description or "",
            cron_expression=request.cron_expression,
            run_at=request.run_at,
            timezone_str=request.timezone or "UTC",
            provider=(request.provider or "claude").strip().lower(),
            alias=(request.alias or None),
            model=(request.model or None),
            workspace=workspace,
            project_id=(request.project_id or None),
            project_name=(request.project_name or None),
            exec_user=effective_exec_user,
            context=request.context,
            max_runs=request.max_runs,
            created_by=effective_exec_user,
            schedule_kind=request.schedule_kind or "task",
            evolution_phase=request.evolution_phase,
            durability_mode=request.durability_mode or "durable",
            session_id=request.session_id,
            ttl_seconds=request.ttl_seconds,
            jitter_seconds=request.jitter_seconds or 0,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _schedule_to_dict(schedule)


@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, request: ScheduleUpdateRequest, exec_user: str = Query(settings.exec_user)):
    effective_exec_user = await validate_exec_user(exec_user)
    storage = _storage(effective_exec_user)
    schedule = storage.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")

    data = request.model_dump(exclude_unset=True)
    if "workspace" in data:
        data["workspace"] = normalize_workspace_path(data["workspace"])
    if "timezone" in data:
        schedule.timezone = data.pop("timezone") or "UTC"
    for key, value in data.items():
        setattr(schedule, key, value)
    try:
        schedule.next_run_at = schedule.compute_next_run()
        ok = storage.update_schedule(schedule)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return _schedule_to_dict(schedule)


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, exec_user: str = Query(settings.exec_user)):
    effective_exec_user = await validate_exec_user(exec_user)
    _storage(effective_exec_user).delete_schedule(schedule_id)
    return {"success": True, "deleted": True}


@router.post("/schedules/{schedule_id}/pause")
async def pause_schedule(schedule_id: str, exec_user: str = Query(settings.exec_user)):
    effective_exec_user = await validate_exec_user(exec_user)
    schedule = _storage(effective_exec_user).pause_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return _schedule_to_dict(schedule)


@router.post("/schedules/{schedule_id}/resume")
async def resume_schedule(schedule_id: str, exec_user: str = Query(settings.exec_user)):
    effective_exec_user = await validate_exec_user(exec_user)
    schedule = _storage(effective_exec_user).resume_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return _schedule_to_dict(schedule)


@router.post("/schedules/{schedule_id}/cancel")
async def cancel_schedule(schedule_id: str, exec_user: str = Query(settings.exec_user)):
    effective_exec_user = await validate_exec_user(exec_user)
    schedule = _storage(effective_exec_user).cancel_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return _schedule_to_dict(schedule)


@router.post("/schedules/{schedule_id}/trigger")
async def trigger_schedule(schedule_id: str, exec_user: str = Query(settings.exec_user)):
    effective_exec_user = await validate_exec_user(exec_user)
    storage = _storage(effective_exec_user)
    schedule = storage.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    try:
        from src.runtime.execution.scheduler import get_scheduler

        scheduler = get_scheduler()
        task_id = None
        if scheduler is not None:
            task_id = await scheduler.trigger_schedule(schedule_id)
        if task_id is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Scheduler is not running")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"success": True, "task_id": task_id}


@router.get("/schedules/{schedule_id}/history")
async def get_schedule_history(
    schedule_id: str,
    limit: int = Query(20, ge=1, le=100),
    exec_user: str = Query(settings.exec_user),
):
    effective_exec_user = await validate_exec_user(exec_user)
    history = _storage(effective_exec_user).get_schedule_task_history(schedule_id, limit=limit)
    return {"task_ids": history, "history": history}

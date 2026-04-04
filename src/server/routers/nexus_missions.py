# -*- coding: utf-8 -*-
"""Nexus Missions API Router — REST endpoints for nanobot mission system.

Provides HTTP endpoints for creating, managing, and monitoring autonomous
missions backed by nanobot's MissionService.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..routers.nexus_auth import verify_nexus_auth

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-missions"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ── Request/Response Models ────────────────────────────────────────

class MissionCreateRequest(BaseModel):
    """Request body for creating/planning a mission."""

    goal: str = Field(..., description="Goal description for the mission")
    workspace: Optional[str] = Field(None, description="Working directory path")
    auto_approve: bool = Field(False, description="If True, plan + start immediately")
    context: str = Field("", description="Additional context for planning")


class MissionActionResponse(BaseModel):
    """Generic action response."""

    ok: bool
    message: str


class MissionTaskTokenUsageResponse(BaseModel):
    total_tokens: int
    llm_iterations: int


class MissionTaskResultResponse(BaseModel):
    status: str
    error: str | None = None
    duration_seconds: float
    token_usage: MissionTaskTokenUsageResponse


class MissionTaskResponse(BaseModel):
    id: str
    title: str
    description: str
    role: str
    status: str
    depends_on: list[str] = Field(default_factory=list)
    result: MissionTaskResultResponse | None = None


class MissionMilestoneResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    depends_on: list[str] = Field(default_factory=list)
    tasks: list[MissionTaskResponse] = Field(default_factory=list)


class MissionTokenUsageResponse(BaseModel):
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    llm_iterations: int
    estimated_cost_usd: float


class MissionDetailResponse(BaseModel):
    id: str
    goal: str
    mission_type: str
    status: str
    milestones: list[MissionMilestoneResponse] = Field(default_factory=list)
    total_tasks: int
    completed_tasks: int
    progress_pct: float
    wall_clock_display: str
    token_usage: MissionTokenUsageResponse
    error: str | None = None
    created_at_ms: int
    updated_at_ms: int


class MissionStatusResponse(BaseModel):
    mission_id: str
    status_text: str


class MissionListResponse(BaseModel):
    missions_text: str


class MissionLogResponse(BaseModel):
    mission_id: str
    entries: list[str] = Field(default_factory=list)
    count: int


# ── Helpers ────────────────────────────────────────────────────────

def _get_bridge():
    """Get MissionBridge singleton."""
    from ..services.mission_bridge import MissionBridge

    return MissionBridge.get_instance()


def _check_enabled():
    """Raise 503 if missions are disabled."""
    from ..config import settings

    if not settings.nanobot_missions_enabled:
        raise HTTPException(status_code=503, detail="Mission system is disabled")


# ── Endpoints ──────────────────────────────────────────────────────

@router.post("/missions", response_model=MissionDetailResponse)
async def create_mission(req: MissionCreateRequest):
    """Create (plan) a new mission, optionally auto-approving it."""
    _check_enabled()
    bridge = _get_bridge()
    try:
        if req.auto_approve:
            data = await bridge.start(
                goal=req.goal,
                workspace=req.workspace,
                context=req.context,
            )
        else:
            data = await bridge.plan(
                goal=req.goal,
                workspace=req.workspace,
                context=req.context,
            )
        return MissionDetailResponse(**data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/missions/{mission_id}/approve", response_model=MissionActionResponse)
async def approve_mission(mission_id: str):
    """Approve a planned mission and start execution."""
    _check_enabled()
    bridge = _get_bridge()
    ok = await bridge.approve(mission_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Mission {mission_id} not found or not in 'planned' status",
        )
    return MissionActionResponse(ok=True, message=f"Mission {mission_id} approved and started")


@router.get("/missions/{mission_id}", response_model=MissionDetailResponse)
async def get_mission(mission_id: str):
    """Get mission detail with formatted status."""
    _check_enabled()
    bridge = _get_bridge()
    data = bridge.get_mission_detail(mission_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
    return MissionDetailResponse(**data)


@router.get("/missions/{mission_id}/status", response_model=MissionStatusResponse)
async def get_mission_status(mission_id: str):
    """Get formatted mission status (markdown)."""
    _check_enabled()
    bridge = _get_bridge()
    payload = await bridge.get_status_payload(mission_id)
    if not payload:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
    return MissionStatusResponse(**payload)


@router.get("/missions", response_model=MissionListResponse)
async def list_missions(
    include_completed: bool = Query(False, description="Include completed/failed/cancelled"),
):
    """List all missions."""
    _check_enabled()
    bridge = _get_bridge()
    payload = await bridge.get_mission_list_payload(include_completed=include_completed)
    return MissionListResponse(**payload)


@router.post("/missions/{mission_id}/cancel", response_model=MissionActionResponse)
async def cancel_mission(mission_id: str):
    """Cancel a mission."""
    _check_enabled()
    bridge = _get_bridge()
    ok = await bridge.cancel(mission_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found or already completed/cancelled")
    return MissionActionResponse(ok=True, message=f"Mission {mission_id} cancelled")


@router.post("/missions/{mission_id}/pause", response_model=MissionActionResponse)
async def pause_mission(mission_id: str):
    """Pause a running mission."""
    _check_enabled()
    bridge = _get_bridge()
    ok = await bridge.pause(mission_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found or not running")
    return MissionActionResponse(ok=True, message=f"Mission {mission_id} paused")


@router.post("/missions/{mission_id}/resume", response_model=MissionActionResponse)
async def resume_mission(mission_id: str):
    """Resume a paused mission."""
    _check_enabled()
    bridge = _get_bridge()
    ok = await bridge.resume(mission_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found or not paused")
    return MissionActionResponse(ok=True, message=f"Mission {mission_id} resumed")


@router.get("/missions/{mission_id}/log", response_model=MissionLogResponse)
async def get_mission_log(
    mission_id: str,
    tail: Optional[int] = Query(None, description="Show only last N log entries"),
):
    """Get mission log entries."""
    _check_enabled()
    bridge = _get_bridge()
    payload = bridge.get_mission_log_payload(mission_id, tail=tail)
    if not payload:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
    return MissionLogResponse(**payload)

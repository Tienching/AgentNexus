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

@router.post("/missions")
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
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/missions/{mission_id}/approve")
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


@router.get("/missions/{mission_id}")
async def get_mission(mission_id: str):
    """Get mission detail with formatted status."""
    _check_enabled()
    bridge = _get_bridge()
    mission = bridge.get_mission_raw(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
    return bridge._mission_to_dict(mission)


@router.get("/missions/{mission_id}/status")
async def get_mission_status(mission_id: str):
    """Get formatted mission status (markdown)."""
    _check_enabled()
    bridge = _get_bridge()
    text = await bridge.status(mission_id)
    if not text:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
    return {"mission_id": mission_id, "status_text": text}


@router.get("/missions")
async def list_missions(
    include_completed: bool = Query(False, description="Include completed/failed/cancelled"),
):
    """List all missions."""
    _check_enabled()
    bridge = _get_bridge()
    text = await bridge.list_missions(include_completed=include_completed)
    return {"missions_text": text}


@router.post("/missions/{mission_id}/cancel")
async def cancel_mission(mission_id: str):
    """Cancel a mission."""
    _check_enabled()
    bridge = _get_bridge()
    ok = await bridge.cancel(mission_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found or already completed/cancelled")
    return MissionActionResponse(ok=True, message=f"Mission {mission_id} cancelled")


@router.post("/missions/{mission_id}/pause")
async def pause_mission(mission_id: str):
    """Pause a running mission."""
    _check_enabled()
    bridge = _get_bridge()
    ok = await bridge.pause(mission_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found or not running")
    return MissionActionResponse(ok=True, message=f"Mission {mission_id} paused")


@router.post("/missions/{mission_id}/resume")
async def resume_mission(mission_id: str):
    """Resume a paused mission."""
    _check_enabled()
    bridge = _get_bridge()
    ok = await bridge.resume(mission_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found or not paused")
    return MissionActionResponse(ok=True, message=f"Mission {mission_id} resumed")


@router.get("/missions/{mission_id}/log")
async def get_mission_log(
    mission_id: str,
    tail: Optional[int] = Query(None, description="Show only last N log entries"),
):
    """Get mission log entries."""
    _check_enabled()
    bridge = _get_bridge()
    entries = bridge.get_log(mission_id, tail=tail)
    if entries is None:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
    return {"mission_id": mission_id, "entries": entries, "count": len(entries)}

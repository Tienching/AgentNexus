# -*- coding: utf-8 -*-
"""Runtime permission mode and plan mode management API.

Permission Endpoints:
  - GET  /api/nexus/permissions              — current permission mode and stats
  - PUT  /api/nexus/permissions/mode         — change the permission mode
  - POST /api/nexus/permissions/cache/clear  — clear the permission cache

Plan Mode Endpoints:
  - POST /api/nexus/plan/enter    — enter plan mode (read-only)
  - POST /api/nexus/plan/submit   — submit a plan for approval
  - POST /api/nexus/plan/approve  — approve plan, switch to execution
  - POST /api/nexus/plan/reject   — reject plan, stay in plan mode
  - GET  /api/nexus/plan/status   — current plan mode status
  - POST /api/nexus/plan/exit     — exit plan mode without approving
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from .nexus_auth import verify_nexus_auth

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-permissions"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

PermissionModeValue = Literal["auto", "ask", "plan", "bypass"]


class PermissionModeRequest(BaseModel):
    """Request body for changing the permission mode."""
    mode: PermissionModeValue = Field(
        ...,
        description="New permission mode: auto, ask, plan, or bypass",
    )


class PermissionModeResponse(BaseModel):
    """Response with current permission mode and stats."""
    mode: str
    stats: dict[str, int]


class CacheClearResponse(BaseModel):
    """Response after clearing the permission cache."""
    cleared: bool = True
    message: str = "Permission cache cleared"


class PlanSubmitRequest(BaseModel):
    """Request body for submitting a plan."""
    content: str = Field(
        ...,
        min_length=1,
        description="The plan content to submit for approval",
    )


class PlanStatusResponse(BaseModel):
    """Response with current plan mode status."""
    plan_mode: bool
    plan_content: str | None = None
    plan_approved: bool = False
    permission_mode: str


class PlanActionResponse(BaseModel):
    """Response after a plan mode action."""
    success: bool
    message: str


# ---------------------------------------------------------------------------
# Helper — get the agent loop
# ---------------------------------------------------------------------------

def _get_agent_loop():
    """Get the active AgentLoop from the server runtime.

    Returns None if no loop is running.
    """
    try:
        from ..app import get_agent_loop
        return get_agent_loop()
    except Exception:
        return None


def _get_permission_gate():
    """Get the active PermissionGate from the server's agent loop."""
    loop = _get_agent_loop()
    if loop is None:
        return None
    return loop.permission_gate


# ---------------------------------------------------------------------------
# Permission Routes
# ---------------------------------------------------------------------------

@router.get("/permissions", response_model=PermissionModeResponse)
async def get_permissions():
    """Get the current permission mode and approval statistics."""
    gate = _get_permission_gate()
    if gate is None:
        return PermissionModeResponse(mode="auto", stats={})

    return PermissionModeResponse(
        mode=gate.mode.value,
        stats=gate.stats,
    )


@router.put("/permissions/mode", response_model=PermissionModeResponse)
async def set_permission_mode(req: PermissionModeRequest):
    """Change the runtime permission mode.

    Changing the mode clears the permission cache.
    Valid modes: auto, ask, plan, bypass.
    """
    from src.core.agent_runtime.agent.permissions import PermissionMode

    gate = _get_permission_gate()
    if gate is None:
        raise HTTPException(status_code=503, detail="Agent loop not running")

    try:
        new_mode = PermissionMode(req.mode)
    except ValueError:
        valid = ", ".join(m.value for m in PermissionMode)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid permission mode '{req.mode}'. Valid: {valid}",
        )

    old_mode = gate.mode.value
    gate.mode = new_mode  # setter clears cache on change
    logger.info("Permission mode changed via API: {} → {}", old_mode, req.mode)

    return PermissionModeResponse(
        mode=gate.mode.value,
        stats=gate.stats,
    )


@router.post("/permissions/cache/clear", response_model=CacheClearResponse)
async def clear_permission_cache():
    """Clear the permission approval cache.

    Forces re-approval for all tool calls on next request (in ask mode).
    """
    gate = _get_permission_gate()
    if gate is None:
        raise HTTPException(status_code=503, detail="Agent loop not running")

    gate.cache.clear()
    logger.info("Permission cache cleared via API")

    return CacheClearResponse()


# ---------------------------------------------------------------------------
# Plan Mode Routes
# ---------------------------------------------------------------------------

@router.post("/plan/enter", response_model=PlanActionResponse)
async def enter_plan_mode():
    """Enter plan mode — only read-only tools are allowed.

    The previous permission mode is saved and will be restored when plan mode
    is exited (either via approve or explicit exit).
    """
    loop = _get_agent_loop()
    if loop is None:
        raise HTTPException(status_code=503, detail="Agent loop not running")

    if loop._plan_mode:
        raise HTTPException(
            status_code=409,
            detail="Already in plan mode. Use /api/nexus/plan/exit to leave, "
                   "or /api/nexus/plan/submit to submit a plan.",
        )

    loop.enter_plan_mode()
    logger.info("Plan mode entered via API")

    return PlanActionResponse(
        success=True,
        message="Entered plan mode. Only read-only tools are allowed. "
                "Submit a plan for approval when ready.",
    )


@router.post("/plan/submit", response_model=PlanActionResponse)
async def submit_plan(req: PlanSubmitRequest):
    """Submit a plan for approval.

    The plan content is stored and can be approved or rejected.
    While in plan mode, only read-only exploration is allowed.
    """
    loop = _get_agent_loop()
    if loop is None:
        raise HTTPException(status_code=503, detail="Agent loop not running")

    if not loop._plan_mode:
        raise HTTPException(
            status_code=409,
            detail="Not in plan mode. Use /api/nexus/plan/enter first.",
        )

    try:
        loop.submit_plan(req.content)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    logger.info("Plan submitted via API ({} chars)", len(req.content))

    return PlanActionResponse(
        success=True,
        message="Plan submitted. Use /api/nexus/plan/approve to approve "
                "and switch to execution mode, or /api/nexus/plan/reject to revise.",
    )


@router.post("/plan/approve", response_model=PlanActionResponse)
async def approve_plan():
    """Approve the current plan and switch to execution mode.

    Exits plan mode and restores the previous permission mode,
    allowing full tool access for execution.
    """
    loop = _get_agent_loop()
    if loop is None:
        raise HTTPException(status_code=503, detail="Agent loop not running")

    if not loop._plan_mode:
        raise HTTPException(
            status_code=409,
            detail="Not in plan mode.",
        )

    if loop._plan_content is None:
        raise HTTPException(
            status_code=409,
            detail="No plan has been submitted. Use /api/nexus/plan/submit first.",
        )

    try:
        loop.approve_plan()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    logger.info("Plan approved via API — switched to execution mode")

    return PlanActionResponse(
        success=True,
        message="Plan approved. Switched to execution mode with full tool access.",
    )


@router.post("/plan/reject", response_model=PlanActionResponse)
async def reject_plan():
    """Reject the current plan. Remains in plan mode for revision.

    Clears the submitted plan content so a new one can be submitted.
    """
    loop = _get_agent_loop()
    if loop is None:
        raise HTTPException(status_code=503, detail="Agent loop not running")

    if not loop._plan_mode:
        raise HTTPException(
            status_code=409,
            detail="Not in plan mode.",
        )

    try:
        loop.reject_plan()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    logger.info("Plan rejected via API — remaining in plan mode")

    return PlanActionResponse(
        success=True,
        message="Plan rejected. Revise and resubmit with /api/nexus/plan/submit.",
    )


@router.get("/plan/status", response_model=PlanStatusResponse)
async def get_plan_status():
    """Get the current plan mode status, including any submitted plan content."""
    loop = _get_agent_loop()
    if loop is None:
        return PlanStatusResponse(
            plan_mode=False,
            plan_content=None,
            plan_approved=False,
            permission_mode="auto",
        )

    status = loop.get_plan_status()
    return PlanStatusResponse(**status)


@router.post("/plan/exit", response_model=PlanActionResponse)
async def exit_plan_mode():
    """Exit plan mode without approving a plan.

    Restores the previous permission mode and discards any submitted plan.
    """
    loop = _get_agent_loop()
    if loop is None:
        raise HTTPException(status_code=503, detail="Agent loop not running")

    if not loop._plan_mode:
        raise HTTPException(
            status_code=409,
            detail="Not in plan mode.",
        )

    loop.exit_plan_mode()
    logger.info("Plan mode exited via API (no approval)")

    return PlanActionResponse(
        success=True,
        message="Exited plan mode. Full tool access restored.",
    )

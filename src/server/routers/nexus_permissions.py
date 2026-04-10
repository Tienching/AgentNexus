# -*- coding: utf-8 -*-
"""Runtime permission mode management API.

Endpoints:
  - GET  /api/nexus/permissions         — current permission mode and stats
  - PUT  /api/nexus/permissions/mode    — change the permission mode
  - POST /api/nexus/permissions/cache/clear — clear the permission cache
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


# ---------------------------------------------------------------------------
# Helper — get the permission gate from the running agent loop
# ---------------------------------------------------------------------------

def _get_permission_gate():
    """Get the active PermissionGate from the server's agent loop.

    The agent loop is stored on the app state during startup.
    Returns None if the loop is not running.
    """
    # Import here to avoid circular imports
    from ..app import get_agent_loop
    loop = get_agent_loop()
    if loop is None:
        return None
    return loop.permission_gate


# ---------------------------------------------------------------------------
# Routes
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
    from src.nanobot.agent.permissions import PermissionMode

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

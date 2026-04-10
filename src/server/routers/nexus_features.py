# -*- coding: utf-8 -*-
"""Nexus Feature Flags API Router

Provides REST API endpoints for feature flag management:
- List all feature flags with resolved values
- Get a single flag's resolved value
- Set a runtime override (persisted to DB)
- Reset a flag to its default (remove override)
- Reload flags from DB
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..logger import get_logger
from ..services.feature_flags import get_feature_flag_service, BUILTIN_FLAGS
from .nexus_auth import verify_nexus_auth
from .nexus_models import SuccessResponse

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-features"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ============ Response Models ============

class FlagInfo(BaseModel):
    """Single feature flag info."""
    name: str
    description: str
    category: str
    flag_type: str
    default_value: Any
    value: Any
    source: str  # "env_override" | "db_override" | "config" | "default"
    stable: bool
    overridden: bool


class FeatureFlagsListResponse(BaseModel):
    """Response model for listing feature flags."""
    flags: List[FlagInfo]
    total: int
    categories: List[str]


class SetFlagOverrideRequest(BaseModel):
    """Request model for setting a flag override."""
    value: Any = Field(..., description="Override value for the flag")
    updated_by: str = Field(default="api", description="Identifier of who made the change")


# ============ List Feature Flags ============

@router.get("/features", response_model=FeatureFlagsListResponse)
async def list_feature_flags(
    category: Optional[str] = None,
):
    """List all feature flags with their resolved values.

    - **category**: Optional filter by flag category (capability, tool, ui, integration, performance)
    """
    svc = get_feature_flag_service()
    flags = svc.list_flags()

    if category:
        flags = [f for f in flags if f["category"] == category]

    categories = sorted(set(f["category"] for f in svc.list_flags()))

    return FeatureFlagsListResponse(
        flags=[FlagInfo(**f) for f in flags],
        total=len(flags),
        categories=categories,
    )


# ============ Get Single Feature Flag ============

@router.get("/features/{flag_name}", response_model=FlagInfo)
async def get_feature_flag(flag_name: str):
    """Get a single feature flag's resolved value and metadata.

    - **flag_name**: The flag name to look up
    """
    svc = get_feature_flag_service()
    flag = svc.get_flag(flag_name)
    if not flag:
        raise HTTPException(status_code=404, detail=f"Feature flag not found: {flag_name}")
    return FlagInfo(**flag)


# ============ Set Feature Flag Override ============

@router.patch("/features/{flag_name}", response_model=FlagInfo)
async def set_feature_flag_override(
    flag_name: str,
    request: SetFlagOverrideRequest,
):
    """Set a runtime override for a feature flag.

    The override is persisted to the database and survives server restarts.
    To remove the override, use the reset endpoint.

    - **flag_name**: The flag name to override
    - **value**: The override value
    """
    svc = get_feature_flag_service()

    # Validate flag exists
    if flag_name not in BUILTIN_FLAGS:
        raise HTTPException(status_code=404, detail=f"Feature flag not found: {flag_name}")

    # Validate value type
    flag_def = BUILTIN_FLAGS[flag_name]
    if flag_def.flag_type.value == "boolean" and not isinstance(request.value, bool):
        # Allow int 0/1 as boolean for convenience
        if isinstance(request.value, int) and request.value in (0, 1):
            request.value = bool(request.value)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Flag '{flag_name}' expects a boolean value, got {type(request.value).__name__}",
            )

    ok = svc.set_override(flag_name, request.value, updated_by=request.updated_by)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save flag override")

    # Record audit event
    from .nexus_admin import record_audit_event
    record_audit_event(
        "feature_flag_set",
        actor=request.updated_by,
        detail={"flag": flag_name, "value": request.value},
    )

    flag = svc.get_flag(flag_name)
    return FlagInfo(**flag)


# ============ Reset Feature Flag Override ============

@router.post("/features/{flag_name}/reset", response_model=FlagInfo)
async def reset_feature_flag_override(flag_name: str):
    """Remove a runtime override so the flag reverts to its default.

    - **flag_name**: The flag name to reset
    """
    svc = get_feature_flag_service()

    if flag_name not in BUILTIN_FLAGS:
        raise HTTPException(status_code=404, detail=f"Feature flag not found: {flag_name}")

    ok = svc.reset_override(flag_name)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to reset flag override")

    # Record audit event
    from .nexus_admin import record_audit_event
    record_audit_event(
        "feature_flag_reset",
        actor="api",
        detail={"flag": flag_name},
    )

    flag = svc.get_flag(flag_name)
    return FlagInfo(**flag)


# ============ Reload Feature Flags ============

@router.post("/features/reload", response_model=SuccessResponse)
async def reload_feature_flags():
    """Force reload feature flags from the database.

    Useful after external database changes.
    """
    svc = get_feature_flag_service()
    svc.reload()
    return SuccessResponse(message="Feature flags reloaded from database")

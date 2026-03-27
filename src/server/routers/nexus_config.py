# -*- coding: utf-8 -*-
"""Nexus Config API Router

Provides REST API endpoints for server configuration:
- Server defaults (exec_user, default_provider, etc.)
- Concurrency configuration (global + per-provider limits)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..logger import get_logger
from .nexus_auth import verify_nexus_auth
from .nexus_models import (
    SuccessResponse,
    ServerDefaultsResponse,
    ConcurrencyConfigResponse,
    SetProviderConcurrencyRequest,
    SetGlobalConcurrencyRequest,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-config"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ============ Server Defaults API ============


@router.get("/defaults", response_model=ServerDefaultsResponse)
async def get_server_defaults():
    """Return .env default configuration values for the UI to use as initial defaults."""
    return ServerDefaultsResponse(
        exec_user=settings.exec_user or "",
        default_provider=settings.default_provider or "",
        default_alias=settings.default_alias or "",
        default_exec_user=settings.default_exec_user or "",
    )


# ============ Concurrency Config API ============


@router.get("/concurrency", response_model=ConcurrencyConfigResponse)
async def get_concurrency_config():
    """Get the current concurrency configuration."""
    from src.runtime.stores.concurrency_config import get_concurrency_config_store
    store = get_concurrency_config_store()
    cfg = store.get_all()
    return ConcurrencyConfigResponse(**cfg)


@router.post("/concurrency/provider", response_model=SuccessResponse)
async def set_provider_concurrency(request: SetProviderConcurrencyRequest):
    """Set max concurrency for a provider or alias."""
    from src.runtime.stores.concurrency_config import get_concurrency_config_store
    from src.runtime.execution.task_executor import get_executor

    store = get_concurrency_config_store()
    name = (request.name or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    try:
        ok = store.set_provider_concurrency(name, request.limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not ok:
        raise HTTPException(status_code=500, detail="Failed to set provider concurrency")

    # Hot-reload
    executor = get_executor()
    if executor:
        executor.set_provider_concurrency(name, request.limit)

    return SuccessResponse(message=f"Provider '{name}' concurrency set to {request.limit}")


@router.delete("/concurrency/provider/{name}", response_model=SuccessResponse)
async def remove_provider_concurrency(name: str):
    """Remove concurrency limit for a provider or alias."""
    from src.runtime.stores.concurrency_config import get_concurrency_config_store
    from src.runtime.execution.task_executor import get_executor

    store = get_concurrency_config_store()
    name = (name or "").strip().lower()
    store.remove_provider_concurrency(name)

    executor = get_executor()
    if executor:
        executor.set_provider_concurrency(name, 0)

    return SuccessResponse(message=f"Provider '{name}' concurrency limit removed")


@router.post("/concurrency/global", response_model=SuccessResponse)
async def set_global_concurrency(request: SetGlobalConcurrencyRequest):
    """Set global max concurrency (0 = unlimited)."""
    from src.runtime.stores.concurrency_config import get_concurrency_config_store
    from src.runtime.execution.task_executor import get_executor

    store = get_concurrency_config_store()
    try:
        ok = store.set_global_concurrency(request.limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not ok:
        raise HTTPException(status_code=500, detail="Failed to set global concurrency")

    executor = get_executor()
    if executor:
        executor.set_global_concurrency(request.limit)

    return SuccessResponse(message=f"Global concurrency set to {request.limit}")

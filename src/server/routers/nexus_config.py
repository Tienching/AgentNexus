# -*- coding: utf-8 -*-
"""Nexus Config API Router

Provides REST API endpoints for server configuration:
- Server defaults (exec_user, default_provider, etc.)
- Concurrency configuration (global + per-provider limits)
- Setup/onboarding readiness checks for the UI wizard
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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


class SetupCheckItem(BaseModel):
    name: str
    status: str
    message: str
    detail: Dict[str, Any] = Field(default_factory=dict)
    required: bool = False
    retryable: bool = False


class SetupReadinessResponse(BaseModel):
    ready: bool
    backend: str = "sqlite"
    checks: List[SetupCheckItem] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    total_required: int = 0
    passed_required: int = 0


# ============ Server Defaults API ============


@router.get("/defaults", response_model=ServerDefaultsResponse)
async def get_server_defaults():
    """Return .env default configuration values for the UI to use as initial defaults."""
    return ServerDefaultsResponse(
        exec_user=settings.exec_user or "",
        default_provider=settings.default_provider or "",
        current_workdir=os.getcwd(),
    )


# ============ Concurrency Config API ============


@router.get("/concurrency", response_model=ConcurrencyConfigResponse)
async def get_concurrency_config():
    """Get the current concurrency configuration."""
    from src.runtime.stores.concurrency_config import get_concurrency_config_store
    store = get_concurrency_config_store()
    cfg = store.get_all()
    return ConcurrencyConfigResponse(**cfg)


@router.get("/setup/readiness", response_model=SetupReadinessResponse)
async def get_setup_readiness():
    """Return a readiness snapshot for onboarding/setup UI."""
    from src.runtime.stores.db import get_db

    checks: List[SetupCheckItem] = []
    next_steps: List[str] = []

    try:
        db = get_db()
        db.execute_fetchone("SELECT 1")
        checks.append(
            SetupCheckItem(
                name="SQLite database",
                status="ready",
                message=f"Connected to {db.db_path}",
                detail={"db_path": db.db_path},
                required=True,
            )
        )
    except Exception as exc:
        checks.append(
            SetupCheckItem(
                name="SQLite database",
                status="blocked",
                message=f"SQLite unavailable: {exc}",
                detail={"error": str(exc), "hint": "Check NEXUS_DB_PATH and file permissions."},
                required=True,
                retryable=True,
            )
        )
        next_steps.append("Fix SQLite connectivity or permissions before starting tasks.")

    cli_command = (settings.cli_command or "").strip()
    cli_path = shutil.which(cli_command) if cli_command else None
    if cli_path:
        checks.append(
            SetupCheckItem(
                name="Provider CLI",
                status="ready",
                message=f"Found CLI command: {cli_command}",
                detail={"command": cli_command, "path": cli_path},
                required=True,
            )
        )
    else:
        checks.append(
            SetupCheckItem(
                name="Provider CLI",
                status="blocked",
                message=f"CLI command not found: {cli_command or 'unset'}",
                detail={"command": cli_command or "", "hint": "Install the provider CLI or update CLI_COMMAND."},
                required=True,
                retryable=True,
            )
        )
        next_steps.append("Install the provider CLI or update CLI_COMMAND in .env.")

    exec_user = (settings.exec_user or os.environ.get("EXEC_USER") or "").strip()
    home_base = settings.user_home_base or "/home"
    user_home = Path(home_base) / (exec_user or "ubuntu")
    if exec_user and user_home.exists():
        checks.append(
            SetupCheckItem(
                name="Workspace home",
                status="ready",
                message=f"User home available: {user_home}",
                detail={"path": str(user_home)},
            )
        )
    else:
        checks.append(
            SetupCheckItem(
                name="Workspace home",
                status="warning",
                message=f"User home not found yet: {user_home}",
                detail={"path": str(user_home), "hint": "Create the execution user home or update USER_HOME_BASE."},
                retryable=True,
            )
        )

    redis_host = (os.environ.get("REDIS_HOST") or "localhost").strip()
    if redis_host in {"localhost", "127.0.0.1", "::1"}:
        checks.append(
            SetupCheckItem(
                name="Redis (optional)",
                status="ready",
                message=f"Optional Redis is configured locally at {redis_host}",
                detail={"host": redis_host, "optional": True},
            )
        )
    else:
        checks.append(
            SetupCheckItem(
                name="Redis (optional)",
                status="warning",
                message=f"Redis is remote at {redis_host} and should be authenticated",
                detail={
                    "host": redis_host,
                    "optional": True,
                    "hint": "Redis is optional; SQLite remains the primary backend.",
                },
                retryable=True,
            )
        )

    required_checks = [check for check in checks if check.required]
    passed_required = sum(1 for check in required_checks if check.status == "ready")
    ready = passed_required == len(required_checks)

    if ready:
        next_steps.append("Open Nexus and create your first task.")

    return SetupReadinessResponse(
        ready=ready,
        backend="sqlite",
        checks=checks,
        next_steps=next_steps,
        total_required=len(required_checks),
        passed_required=passed_required,
    )


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

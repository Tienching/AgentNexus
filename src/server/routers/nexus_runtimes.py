# -*- coding: utf-8 -*-
"""Agent runtimes detection endpoint.

Ported from mission-control:
  - GET /api/agent-runtimes  (src/lib/agent-runtimes.ts, commit 14f34d1)

Detects installed CLI agent runtimes, their versions and auth status.
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..logger import get_logger
from ..services.agent_runtimes import (
    RuntimeStatus as _RuntimeStatus,
    RuntimeDaemon,
    get_runtime_daemon_registry,
    detect_all_runtimes,
    detect_runtime,
)
from ..services.domain_events import record_domain_event
from ..services.task_storage import get_task_queue
from ..services.stale_task_watchdog import requeue_stale_tasks
from .nexus_auth import verify_nexus_auth

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-admin"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class RuntimeStatusResponse(BaseModel):
    id: str
    name: str
    description: str
    installed: bool
    version: Optional[str] = None
    binary_path: Optional[str] = None
    auth_required: bool
    auth_hint: str
    authenticated: bool


class RuntimesResponse(BaseModel):
    runtimes: List[RuntimeStatusResponse]
    total: int
    installed_count: int


class RuntimeDaemonResponse(BaseModel):
    daemon_id: str
    runtime_id: str
    device_name: str = ""
    cli_version: Optional[str] = None
    provider_version: Optional[str] = None
    status: str = "idle"
    health_endpoint: Optional[str] = None
    pending_operations: int = 0
    last_heartbeat: float
    last_health_check: float
    metadata: dict = Field(default_factory=dict)
    created_at: float
    updated_at: float


class RuntimeDaemonListResponse(BaseModel):
    daemons: List[RuntimeDaemonResponse] = Field(default_factory=list)
    total: int = 0


class RuntimeDaemonRegisterRequest(BaseModel):
    daemon_id: str
    runtime_id: str
    device_name: str = ""
    cli_version: Optional[str] = None
    provider_version: Optional[str] = None
    status: str = "idle"
    health_endpoint: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class RuntimeDaemonHeartbeatRequest(BaseModel):
    status: Optional[str] = None
    pending_operations: Optional[int] = None
    metadata: dict = Field(default_factory=dict)


class RuntimeDaemonHealthRequest(BaseModel):
    status: Optional[str] = None
    health_endpoint: Optional[str] = None
    pending_operations: Optional[int] = None
    metadata: dict = Field(default_factory=dict)



class RuntimeSweepResponse(BaseModel):
    offline_daemons: List[RuntimeDaemonResponse] = Field(default_factory=list)
    offline_count: int = 0
    requeued_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0
    message: str = ""

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/agent-runtimes", response_model=RuntimesResponse)
async def get_agent_runtimes(
    runtime_id: Optional[str] = Query(None, description="Detect a specific runtime only"),
):
    """Detect installed agent runtimes.

    Ported from mission-control GET /api/agent-runtimes (src/lib/agent-runtimes.ts).
    Checks for installed CLI tools (claude, codex, gemini, codebuddy, nanobot),
    their versions, and authentication status.
    """
    loop = asyncio.get_event_loop()

    if runtime_id:
        status = await loop.run_in_executor(None, detect_runtime, runtime_id)
        runtimes = [status]
    else:
        runtimes = await loop.run_in_executor(None, detect_all_runtimes)

    items = [
        RuntimeStatusResponse(
            id=r.id,
            name=r.name,
            description=r.description,
            installed=r.installed,
            version=r.version,
            binary_path=r.binary_path,
            auth_required=r.auth_required,
            auth_hint=r.auth_hint,
            authenticated=r.authenticated,
        )
        for r in runtimes
    ]

    return RuntimesResponse(
        runtimes=items,
        total=len(items),
        installed_count=sum(1 for r in items if r.installed),
    )


def _daemon_to_response(daemon: RuntimeDaemon) -> RuntimeDaemonResponse:
    return RuntimeDaemonResponse(**daemon.to_dict())


@router.post("/runtimes/daemons/register", response_model=RuntimeDaemonResponse, status_code=201)
async def register_runtime_daemon(request: RuntimeDaemonRegisterRequest):
    """Register a runtime daemon/host instance in the control-plane registry."""
    reg = get_runtime_daemon_registry()
    daemon = reg.register_daemon(
        daemon_id=request.daemon_id,
        runtime_id=request.runtime_id,
        device_name=request.device_name,
        cli_version=request.cli_version,
        provider_version=request.provider_version,
        status=request.status,
        health_endpoint=request.health_endpoint,
        metadata=request.metadata,
    )
    return _daemon_to_response(daemon)


@router.post("/runtimes/daemons/{daemon_id}/heartbeat", response_model=RuntimeDaemonResponse)
async def runtime_daemon_heartbeat(daemon_id: str, request: RuntimeDaemonHeartbeatRequest):
    """Record a daemon heartbeat and update lightweight operational state."""
    reg = get_runtime_daemon_registry()
    daemon = reg.record_daemon_heartbeat(
        daemon_id,
        status=request.status,
        pending_operations=request.pending_operations,
        metadata=request.metadata,
    )
    if not daemon:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Daemon not found: {daemon_id}")
    return _daemon_to_response(daemon)


@router.post("/runtimes/daemons/{daemon_id}/health", response_model=RuntimeDaemonResponse)
async def runtime_daemon_health(daemon_id: str, request: RuntimeDaemonHealthRequest):
    """Update daemon health status and last health-check timestamp."""
    reg = get_runtime_daemon_registry()
    daemon = reg.update_daemon_health(
        daemon_id,
        status=request.status,
        health_endpoint=request.health_endpoint,
        pending_operations=request.pending_operations,
        metadata=request.metadata,
    )
    if not daemon:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Daemon not found: {daemon_id}")
    return _daemon_to_response(daemon)


@router.get("/runtimes/daemons", response_model=RuntimeDaemonListResponse)
async def list_runtime_daemons(
    runtime_id: Optional[str] = Query(None, description="Filter by runtime id"),
    status: Optional[str] = Query(None, description="Filter by daemon status"),
):
    reg = get_runtime_daemon_registry()
    daemons = reg.list_daemons(runtime_id=runtime_id, status=status)
    return RuntimeDaemonListResponse(
        daemons=[_daemon_to_response(d) for d in daemons],
        total=len(daemons),
    )


@router.get("/runtimes/daemons/{daemon_id}", response_model=RuntimeDaemonResponse)
async def get_runtime_daemon(daemon_id: str):
    reg = get_runtime_daemon_registry()
    daemon = reg.get_daemon(daemon_id)
    if not daemon:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Daemon not found: {daemon_id}")
    return _daemon_to_response(daemon)


@router.post("/runtimes/sweep/stale", response_model=RuntimeSweepResponse)
async def sweep_stale_runtime_state(
    stale_after_seconds: float = Query(120.0, ge=1.0, le=86400.0),
    task_stale_after_seconds: float = Query(600.0, ge=1.0, le=86400.0),
    exec_user: str = Query("default", description="Exec user scope for task requeue sweep"),
):
    """Sweep stale runtime daemons and requeue/fail stale in-progress tasks."""
    reg = get_runtime_daemon_registry()
    offline_daemons = reg.reap_stale_daemons(stale_after_seconds=stale_after_seconds)

    queue = get_task_queue(exec_user)
    task_result = requeue_stale_tasks(
        queue,
        stale_threshold_seconds=int(task_stale_after_seconds),
    )

    for daemon in offline_daemons:
        record_domain_event(
            "runtime.daemon.offline",
            "runtime_daemon",
            daemon.daemon_id,
            actor="runtime-sweeper",
            payload={"runtime_id": daemon.runtime_id, "status": daemon.status},
            runtime_id=daemon.daemon_id,
        )

    record_domain_event(
        "runtime.sweep.completed",
        "runtime_sweeper",
        exec_user or "default",
        actor="runtime-sweeper",
        payload={
            "offline_count": len(offline_daemons),
            "requeued": int(task_result.get("requeued") or 0),
            "failed": int(task_result.get("failed") or 0),
            "skipped": int(task_result.get("skipped") or 0),
        },
    )

    return RuntimeSweepResponse(
        offline_daemons=[_daemon_to_response(d) for d in offline_daemons],
        offline_count=len(offline_daemons),
        requeued_tasks=int(task_result.get("requeued") or 0),
        failed_tasks=int(task_result.get("failed") or 0),
        skipped_tasks=int(task_result.get("skipped") or 0),
        message=str(task_result.get("message") or ""),
    )

# -*- coding: utf-8 -*-
"""Nexus Teleport API Router — REST endpoints for teleport/remote execution.

Provides HTTP endpoints for connecting to remote execution environments,
executing tasks, streaming output, and synchronizing state.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..routers.nexus_auth import verify_nexus_auth
from ..services.teleport_bridge import TeleportBridge
from ..logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus/teleport",
    tags=["nexus-teleport"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ── Request/Response Models ────────────────────────────────────────


class TeleportConnectRequest(BaseModel):
    """Request body for connecting to a remote environment."""

    remote_url: str = Field(..., description="URL of the remote agent-nexus endpoint")
    credentials: dict = Field(default_factory=dict, description="Auth credentials for the remote endpoint")
    metadata: dict = Field(default_factory=dict, description="Additional session metadata")


class TeleportExecuteRequest(BaseModel):
    """Request body for executing a task on a remote environment."""

    session_id: str = Field(..., description="Teleport session ID to execute on")
    task: str = Field(..., description="Task description/command to execute")
    metadata: dict = Field(default_factory=dict, description="Additional task metadata")


class TeleportDisconnectRequest(BaseModel):
    """Request body for disconnecting a remote session."""

    session_id: str = Field(..., description="Teleport session ID to disconnect")


class TeleportSyncRequest(BaseModel):
    """Request body for syncing state with a remote environment."""

    session_id: str = Field(..., description="Teleport session ID to sync")


class TeleportSessionResponse(BaseModel):
    """Response model for a teleport session."""

    id: str
    remote_url: str
    status: str
    connected_at: float
    last_heartbeat: float
    metadata: dict = Field(default_factory=dict)


class TeleportResultResponse(BaseModel):
    """Response model for a remote execution result."""

    session_id: str
    task_id: str
    status: str
    output: str = ""
    exit_code: Optional[int] = None
    artifacts: list[str] = Field(default_factory=list)


class TeleportSyncResponse(BaseModel):
    """Response model for a sync operation."""

    session_id: str
    synced_tasks: int = 0
    synced_files: list[str] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)


class TeleportActionResponse(BaseModel):
    """Generic action response."""

    ok: bool
    message: str


class TeleportSessionsListResponse(BaseModel):
    """Response model for listing sessions."""

    sessions: list[TeleportSessionResponse]
    count: int


# ── Helpers ────────────────────────────────────────────────────────


def _get_bridge() -> TeleportBridge:
    """Get TeleportBridge singleton."""
    return TeleportBridge.get_instance()


# ── Endpoints ──────────────────────────────────────────────────────


@router.post("/connect", response_model=TeleportSessionResponse)
async def connect_remote(req: TeleportConnectRequest):
    """Connect to a remote execution environment."""
    bridge = _get_bridge()
    try:
        session = await bridge.connect(
            remote_url=req.remote_url,
            credentials=req.credentials,
            metadata=req.metadata,
        )
        return TeleportSessionResponse(**session.to_dict())
    except Exception as e:
        logger.error(f"Teleport connect failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e))


@router.post("/disconnect", response_model=TeleportActionResponse)
async def disconnect_remote(req: TeleportDisconnectRequest):
    """Disconnect a remote session."""
    bridge = _get_bridge()
    ok = await bridge.disconnect(req.session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Session {req.session_id} not found")
    return TeleportActionResponse(ok=True, message=f"Session {req.session_id} disconnected")


@router.post("/execute", response_model=TeleportResultResponse)
async def execute_remote(req: TeleportExecuteRequest):
    """Execute a task on a remote environment."""
    bridge = _get_bridge()
    try:
        result = await bridge.execute_remote(
            session_id=req.session_id,
            task=req.task,
            task_metadata=req.metadata,
        )
        return TeleportResultResponse(**result.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Teleport execute failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e))


@router.get("/sessions", response_model=TeleportSessionsListResponse)
async def list_sessions():
    """List all teleport sessions."""
    bridge = _get_bridge()
    sessions = bridge.list_sessions()
    return TeleportSessionsListResponse(
        sessions=[TeleportSessionResponse(**s.to_dict()) for s in sessions],
        count=len(sessions),
    )


@router.get("/sessions/{session_id}", response_model=TeleportSessionResponse)
async def get_session(session_id: str):
    """Get details of a specific teleport session."""
    bridge = _get_bridge()
    session = bridge.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return TeleportSessionResponse(**session.to_dict())


@router.post("/sync", response_model=TeleportSyncResponse)
async def sync_state(req: TeleportSyncRequest):
    """Synchronize state with a remote environment."""
    bridge = _get_bridge()
    try:
        result = await bridge.sync_state(req.session_id)
        return TeleportSyncResponse(**result.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Teleport sync failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}/output")
async def stream_output(session_id: str):
    """Stream output from a remote session (SSE)."""
    bridge = _get_bridge()
    session = bridge.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    async def event_generator():
        try:
            async for chunk in bridge.stream_output(session_id):
                yield f"data: {chunk}\n\n"
        except ValueError:
            yield f"data: {{'error': 'Session not found'}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

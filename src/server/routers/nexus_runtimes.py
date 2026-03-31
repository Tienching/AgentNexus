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
from pydantic import BaseModel

from ..logger import get_logger
from ..services.agent_runtimes import (
    RuntimeStatus as _RuntimeStatus,
    detect_all_runtimes,
    detect_runtime,
)
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

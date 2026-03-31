# -*- coding: utf-8 -*-
"""Agent Run Protocol v1 API Router

Provides REST API endpoints per the agent-run protocol spec.
Ported from mission-control src/app/api/v1/runs/* (commit d4f55dd).

Endpoints:
  GET  /api/v1/runs                  — list runs (filtered)
  POST /api/v1/runs                  — report a new run
  GET  /api/v1/runs/{run_id}         — single run detail
  GET  /api/v1/runs/{run_id}/provenance — provenance record
  PUT  /api/v1/runs/{run_id}/eval    — attach eval result
  GET  /api/v1/evals/leaderboard     — eval leaderboard
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from .nexus_auth import verify_nexus_auth
from ..services.run_service import (
    RunService,
    get_run_service,
    VALID_STATUSES,
    VALID_OUTCOMES,
    _PROTOCOL_VERSION,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["agent-runs"],
    dependencies=[Depends(verify_nexus_auth)],
)

_PROTOCOL_HEADER = {"X-Agent-Run-Protocol": _PROTOCOL_VERSION}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CostPayload(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: Optional[int] = None
    cache_write_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    model: Optional[str] = None


class ProvenancePayload(BaseModel):
    run_hash: Optional[str] = None
    parent_run_hash: Optional[str] = None
    lineage: Optional[List[str]] = None
    model_version: Optional[str] = None
    config_hash: Optional[str] = None
    runtime: Optional[str] = None
    signed_by: Optional[str] = None
    signature: Optional[str] = None
    created_at: Optional[str] = None


class EvalPayload(BaseModel):
    task_type: Optional[str] = None
    eval_layer: Optional[str] = None
    pass_: bool = Field(..., alias="pass")
    score: float
    expected_outcome: Optional[str] = None
    actual_outcome: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    regression_from: Optional[str] = None
    detail: Optional[str] = None
    benchmark_id: Optional[str] = None

    model_config = {"populate_by_name": True}


class CreateRunRequest(BaseModel):
    agent_id: str
    agent_name: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    runtime: Optional[str] = None
    runtime_version: Optional[str] = None
    trigger: Optional[str] = None
    parent_run_id: Optional[str] = None
    task_id: Optional[str] = None
    status: str = "pending"
    outcome: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_ms: Optional[int] = None
    steps: Optional[List[Dict[str, Any]]] = None
    tools_available: Optional[List[str]] = None
    cost: Optional[CostPayload] = None
    provenance: Optional[ProvenancePayload] = None
    eval: Optional[EvalPayload] = None
    error: Optional[str] = None
    git_branch: Optional[str] = None
    git_commit: Optional[str] = None
    workspace_id: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class UpdateRunRequest(BaseModel):
    status: Optional[str] = None
    outcome: Optional[str] = None
    ended_at: Optional[str] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    git_branch: Optional[str] = None
    git_commit: Optional[str] = None
    steps: Optional[List[Dict[str, Any]]] = None
    cost: Optional[CostPayload] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _svc(exec_user: str = settings.exec_user) -> RunService:
    return get_run_service(exec_user)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/runs")
async def list_runs(
    agent_id: Optional[str] = Query(None, description="Filter by agent_id"),
    status: Optional[str] = Query(None, description="Filter by status"),
    since: Optional[str] = Query(None, description="ISO-8601 lower bound for started_at"),
    task_id: Optional[str] = Query(None, description="Filter by task_id"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    exec_user: str = Query(settings.exec_user, description="Exec user namespace"),
):
    """List agent runs with optional filtering.

    Mirrors GET /api/v1/runs from mission-control (commit d4f55dd).
    """
    if status and status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    try:
        result = _svc(exec_user).list_runs(
            agent_id=agent_id,
            status=status,
            since=since,
            task_id=task_id,
            limit=limit,
            offset=offset,
        )
        return result
    except Exception as e:
        logger.error(f"Failed to list runs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list runs")


@router.post("/runs", status_code=201)
async def create_run(
    body: CreateRunRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user namespace"),
):
    """Report a new agent run.

    Returns {id, run_hash} on success.
    Mirrors POST /api/v1/runs from mission-control (commit d4f55dd).
    """
    if body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")
    if body.outcome and body.outcome not in VALID_OUTCOMES:
        raise HTTPException(status_code=400, detail=f"Invalid outcome: {body.outcome}")

    run_dict = body.model_dump(by_alias=True, exclude_none=True)
    # Flatten nested pydantic sub-objects back to plain dicts
    if "cost" in run_dict and isinstance(run_dict["cost"], dict):
        pass  # already a dict from model_dump
    if "provenance" in run_dict and isinstance(run_dict["provenance"], dict):
        pass
    if "eval" in run_dict and isinstance(run_dict["eval"], dict):
        # Rename pass_ back to pass for internal use
        ev = run_dict["eval"]
        if "pass_" in ev:
            ev["pass"] = ev.pop("pass_")

    try:
        run = _svc(exec_user).create_run(run_dict)
        return {
            "id": run["id"],
            "run_hash": (run.get("provenance") or {}).get("run_hash", ""),
        }
    except Exception as e:
        logger.error(f"Failed to create run: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create run")


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    exec_user: str = Query(settings.exec_user, description="Exec user namespace"),
):
    """Get a single run with full detail.

    Mirrors GET /api/v1/runs/:id from mission-control.
    """
    run = _svc(exec_user).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return run


@router.get("/runs/{run_id}/provenance")
async def get_run_provenance(
    run_id: str,
    exec_user: str = Query(settings.exec_user, description="Exec user namespace"),
):
    """Get the provenance record for a run.

    Mirrors GET /api/v1/runs/:id/provenance from mission-control.
    """
    run = _svc(exec_user).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return run.get("provenance") or {}


@router.put("/runs/{run_id}")
async def update_run(
    run_id: str,
    body: UpdateRunRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user namespace"),
):
    """Update run status, outcome, cost, or steps.

    Mirrors PUT /api/v1/runs/:id from mission-control.
    """
    if body.status and body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")
    if body.outcome and body.outcome not in VALID_OUTCOMES:
        raise HTTPException(status_code=400, detail=f"Invalid outcome: {body.outcome}")

    updates = body.model_dump(exclude_none=True)
    try:
        run = _svc(exec_user).update_run(run_id, updates)
    except Exception as e:
        logger.error(f"Failed to update run {run_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update run")

    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return run


@router.put("/runs/{run_id}/eval")
async def attach_eval(
    run_id: str,
    body: EvalPayload,
    exec_user: str = Query(settings.exec_user, description="Exec user namespace"),
):
    """Attach eval results to a run.

    Mirrors PUT /api/v1/runs/:id/eval from mission-control.
    """
    eval_dict = body.model_dump(by_alias=True, exclude_none=True)
    if "pass_" in eval_dict:
        eval_dict["pass"] = eval_dict.pop("pass_")

    try:
        run = _svc(exec_user).attach_eval(run_id, eval_dict)
    except Exception as e:
        logger.error(f"Failed to attach eval to run {run_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to attach eval")

    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return run


@router.get("/evals/leaderboard")
async def get_leaderboard(
    benchmark_id: Optional[str] = Query(None, description="Filter by benchmark_id"),
    limit: int = Query(50, ge=1, le=200, description="Max entries"),
    exec_user: str = Query(settings.exec_user, description="Exec user namespace"),
):
    """Return eval leaderboard ranked by avg_score DESC.

    Mirrors GET /api/v1/evals/leaderboard from mission-control.
    """
    try:
        rows = _svc(exec_user).get_leaderboard(benchmark_id=benchmark_id, limit=limit)
        return {"leaderboard": rows, "total": len(rows)}
    except Exception as e:
        logger.error(f"Failed to get leaderboard: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get leaderboard")

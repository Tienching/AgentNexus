"""Evolution system REST API endpoints.

Provides:
  POST /api/nexus/evolution/trigger   — trigger an evolution session now
  POST /api/nexus/evolution/synthesis — trigger memory synthesis now
  GET  /api/nexus/evolution/status    — get current status and recent sessions
  GET  /api/nexus/evolution/memory    — get memory archive statistics
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/nexus/evolution", tags=["evolution"])


class EvolutionSessionResponse(BaseModel):
    id: str
    day: int
    date: str
    status: str
    phase: str
    tasks_planned: int
    tasks_completed: int
    tasks_failed: int
    duration_seconds: float
    error: str | None = None


class EvolutionTriggerResponse(BaseModel):
    ok: bool
    session: EvolutionSessionResponse


class EvolutionSynthesisResponse(BaseModel):
    ok: bool
    message: str


class EvolutionStatusResponse(BaseModel):
    enabled: bool
    running: bool
    evolution_in_progress: bool
    cron_expr: str
    interval_hours: int
    working_dir: str
    memory_path: str
    codebuddy_path: str
    current_session: EvolutionSessionResponse | None = None
    recent_sessions: list[EvolutionSessionResponse] = Field(default_factory=list)
    cron_jobs: dict[str, Any] = Field(default_factory=dict)


class EvolutionMemoryResponse(BaseModel):
    learnings_count: int
    social_learnings_count: int
    active_learnings_exists: bool
    active_social_learnings_exists: bool
    active_learnings_preview: str = ""
    active_social_learnings_preview: str = ""


def _get_service(request: Request):
    """Get EvolutionService from app state, raise 503 if not initialized."""
    svc = getattr(request.app.state, "evolution_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail="Evolution service is not running. Set EVOLUTION_ENABLED=true to enable it.",
        )
    return svc


def _to_session_response(session) -> EvolutionSessionResponse:
    return EvolutionSessionResponse(
        id=session.id,
        day=session.day,
        date=session.date,
        status=session.status,
        phase=session.phase,
        tasks_planned=session.metrics.tasks_planned,
        tasks_completed=session.metrics.tasks_completed,
        tasks_failed=session.metrics.tasks_failed,
        duration_seconds=round(session.duration_seconds, 1),
        error=session.error,
    )


@router.post("/trigger", response_model=EvolutionTriggerResponse)
async def trigger_evolution(request: Request) -> EvolutionTriggerResponse:
    """Trigger a full evolution cycle immediately.

    Returns 409 if a session is already in progress.
    Returns 200 with session summary on completion.
    """
    svc = _get_service(request)

    if svc.is_evolution_running():
        raise HTTPException(
            status_code=409,
            detail="Evolution session already in progress. Try again later.",
        )

    session = await svc.trigger_now()
    if session is None:
        raise HTTPException(
            status_code=409,
            detail="Failed to start evolution session (possibly already running).",
        )

    return EvolutionTriggerResponse(ok=True, session=_to_session_response(session))


@router.post("/synthesis", response_model=EvolutionSynthesisResponse)
async def trigger_synthesis(request: Request) -> EvolutionSynthesisResponse:
    """Trigger memory synthesis immediately (archive → active_learnings.md)."""
    svc = _get_service(request)
    await svc.trigger_synthesis()
    return EvolutionSynthesisResponse(ok=True, message="Memory synthesis completed")


@router.get("/status", response_model=EvolutionStatusResponse)
async def get_status(request: Request) -> EvolutionStatusResponse:
    """Get current evolution system status."""
    svc = _get_service(request)
    return EvolutionStatusResponse.model_validate(svc.get_status())


@router.get("/memory", response_model=EvolutionMemoryResponse)
async def get_memory(request: Request) -> EvolutionMemoryResponse:
    """Get memory archive statistics."""
    svc = _get_service(request)
    return EvolutionMemoryResponse.model_validate(
        {
            **svc.get_memory_stats(),
            **svc.get_memory_previews(),
        }
    )

"""Evolution system REST API endpoints.

Provides:
  POST /api/nexus/evolution/trigger   — trigger an evolution session now
  POST /api/nexus/evolution/synthesis — trigger memory synthesis now
  GET  /api/nexus/evolution/status    — get current status and recent sessions
  GET  /api/nexus/evolution/memory    — get memory archive statistics
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/nexus/evolution", tags=["evolution"])


def _get_service(request: Request):
    """Get EvolutionService from app state, raise 503 if not initialized."""
    svc = getattr(request.app.state, "evolution_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail="Evolution service is not running. Set EVOLUTION_ENABLED=true to enable it.",
        )
    return svc


@router.post("/trigger")
async def trigger_evolution(request: Request):
    """Trigger a full evolution cycle immediately.

    Returns 409 if a session is already in progress.
    Returns 200 with session summary on completion.
    """
    svc = _get_service(request)

    if svc._lock.locked():
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

    return {
        "ok": True,
        "session": {
            "id": session.id,
            "day": session.day,
            "status": session.status,
            "tasks_planned": session.metrics.tasks_planned,
            "tasks_completed": session.metrics.tasks_completed,
            "tasks_failed": session.metrics.tasks_failed,
            "duration_seconds": round(session.duration_seconds, 1),
            "error": session.error,
        },
    }


@router.post("/synthesis")
async def trigger_synthesis(request: Request):
    """Trigger memory synthesis immediately (archive → active_learnings.md)."""
    svc = _get_service(request)
    await svc.trigger_synthesis()
    return {"ok": True, "message": "Memory synthesis completed"}


@router.get("/status")
async def get_status(request: Request):
    """Get current evolution system status."""
    svc = _get_service(request)
    return svc.get_status()


@router.get("/memory")
async def get_memory(request: Request):
    """Get memory archive statistics."""
    svc = _get_service(request)
    stats = svc.get_memory_stats()

    # Also include content of active files if they exist
    from pathlib import Path
    memory_path = Path(svc._config.memory_path)

    active_learnings = ""
    active_social = ""
    try:
        al_path = memory_path / "active_learnings.md"
        if al_path.exists():
            active_learnings = al_path.read_text(encoding="utf-8")[:4000]
    except Exception:
        pass

    try:
        as_path = memory_path / "active_social_learnings.md"
        if as_path.exists():
            active_social = as_path.read_text(encoding="utf-8")[:2000]
    except Exception:
        pass

    return {
        **stats,
        "active_learnings_preview": active_learnings,
        "active_social_learnings_preview": active_social,
    }

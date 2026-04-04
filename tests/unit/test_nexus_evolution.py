from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.nanobot.evolve.models import EvolutionConfig, EvolutionSession, SessionMetrics
from src.server.routers.nexus_evolution import router
from src.server.services.evolution_service import EvolutionService


class EvolutionServiceStub:
    def __init__(
        self,
        *,
        running: bool = False,
        session: EvolutionSession | None = None,
        status: dict | None = None,
        memory_stats: dict | None = None,
        memory_previews: dict | None = None,
    ):
        self._running = running
        self._session = session
        self._status = status or {
            "enabled": True,
            "running": True,
            "evolution_in_progress": False,
            "cron_expr": "0 */8 * * *",
            "interval_hours": 8,
            "working_dir": "/workspace",
            "memory_path": "/workspace/memory",
            "codebuddy_path": "codebuddy",
            "current_session": None,
            "recent_sessions": [],
            "cron_jobs": {},
        }
        self._memory_stats = memory_stats or {
            "learnings_count": 2,
            "social_learnings_count": 1,
            "active_learnings_exists": True,
            "active_social_learnings_exists": False,
        }
        self._memory_previews = memory_previews or {
            "active_learnings_preview": "active learnings",
            "active_social_learnings_preview": "",
        }
        self.synthesis_calls = 0

    def is_evolution_running(self) -> bool:
        return self._running

    async def trigger_now(self) -> EvolutionSession | None:
        return self._session

    async def trigger_synthesis(self) -> None:
        self.synthesis_calls += 1

    def get_status(self) -> dict:
        return self._status

    def get_memory_stats(self) -> dict:
        return self._memory_stats

    def get_memory_previews(self) -> dict:
        return self._memory_previews


def _build_session() -> EvolutionSession:
    session = EvolutionSession(id="session-123", day=11, date="2026-04-04")
    session.phase = "reflection"
    session.status = "completed"
    session.metrics = SessionMetrics(tasks_planned=3, tasks_completed=2, tasks_failed=1)
    session.started_at_ms = 1_000
    session.completed_at_ms = 6_400
    return session


def _build_client(service) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.evolution_service = service
    return TestClient(app)


class TestNexusEvolutionRouter:
    def test_trigger_returns_409_when_evolution_is_running(self):
        service = EvolutionServiceStub(running=True)

        with _build_client(service) as client:
            response = client.post("/api/nexus/evolution/trigger")

        assert response.status_code == 409
        assert response.json() == {
            "detail": "Evolution session already in progress. Try again later.",
        }

    def test_trigger_returns_session_payload(self):
        service = EvolutionServiceStub(session=_build_session())

        with _build_client(service) as client:
            response = client.post("/api/nexus/evolution/trigger")

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "session": {
                "id": "session-123",
                "day": 11,
                "date": "2026-04-04",
                "status": "completed",
                "phase": "reflection",
                "tasks_planned": 3,
                "tasks_completed": 2,
                "tasks_failed": 1,
                "duration_seconds": 5.4,
                "error": None,
            },
        }

    def test_synthesis_and_status_return_success_payloads(self):
        session = _build_session()
        service = EvolutionServiceStub(
            status={
                "enabled": True,
                "running": True,
                "evolution_in_progress": False,
                "cron_expr": "0 */8 * * *",
                "interval_hours": 8,
                "working_dir": "/workspace",
                "memory_path": "/workspace/memory",
                "codebuddy_path": "codebuddy",
                "current_session": {
                    "id": session.id,
                    "day": session.day,
                    "date": session.date,
                    "status": session.status,
                    "phase": session.phase,
                    "tasks_planned": session.metrics.tasks_planned,
                    "tasks_completed": session.metrics.tasks_completed,
                    "tasks_failed": session.metrics.tasks_failed,
                    "duration_seconds": session.duration_seconds,
                    "error": session.error,
                },
                "recent_sessions": [],
                "cron_jobs": {"total": 2},
            },
        )

        with _build_client(service) as client:
            synthesis_response = client.post("/api/nexus/evolution/synthesis")
            status_response = client.get("/api/nexus/evolution/status")

        assert synthesis_response.status_code == 200
        assert synthesis_response.json() == {
            "ok": True,
            "message": "Memory synthesis completed",
        }
        assert service.synthesis_calls == 1

        assert status_response.status_code == 200
        assert status_response.json() == service.get_status()

    def test_memory_returns_stats_and_previews(self):
        service = EvolutionServiceStub(
            memory_stats={
                "learnings_count": 4,
                "social_learnings_count": 2,
                "active_learnings_exists": True,
                "active_social_learnings_exists": True,
            },
            memory_previews={
                "active_learnings_preview": "latest learnings",
                "active_social_learnings_preview": "latest social learnings",
            },
        )

        with _build_client(service) as client:
            response = client.get("/api/nexus/evolution/memory")

        assert response.status_code == 200
        assert response.json() == {
            "learnings_count": 4,
            "social_learnings_count": 2,
            "active_learnings_exists": True,
            "active_social_learnings_exists": True,
            "active_learnings_preview": "latest learnings",
            "active_social_learnings_preview": "latest social learnings",
        }


class TestEvolutionServiceMemoryPreviews:
    def test_get_memory_previews_reads_safely_and_truncates(self, tmp_path: Path):
        memory_path = tmp_path / "memory"
        memory_path.mkdir()
        (memory_path / "active_learnings.md").write_text("A" * 5000, encoding="utf-8")
        (memory_path / "active_social_learnings.md").mkdir()

        service = EvolutionService(
            EvolutionConfig(
                enabled=True,
                working_dir=str(tmp_path),
                memory_path=str(memory_path),
            )
        )

        previews = service.get_memory_previews()

        assert previews == {
            "active_learnings_preview": "A" * 4000,
            "active_social_learnings_preview": "",
        }

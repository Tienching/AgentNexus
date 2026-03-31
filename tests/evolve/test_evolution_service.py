"""Integration tests for EvolutionService."""

import asyncio
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.nanobot.evolve.models import EvolutionConfig, EvolutionSession, SessionMetrics
from src.server.services.evolution_service import EvolutionService, _session_summary


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def config(tmp_dir):
    return EvolutionConfig(
        enabled=True,
        working_dir=str(tmp_dir),
        memory_path=str(tmp_dir / "memory"),
        cron_expr="0 */8 * * *",
        codebuddy_path="codebuddy",
        codebuddy_timeout=30,
    )


@pytest.fixture
def service(config):
    return EvolutionService(config)


def _make_done_session() -> EvolutionSession:
    s = EvolutionSession(id="test-abc", day=1, date="2026-01-01")
    s.status = "completed"
    s.metrics = SessionMetrics(tasks_planned=2, tasks_completed=2)
    s.started_at_ms = 1_000_000
    s.completed_at_ms = 1_060_000
    return s


class TestEvolutionServiceLifecycle:
    @pytest.mark.asyncio
    async def test_start_registers_cron_jobs(self, service):
        """start() should initialize CronService with evolution jobs."""
        await service.start()
        try:
            assert service._cron is not None
            assert service._engine is not None
            assert service._running is True

            jobs = service._cron.list_jobs()
            job_names = {j.name for j in jobs}
            assert "nexus-self-evolve" in job_names
            assert "nexus-memory-synth" in job_names
        finally:
            await service.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent_job_registration(self, service):
        """Jobs should not be duplicated on repeated start calls."""
        await service.start()
        try:
            await service.stop()
            # Re-create service with same store path
            svc2 = EvolutionService(service._config)
            await svc2.start()
            try:
                jobs = svc2._cron.list_jobs()
                evolve_jobs = [j for j in jobs if j.name == "nexus-self-evolve"]
                assert len(evolve_jobs) == 1  # Should not be duplicated
            finally:
                await svc2.stop()
        except Exception:
            await service.stop()
            raise

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self, service):
        """stop() should set _running to False and stop CronService."""
        await service.start()
        assert service._running is True
        await service.stop()
        assert service._running is False

    @pytest.mark.asyncio
    async def test_disabled_service_does_not_start(self, tmp_dir):
        """Disabled service should silently not start."""
        config = EvolutionConfig(enabled=False, working_dir=str(tmp_dir))
        svc = EvolutionService(config)
        await svc.start()
        assert svc._cron is None
        assert svc._engine is None
        assert svc._running is False


class TestEvolutionServiceTrigger:
    @pytest.mark.asyncio
    async def test_trigger_now_calls_engine(self, service):
        """trigger_now() should call engine.run_full_cycle()."""
        done_session = _make_done_session()

        with patch("src.nanobot.evolve.engine.EvolutionEngine.run_full_cycle",
                   new_callable=AsyncMock, return_value=done_session):
            session = await service.trigger_now()

        assert session is not None
        assert session.status == "completed"
        assert session.metrics.tasks_completed == 2

    @pytest.mark.asyncio
    async def test_trigger_now_blocks_concurrent(self, service):
        """trigger_now() should return None if already running."""
        done_session = _make_done_session()

        # Simulate a long-running session by holding the lock
        async def slow_cycle():
            await asyncio.sleep(0.2)
            return done_session

        with patch("src.nanobot.evolve.engine.EvolutionEngine.run_full_cycle",
                   new_callable=AsyncMock, side_effect=slow_cycle):
            # Start first session (in background)
            task = asyncio.create_task(service.trigger_now())
            await asyncio.sleep(0.05)  # Let it acquire the lock

            # Second trigger should be blocked
            result = await service.trigger_now()
            assert result is None  # Already running

            await task  # Wait for first to complete

    @pytest.mark.asyncio
    async def test_trigger_synthesis(self, service):
        """trigger_synthesis() should call engine.run_memory_synthesis()."""
        with patch("src.nanobot.evolve.engine.EvolutionEngine.run_memory_synthesis",
                   new_callable=AsyncMock) as mock_synth:
            await service.trigger_synthesis()
            mock_synth.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_history_maintained(self, service):
        """Completed sessions should appear in history."""
        done_session = _make_done_session()

        with patch("src.nanobot.evolve.engine.EvolutionEngine.run_full_cycle",
                   new_callable=AsyncMock, return_value=done_session):
            await service.trigger_now()

        assert len(service._session_history) == 1
        assert service._current_session is done_session

    @pytest.mark.asyncio
    async def test_session_history_capped_at_20(self, service):
        """Session history should not exceed 20 entries."""
        done_session = _make_done_session()

        with patch("src.nanobot.evolve.engine.EvolutionEngine.run_full_cycle",
                   new_callable=AsyncMock, return_value=done_session):
            for _ in range(25):
                await service.trigger_now()

        assert len(service._session_history) <= 20


class TestEvolutionServiceStatus:
    @pytest.mark.asyncio
    async def test_get_status_disabled(self, tmp_dir):
        config = EvolutionConfig(enabled=False, working_dir=str(tmp_dir))
        svc = EvolutionService(config)
        status = svc.get_status()
        assert status["enabled"] is False
        assert status["running"] is False

    @pytest.mark.asyncio
    async def test_get_status_running(self, service):
        await service.start()
        try:
            status = service.get_status()
            assert status["enabled"] is True
            assert status["running"] is True
            assert status["cron_expr"] == "0 */8 * * *"
            assert "cron_jobs" in status
        finally:
            await service.stop()

    @pytest.mark.asyncio
    async def test_get_memory_stats(self, service):
        stats = service.get_memory_stats()
        assert "learnings_count" in stats
        assert "social_learnings_count" in stats
        assert stats["learnings_count"] == 0


class TestSessionSummary:
    def test_none_returns_none(self):
        assert _session_summary(None) is None

    def test_session_summary_keys(self):
        session = _make_done_session()
        summary = _session_summary(session)
        assert summary is not None
        assert summary["id"] == "test-abc"
        assert summary["status"] == "completed"
        assert summary["tasks_completed"] == 2


class TestCronJobRouting:
    @pytest.mark.asyncio
    async def test_on_cron_job_evolve(self, service):
        """Evolve cron job should trigger evolution."""
        from src.nanobot.cron.types import CronJob, CronPayload, CronSchedule
        from src.nanobot.evolve.cron_jobs import EVOLVE_PAYLOAD_MSG_EVOLVE

        job = CronJob(
            id="test-job",
            name="nexus-self-evolve",
            payload=CronPayload(message=EVOLVE_PAYLOAD_MSG_EVOLVE),
            schedule=CronSchedule(kind="cron", expr="0 */8 * * *"),
        )
        done_session = _make_done_session()

        with patch("src.nanobot.evolve.engine.EvolutionEngine.run_full_cycle",
                   new_callable=AsyncMock, return_value=done_session):
            await service._on_cron_job(job)

        assert service._current_session is done_session

    @pytest.mark.asyncio
    async def test_on_cron_job_synthesis(self, service):
        """Synthesis cron job should trigger memory synthesis."""
        from src.nanobot.cron.types import CronJob, CronPayload, CronSchedule
        from src.nanobot.evolve.cron_jobs import EVOLVE_PAYLOAD_MSG_SYNTH

        job = CronJob(
            id="test-synth",
            name="nexus-memory-synth",
            payload=CronPayload(message=EVOLVE_PAYLOAD_MSG_SYNTH),
            schedule=CronSchedule(kind="cron", expr="0 12 * * *"),
        )

        with patch("src.nanobot.evolve.engine.EvolutionEngine.run_memory_synthesis",
                   new_callable=AsyncMock) as mock_synth:
            await service._on_cron_job(job)
            mock_synth.assert_called_once()

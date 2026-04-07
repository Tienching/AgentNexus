"""Evolution service — integrates EvolutionEngine with CronService and app lifecycle.

This module is the "glue" between the evolution engine (which knows how to
self-improve) and the application runtime (CronService, app.py lifespan).

Responsibilities:
  - Initialize CronService with evolution-specific jobs
  - Route cron job triggers to the correct engine method
  - Provide a manual trigger API for on-demand evolution
  - Track the current session state for status queries
  - Ensure concurrent evolution sessions cannot overlap
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from loguru import logger

from src.nanobot.cron.service import CronService
from src.nanobot.cron.types import CronJob
from src.nanobot.evolve.cron_jobs import (
    EVOLVE_PAYLOAD_MSG_EVOLVE,
    EVOLVE_PAYLOAD_MSG_SYNTH,
    get_evolution_action,
    register_evolution_jobs,
)
from src.nanobot.evolve.engine import EvolutionEngine
from src.nanobot.evolve.models import EvolutionConfig, EvolutionSession


def _now_ms() -> int:
    return int(time.time() * 1000)


class EvolutionService:
    """Manages the lifecycle of the self-evolution system.

    Usage (in app.py lifespan):
        svc = await EvolutionService.create()
        await svc.start()
        # ... app runs ...
        await svc.stop()

    Manual trigger:
        session = await svc.trigger_now()
    """

    def __init__(self, engine_config: EvolutionConfig):
        self._config = engine_config
        self._cron_store_path = Path(engine_config.working_dir) / ".nexus" / "evolve_cron.json"
        self._cron: CronService | None = None
        self._engine: EvolutionEngine | None = None
        self._running = False
        self._lock = asyncio.Lock()  # Prevents concurrent evolution sessions
        self._current_session: EvolutionSession | None = None
        self._session_history: list[EvolutionSession] = []

    @classmethod
    def create(cls) -> "EvolutionService":
        """Create an EvolutionService instance by loading config from environment."""
        config = _load_evolution_config()
        return cls(config)

    async def start(self) -> None:
        """Initialize CronService, register jobs, and start the scheduler."""
        if not self._config.enabled:
            logger.info("EvolutionService: disabled, not starting")
            return

        self._engine = EvolutionEngine(self._config)

        # Create CronService with our on_job callback
        self._cron = CronService(
            store_path=self._cron_store_path,
            on_job=self._on_cron_job,
        )

        # Register evolution cron jobs (idempotent)
        register_evolution_jobs(self._cron, _to_schema_config(self._config))

        # Start the cron scheduler
        await self._cron.start()

        self._running = True
        logger.info(
            "EvolutionService started — evolve cron='{}', synthesis cron='{}'",
            self._config.cron_expr,
            "0 12 * * *",
        )

    async def stop(self) -> None:
        """Stop the cron scheduler."""
        self._running = False
        if self._cron:
            self._cron.stop()
            logger.info("EvolutionService stopped")

    async def trigger_now(self, phase: str = "full") -> EvolutionSession | None:
        """Manually trigger an evolution cycle.

        Args:
            phase: "full" (default) runs all phases.

        Returns:
            The completed EvolutionSession, or None if already running.
        """
        if self._lock.locked():
            logger.warning("EvolutionService: evolution already in progress, skipping trigger")
            return None

        if not self._engine:
            self._engine = EvolutionEngine(self._config)

        async with self._lock:
            try:
                logger.info("EvolutionService: starting manual evolution cycle")
                session = await self._engine.run_full_cycle()
                self._current_session = session
                self._session_history.append(session)
                # Keep only last 20 sessions in memory
                self._session_history = self._session_history[-20:]
                return session
            except Exception as e:
                logger.error("EvolutionService: manual trigger failed: {}", e)
                return None

    async def trigger_synthesis(self) -> None:
        """Manually trigger memory synthesis."""
        if not self._engine:
            self._engine = EvolutionEngine(self._config)
        try:
            await self._engine.run_memory_synthesis()
        except Exception as e:
            logger.error("EvolutionService: memory synthesis failed: {}", e)

    def is_evolution_running(self) -> bool:
        """Return whether an evolution session currently holds the service lock."""
        return self._lock.locked()

    def get_status(self) -> dict[str, Any]:
        """Return current status of the evolution system."""
        return {
            "enabled": self._config.enabled,
            "running": self._running,
            "evolution_in_progress": self.is_evolution_running(),
            "cron_expr": self._config.cron_expr,
            "interval_hours": self._config.interval_hours,
            "working_dir": self._config.working_dir,
            "memory_path": self._config.memory_path,
            "codebuddy_path": self._config.codebuddy_path,
            "current_session": _session_summary(self._current_session),
            "recent_sessions": [_session_summary(s) for s in self._session_history[-5:]],
            "cron_jobs": self._cron.status() if self._cron else {},
        }

    def get_memory_stats(self) -> dict[str, Any]:
        """Return statistics about the memory system."""
        if not self._engine:
            self._engine = EvolutionEngine(self._config)
        return self._engine._memory.get_archive_stats()

    def get_memory_previews(self) -> dict[str, str]:
        """Return truncated previews of active memory files."""
        return {
            "active_learnings_preview": self._read_memory_preview("active_learnings.md", 4000),
            "active_social_learnings_preview": self._read_memory_preview(
                "active_social_learnings.md", 2000
            ),
        }

    # ─── Internal ───────────────────────────────────────────

    def _read_memory_preview(self, filename: str, limit: int) -> str:
        """Read a memory file preview without surfacing filesystem errors."""
        path = Path(self._config.memory_path) / filename
        try:
            if not path.exists() or not path.is_file():
                return ""
            return path.read_text(encoding="utf-8")[:limit]
        except Exception as e:
            logger.warning("EvolutionService: failed to read memory preview '{}': {}", filename, e)
            return ""

    async def _on_cron_job(self, job: CronJob) -> str | None:
        """Callback from CronService when a scheduled job fires."""
        action = get_evolution_action(job)

        if action == "evolve":
            await self._run_evolution_from_cron(job)
        elif action == "memory_synth":
            await self._run_synthesis_from_cron(job)
        else:
            logger.warning("EvolutionService: unrecognized cron job '{}' ({})", job.name, job.id)

        return None

    async def _run_evolution_from_cron(self, job: CronJob) -> None:
        """Handle the scheduled evolution trigger."""
        if self._lock.locked():
            logger.info("EvolutionService: cron triggered but evolution already running, skipping")
            return

        if not self._engine:
            self._engine = EvolutionEngine(self._config)

        async with self._lock:
            try:
                logger.info("EvolutionService: cron triggered evolution (job_id={})", job.id)
                session = await self._engine.run_full_cycle()
                self._current_session = session
                self._session_history.append(session)
                self._session_history = self._session_history[-20:]
                logger.info(
                    "EvolutionService: cron evolution complete — {}/{} tasks succeeded",
                    session.metrics.tasks_completed,
                    session.metrics.tasks_planned,
                )
            except Exception as e:
                logger.error("EvolutionService: cron evolution failed: {}", e)

    async def _run_synthesis_from_cron(self, job: CronJob) -> None:
        """Handle the scheduled memory synthesis trigger."""
        if not self._engine:
            self._engine = EvolutionEngine(self._config)
        try:
            logger.info("EvolutionService: running scheduled memory synthesis")
            await self._engine.run_memory_synthesis()
        except Exception as e:
            logger.error("EvolutionService: scheduled synthesis failed: {}", e)


# ── Config helpers ────────────────────────────────────────────


def _load_evolution_config() -> EvolutionConfig:
    """Load EvolutionConfig from EVOLUTION_* environment variables.

    Reads directly from server settings (src/server/config.py EvolutionSettings).
    Falls back to defaults if loading fails.
    """
    try:
        from src.server.config import settings
        return EvolutionConfig(
            enabled=settings.evolution_enabled,
            cron_expr=settings.evolution_cron_expr,
            interval_hours=settings.evolution_interval_hours,
            memory_path=settings.evolution_memory_path,
            journal_path=settings.evolution_journal_path,
            identity_file=settings.evolution_identity_file,
            personality_file=settings.evolution_personality_file,
            max_tasks_per_session=settings.evolution_max_tasks_per_session,
            codebuddy_path=settings.evolution_codebuddy_path,
            codebuddy_model=settings.evolution_codebuddy_model,
            codebuddy_timeout=settings.evolution_codebuddy_timeout,
            working_dir=settings.evolution_working_dir,
            use_worktree=settings.evolution_use_worktree,
            parallel_tasks=settings.evolution_parallel_tasks,
            worktree_base_dir=settings.evolution_worktree_base_dir,
        )
    except Exception as e:
        logger.warning("EvolutionService: failed to load settings, using defaults: {}", e)
        return EvolutionConfig()


class _SchemaEvolutionConfigAdapter:
    """Thin adapter to pass EvolutionConfig to register_evolution_jobs which expects schema config."""
    def __init__(self, config: EvolutionConfig, memory_synthesis_cron: str = "0 12 * * *"):
        self.enabled = config.enabled
        self.cron_expr = config.cron_expr
        self.interval_hours = config.interval_hours
        self.memory_synthesis_cron = memory_synthesis_cron


def _to_schema_config(config: EvolutionConfig) -> _SchemaEvolutionConfigAdapter:
    try:
        from src.server.config import settings
        synth_cron = settings.evolution_memory_synthesis_cron
    except Exception:
        synth_cron = "0 12 * * *"
    return _SchemaEvolutionConfigAdapter(config, synth_cron)


def _session_summary(session: EvolutionSession | None) -> dict | None:
    """Serialize a session to a lightweight summary dict."""
    if session is None:
        return None
    return {
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
    }

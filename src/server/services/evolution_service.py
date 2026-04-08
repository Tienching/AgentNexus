"""Evolution service — integrates EvolutionEngine with TaskScheduler.

This module is the "glue" between the evolution engine (which knows how to
self-improve) and the application runtime (TaskScheduler / ScheduleStorage,
app.py lifespan).

Responsibilities:
  - Register evolution schedules via ScheduleStorage (consumed by TaskScheduler)
  - Provide a callback for TaskScheduler to invoke when evolution schedules fire
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

from src.nanobot.evolve.engine import EvolutionEngine
from src.nanobot.evolve.models import EvolutionConfig, EvolutionSession
from src.runtime.models.schedule_models import Schedule, ScheduleKind


# Well-known schedule names used to identify evolution schedules.
EVOLVE_SCHEDULE_NAME = "nexus-self-evolve"
MEMORY_SYNTH_SCHEDULE_NAME = "nexus-memory-synth"


def _now_ms() -> int:
    return int(time.time() * 1000)


class EvolutionService:
    """Manages the lifecycle of the self-evolution system.

    Usage (in app.py lifespan):
        svc = EvolutionService.create()
        await svc.start(schedule_storage)
        # ... app runs ...
        await svc.stop()

    Manual trigger:
        session = await svc.trigger_now()
    """

    def __init__(self, engine_config: EvolutionConfig):
        self._config = engine_config
        self._engine: EvolutionEngine | None = None
        self._running = False
        self._lock = asyncio.Lock()  # Prevents concurrent evolution sessions
        self._current_session: EvolutionSession | None = None
        self._session_history: list[EvolutionSession] = []
        self._schedule_storage = None  # Set during start()

    @classmethod
    def create(cls) -> "EvolutionService":
        """Create an EvolutionService instance by loading config from environment."""
        config = _load_evolution_config()
        return cls(config)

    async def start(self, schedule_storage=None) -> None:
        """Initialize EvolutionEngine and register schedules in ScheduleStorage.

        Args:
            schedule_storage: ScheduleStorage instance from the app lifespan.
                              If None, evolution schedules won't be registered
                              (but manual triggers still work).
        """
        if not self._config.enabled:
            logger.info("EvolutionService: disabled, not starting")
            return

        self._engine = EvolutionEngine(self._config)
        self._schedule_storage = schedule_storage

        # Register evolution schedules via ScheduleStorage if available
        if schedule_storage is not None:
            self._register_evolution_schedules(schedule_storage)

        self._running = True
        logger.info(
            "EvolutionService started — evolve cron='{}', synthesis cron='{}'",
            self._config.cron_expr,
            _get_memory_synthesis_cron(),
        )

    async def stop(self) -> None:
        """Stop the evolution service."""
        self._running = False
        logger.info("EvolutionService stopped")

    # ─── Schedule Registration ──────────────────────────────

    def _register_evolution_schedules(self, schedule_storage) -> None:
        """Register (or sync) the two evolution schedules in ScheduleStorage.

        This is idempotent — if a schedule with the same name already exists
        with the correct cron expression, nothing changes.
        """
        synth_cron = _get_memory_synthesis_cron()

        self._sync_or_register_schedule(
            schedule_storage,
            name=EVOLVE_SCHEDULE_NAME,
            cron_expr=self._config.cron_expr,
            evolution_phase="full",
            description="Periodic self-evolution cycle",
        )
        self._sync_or_register_schedule(
            schedule_storage,
            name=MEMORY_SYNTH_SCHEDULE_NAME,
            cron_expr=synth_cron,
            evolution_phase="memory_synth",
            description="Periodic memory synthesis (archive → active_learnings)",
        )

    def _sync_or_register_schedule(
        self,
        schedule_storage,
        *,
        name: str,
        cron_expr: str,
        evolution_phase: str,
        description: str,
    ) -> None:
        """Ensure a schedule with the given name and cron_expr exists."""
        existing = self._find_schedule_by_name(schedule_storage, name)

        if existing:
            # Check if the cron expression matches
            if existing.cron_expression == cron_expr:
                logger.info(
                    "EvolutionService: schedule '{}' already registered with cron='{}'",
                    name, cron_expr,
                )
                return

            # Cron mismatch — delete and recreate
            logger.info(
                "EvolutionService: schedule '{}' cron mismatch ('{}' -> '{}'), recreating",
                name, existing.cron_expression, cron_expr,
            )
            schedule_storage.delete_schedule(existing.id)

        # Register new schedule
        schedule = schedule_storage.add_schedule(
            name=name,
            description=description,
            cron_expression=cron_expr,
            schedule_kind="evolution",
            evolution_phase=evolution_phase,
            created_by="evolution_service",
        )
        logger.info(
            "EvolutionService: registered schedule '{}' ({}), cron='{}'",
            name, schedule.id, cron_expr,
        )

    @staticmethod
    def _find_schedule_by_name(schedule_storage, name: str) -> Schedule | None:
        """Find a schedule by name in ScheduleStorage."""
        schedules, _ = schedule_storage.list_schedules(page_size=1000)
        return next((s for s in schedules if s.name == name), None)

    # ─── Callback for TaskScheduler ─────────────────────────

    async def on_schedule_fired(self, schedule: Schedule) -> None:
        """Called by TaskScheduler when an evolution schedule fires.

        This replaces the old _on_cron_job callback from CronService.
        """
        if not self._config.enabled:
            logger.warning("EvolutionService: schedule fired but evolution is disabled, ignoring")
            return

        phase = schedule.evolution_phase or "full"

        if phase == "full":
            await self._run_evolution_from_schedule(schedule)
        elif phase == "memory_synth":
            await self._run_synthesis_from_schedule(schedule)
        else:
            logger.warning(
                "EvolutionService: unrecognized evolution_phase '{}' for schedule '{}'",
                phase, schedule.name,
            )

    # ─── Manual Trigger API (unchanged) ────────────────────

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
        # Build schedule info from ScheduleStorage if available
        schedule_info: dict[str, Any] = {}
        if self._schedule_storage is not None:
            try:
                schedules, _ = self._schedule_storage.list_schedules(page_size=100)
                evo_schedules = [
                    s for s in schedules
                    if s.schedule_kind == ScheduleKind.EVOLUTION.value
                ]
                for s in evo_schedules:
                    schedule_info[s.name] = {
                        "id": s.id,
                        "cron_expression": s.cron_expression,
                        "status": s.status,
                        "run_count": s.run_count,
                        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
                        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
                        "evolution_phase": s.evolution_phase,
                    }
            except Exception as e:
                logger.warning("EvolutionService: failed to query schedule info: {}", e)

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
            "schedules": schedule_info,
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

    async def _run_evolution_from_schedule(self, schedule: Schedule) -> None:
        """Handle the scheduled evolution trigger."""
        if self._lock.locked():
            logger.info("EvolutionService: schedule triggered but evolution already running, skipping")
            return

        if not self._engine:
            self._engine = EvolutionEngine(self._config)

        async with self._lock:
            try:
                logger.info(
                    "EvolutionService: schedule triggered evolution (schedule_id={})",
                    schedule.id,
                )
                session = await self._engine.run_full_cycle()
                self._current_session = session
                self._session_history.append(session)
                self._session_history = self._session_history[-20:]
                logger.info(
                    "EvolutionService: scheduled evolution complete — {}/{} tasks succeeded",
                    session.metrics.tasks_completed,
                    session.metrics.tasks_planned,
                )
            except Exception as e:
                logger.error("EvolutionService: scheduled evolution failed: {}", e)

    async def _run_synthesis_from_schedule(self, schedule: Schedule) -> None:
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


def _get_memory_synthesis_cron() -> str:
    """Get the memory synthesis cron expression from settings."""
    try:
        from src.server.config import settings
        return settings.evolution_memory_synthesis_cron
    except Exception:
        return "0 12 * * *"


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

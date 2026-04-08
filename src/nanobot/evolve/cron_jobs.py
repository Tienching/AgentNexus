"""Evolution cron service - registers and manages evolution-specific cron jobs.

.. deprecated::
    This module is NO LONGER used by EvolutionService (which now registers
    schedules via ScheduleStorage / TaskScheduler).  It is kept for backward
    compatibility with the nanobot agent cron tool
    (``src/nanobot/agent/tools/cron.py``) which may still reference these
    constants and helpers.

    For the canonical evolution schedule registration, see
    ``src/server/services/evolution_service.py`` (``_register_evolution_schedules``).

Registers two recurring jobs into the nanobot CronService:
  1. nexus-self-evolve  — runs a full evolution cycle every N hours
  2. nexus-memory-synth — synthesizes archive memories into active context daily
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.nanobot.config.schema import EvolutionConfig as SchemaEvolutionConfig
from src.nanobot.cron.service import CronService
from src.nanobot.cron.types import CronJob, CronPayload, CronSchedule

EVOLVE_JOB_NAME = "nexus-self-evolve"
MEMORY_SYNTH_JOB_NAME = "nexus-memory-synth"

# Special payload kind for evolution engine triggers
EVOLVE_PAYLOAD_KIND = "system_event"
EVOLVE_PAYLOAD_MSG_EVOLVE = "__nexus_evolve__"
EVOLVE_PAYLOAD_MSG_SYNTH = "__nexus_memory_synth__"


def _sync_or_add_job(
    cron_service: CronService,
    *,
    name: str,
    desired_expr: str,
    message: str,
) -> None:
    existing_job = next(
        (job for job in cron_service.list_jobs(include_disabled=True) if job.name == name),
        None,
    )
    if existing_job and existing_job.schedule.expr == desired_expr:
        logger.info("Evolution: job '{}' already registered with cron='{}'", name, desired_expr)
        return

    was_enabled = existing_job.enabled if existing_job else True
    if existing_job:
        logger.info(
            "Evolution: job '{}' cron mismatch ('{}' -> '{}'), recreating",
            name,
            existing_job.schedule.expr,
            desired_expr,
        )
        cron_service.remove_job(existing_job.id)

    job = cron_service.add_job(
        name=name,
        schedule=CronSchedule(kind="cron", expr=desired_expr, tz="UTC"),
        message=message,
    )
    if not was_enabled:
        cron_service.enable_job(job.id, enabled=False)
    logger.info("Evolution: registered job '{}' ({}), cron='{}'", name, job.id, desired_expr)



def register_evolution_jobs(
    cron_service: CronService,
    config: SchemaEvolutionConfig,
) -> None:
    """Register evolution cron jobs if enabled.

    Safe to call multiple times — existing jobs are synchronized to config.
    """
    if not config.enabled:
        logger.info("Evolution: disabled in config, skipping cron registration")
        return

    _sync_or_add_job(
        cron_service,
        name=EVOLVE_JOB_NAME,
        desired_expr=config.cron_expr,
        message=EVOLVE_PAYLOAD_MSG_EVOLVE,
    )
    _sync_or_add_job(
        cron_service,
        name=MEMORY_SYNTH_JOB_NAME,
        desired_expr=config.memory_synthesis_cron,
        message=EVOLVE_PAYLOAD_MSG_SYNTH,
    )


def is_evolution_job(job: CronJob) -> bool:
    """Check if a cron job is an evolution job."""
    return job.name in (EVOLVE_JOB_NAME, MEMORY_SYNTH_JOB_NAME)


def get_evolution_action(job: CronJob) -> str | None:
    """Get the evolution action type from a cron job payload.

    Returns:
        'evolve' | 'memory_synth' | None
    """
    msg = job.payload.message
    if msg == EVOLVE_PAYLOAD_MSG_EVOLVE:
        return "evolve"
    if msg == EVOLVE_PAYLOAD_MSG_SYNTH:
        return "memory_synth"
    return None

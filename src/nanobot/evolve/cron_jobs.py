"""Evolution cron service - registers and manages evolution-specific cron jobs.

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


def register_evolution_jobs(
    cron_service: CronService,
    config: SchemaEvolutionConfig,
) -> None:
    """Register evolution cron jobs if enabled.

    Safe to call multiple times — skips if jobs already registered.
    """
    if not config.enabled:
        logger.info("Evolution: disabled in config, skipping cron registration")
        return

    existing_names = {j.name for j in cron_service.list_jobs(include_disabled=True)}

    # Register evolution job
    if EVOLVE_JOB_NAME not in existing_names:
        from src.nanobot.cron.types import CronSchedule, CronPayload
        import time

        job = cron_service.add_job(
            name=EVOLVE_JOB_NAME,
            schedule=CronSchedule(kind="cron", expr=config.cron_expr, tz="UTC"),
            message=EVOLVE_PAYLOAD_MSG_EVOLVE,
        )
        logger.info("Evolution: registered job '{}' ({}), cron='{}'",
                     EVOLVE_JOB_NAME, job.id, config.cron_expr)
    else:
        logger.info("Evolution: job '{}' already registered", EVOLVE_JOB_NAME)

    # Register memory synthesis job
    if MEMORY_SYNTH_JOB_NAME not in existing_names:
        job = cron_service.add_job(
            name=MEMORY_SYNTH_JOB_NAME,
            schedule=CronSchedule(kind="cron", expr=config.memory_synthesis_cron, tz="UTC"),
            message=EVOLVE_PAYLOAD_MSG_SYNTH,
        )
        logger.info("Evolution: registered job '{}' ({}), cron='{}'",
                     MEMORY_SYNTH_JOB_NAME, job.id, config.memory_synthesis_cron)
    else:
        logger.info("Evolution: job '{}' already registered", MEMORY_SYNTH_JOB_NAME)


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

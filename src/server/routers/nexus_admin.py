# -*- coding: utf-8 -*-
"""Diagnostics and Audit Log endpoints.

Ported from mission-control:
  - GET /api/diagnostics  (api/diagnostics/route.ts)
  - GET /api/audit        (api/audit/route.ts)

Adapted for agent-nexus: Redis-backed audit log, Python system info,
comprehensive diagnostics combining system/redis/tasks/sessions/security.
"""

from __future__ import annotations

import json
import os
import platform
import resource
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from ..services.redis_client import get_redis_client
from ..services.task_storage import TaskQueue
from .nexus_auth import verify_nexus_auth

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-admin"],
    dependencies=[Depends(verify_nexus_auth)],
)

# ═══════════════════════════════════════════════════════════════════════════
# Audit Log — Redis-backed operation log
# ═══════════════════════════════════════════════════════════════════════════

AUDIT_KEY = "nexus:audit:log"
AUDIT_MAX_ENTRIES = 10000  # Cap to prevent unbounded growth

# In-memory fallback when Redis is unavailable — prevents silent data loss
_audit_fallback: deque = deque(maxlen=1000)
_audit_fallback_next_id: int = 0


class AuditEvent(BaseModel):
    id: int
    action: str
    actor: str = ""
    detail: Optional[Any] = None
    ip_address: str = ""
    timestamp: int  # unix seconds


class AuditResponse(BaseModel):
    events: List[AuditEvent]
    total: int
    limit: int
    offset: int


def record_audit_event(
    action: str,
    actor: str = "",
    detail: Optional[Any] = None,
    ip_address: str = "",
) -> None:
    """Record an audit event to Redis. Fire-and-forget, never raises."""
    try:
        rc = get_redis_client()
        r = rc.client
        prefix = os.environ.get("REDIS_KEY_PREFIX", "aona:")
        key = f"{prefix}{AUDIT_KEY}"

        # Auto-increment ID
        id_key = f"{prefix}nexus:audit:next_id"
        event_id = r.incr(id_key)

        event = {
            "id": event_id,
            "action": action,
            "actor": actor,
            "detail": detail,
            "ip_address": ip_address,
            "timestamp": int(time.time()),
        }
        r.lpush(key, json.dumps(event, default=str))
        # Trim to max entries
        r.ltrim(key, 0, AUDIT_MAX_ENTRIES - 1)
    except Exception as e:
        logger.debug(f"Failed to record audit event (using fallback): {e}")
        global _audit_fallback_next_id
        _audit_fallback_next_id += 1
        event = {
            "id": _audit_fallback_next_id,
            "action": action,
            "actor": actor,
            "detail": detail,
            "ip_address": ip_address,
            "timestamp": int(time.time()),
        }
        _audit_fallback.append(event)


@router.get("/audit", response_model=AuditResponse)
async def get_audit_log(
    action: Optional[str] = Query(None, description="Filter by action type"),
    actor: Optional[str] = Query(None, description="Filter by actor"),
    limit: int = Query(100, ge=1, le=10000, description="Max events"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    since: Optional[int] = Query(None, description="Unix timestamp — events after"),
    until: Optional[int] = Query(None, description="Unix timestamp — events before"),
):
    """Query the audit log.

    Ported from mission-control GET /api/audit (api/audit/route.ts).
    Returns operation events (login, export, cleanup, task operations)
    stored in Redis with filtering and pagination.
    """
    try:
        rc = get_redis_client()
        r = rc.client
        prefix = os.environ.get("REDIS_KEY_PREFIX", "aona:")
        key = f"{prefix}{AUDIT_KEY}"

        # Get all events (they're stored newest-first)
        raw_events = r.lrange(key, 0, -1)
        events: List[AuditEvent] = []

        for raw in raw_events:
            try:
                data = json.loads(raw)
                event = AuditEvent(**data)

                # Apply filters
                if action and event.action != action:
                    continue
                if actor and event.actor != actor:
                    continue
                if since and event.timestamp < since:
                    continue
                if until and event.timestamp > until:
                    continue

                events.append(event)
            except Exception:
                continue

        total = len(events)
        page = events[offset:offset + limit]

        return AuditResponse(events=page, total=total, limit=limit, offset=offset)
    except Exception as e:
        logger.warning(f"Audit log query failed, using fallback: {e}")
        events: List[AuditEvent] = []
        for data in list(_audit_fallback):
            try:
                event = AuditEvent(**data)
                if action and event.action != action:
                    continue
                if actor and event.actor != actor:
                    continue
                if since and event.timestamp < since:
                    continue
                if until and event.timestamp > until:
                    continue
                events.append(event)
            except Exception:
                continue
        # Fallback stores oldest-first; reverse to match Redis newest-first order
        events.reverse()
        total = len(events)
        page = events[offset:offset + limit]
        return AuditResponse(events=page, total=total, limit=limit, offset=offset)


# ═══════════════════════════════════════════════════════════════════════════
# Diagnostics — Comprehensive system health
# ═══════════════════════════════════════════════════════════════════════════

class DiagSystem(BaseModel):
    python_version: str
    platform: str
    arch: str
    process_memory_mb: float
    process_uptime_seconds: float
    is_docker: bool
    pid: int
    cpu_count: int


class DiagVersion(BaseModel):
    app: str
    python: str
    fastapi: Optional[str] = None


class DiagSecurityCheck(BaseModel):
    name: str
    passed: bool = Field(..., alias="pass")
    detail: str

    model_config = {"populate_by_name": True}


class DiagSecurity(BaseModel):
    score: int
    checks: List[DiagSecurityCheck]


class DiagRedis(BaseModel):
    connected: bool
    version: str = ""
    used_memory_mb: float = 0
    maxmemory_mb: float = 0
    connected_clients: int = 0
    total_keys: int = 0
    uptime_seconds: int = 0


class DiagTasks(BaseModel):
    total: int = 0
    by_status: Dict[str, int] = Field(default_factory=dict)


class DiagSessions(BaseModel):
    total: int = 0


class DiagRetention(BaseModel):
    tasks_done_days: int
    tasks_failed_days: int
    sessions_days: int


class DiagnosticsResponse(BaseModel):
    system: DiagSystem
    version: DiagVersion
    security: DiagSecurity
    redis: DiagRedis
    tasks: DiagTasks
    sessions: DiagSessions
    retention: DiagRetention
    audit_events_count: int = 0


# Process start time for uptime calculation
_PROCESS_START = time.time()


def _get_system_info() -> DiagSystem:
    """Collect Python/OS process info."""
    try:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On Linux, ru_maxrss is in KB; on macOS, in bytes
        rss_mb = rss / 1024 if platform.system() == "Linux" else rss / 1024 / 1024
    except Exception:
        rss_mb = 0

    return DiagSystem(
        python_version=platform.python_version(),
        platform=platform.system().lower(),
        arch=platform.machine(),
        process_memory_mb=round(rss_mb, 1),
        process_uptime_seconds=round(time.time() - _PROCESS_START, 1),
        is_docker=os.path.exists("/.dockerenv"),
        pid=os.getpid(),
        cpu_count=os.cpu_count() or 1,
    )


def _get_version_info() -> DiagVersion:
    """Get application version info."""
    try:
        import fastapi
        fastapi_ver = fastapi.__version__
    except Exception:
        fastapi_ver = None

    return DiagVersion(
        app=getattr(settings, "version", "0.1.0") if hasattr(settings, "version") else "0.1.0",
        python=platform.python_version(),
        fastapi=fastapi_ver,
    )


def _get_security_info() -> DiagSecurity:
    """Quick security posture check (subset of full security-scan)."""
    checks: List[Dict[str, Any]] = []

    nexus_pw = getattr(settings, "nexus_password", None) or ""
    checks.append({
        "name": "Nexus password configured",
        "pass": bool(nexus_pw) and len(nexus_pw) >= 8,
        "detail": "Password set" if nexus_pw else "No password — UI unprotected",
    })

    debug = getattr(settings, "debug", False) or os.environ.get("DEBUG", "").lower() in ("1", "true")
    checks.append({
        "name": "Debug mode disabled",
        "pass": not debug,
        "detail": "Debug OFF" if not debug else "Debug ON",
    })

    is_root = os.geteuid() == 0 if hasattr(os, "geteuid") else False
    checks.append({
        "name": "Not running as root",
        "pass": not is_root,
        "detail": "Non-root" if not is_root else "Running as root!",
    })

    env = getattr(settings, "environment", "development")
    checks.append({
        "name": "Production environment",
        "pass": env == "production",
        "detail": f"Environment: {env}",
    })

    passed = sum(1 for c in checks if c["pass"])
    score = round(passed / len(checks) * 100) if checks else 0

    return DiagSecurity(
        score=score,
        checks=[DiagSecurityCheck(**c) for c in checks],
    )


def _get_redis_info() -> DiagRedis:
    """Collect Redis diagnostics."""
    try:
        rc = get_redis_client()
        if not rc.ping():
            return DiagRedis(connected=False)

        r = rc.client
        info = r.info()
        prefix = os.environ.get("REDIS_KEY_PREFIX", "aona:")
        total_keys = 0
        for db_info in [v for k, v in info.items() if k.startswith("db") and isinstance(v, dict)]:
            total_keys += db_info.get("keys", 0)

        return DiagRedis(
            connected=True,
            version=info.get("redis_version", ""),
            used_memory_mb=round(info.get("used_memory", 0) / 1024 / 1024, 1),
            maxmemory_mb=round(info.get("maxmemory", 0) / 1024 / 1024, 1),
            connected_clients=info.get("connected_clients", 0),
            total_keys=total_keys,
            uptime_seconds=info.get("uptime_in_seconds", 0),
        )
    except Exception as e:
        return DiagRedis(connected=False, version=str(e)[:80])


def _get_task_info() -> DiagTasks:
    """Count tasks by status."""
    exec_user = getattr(settings, "exec_user", None) or "default"
    queue = TaskQueue(db_path=None, exec_user=exec_user)
    by_status: Dict[str, int] = {}
    total = 0
    for status in ("todo", "doing", "done", "failed", "archived"):
        try:
            tasks, count = queue.list_tasks(page=1, page_size=1, status=status)
            by_status[status] = count
            total += count
        except Exception:
            by_status[status] = 0
    return DiagTasks(total=total, by_status=by_status)


def _get_session_count() -> DiagSessions:
    """Count total sessions in Redis."""
    try:
        rc = get_redis_client()
        r = rc.client
        prefix = os.environ.get("REDIS_KEY_PREFIX", "aona:")
        count = 0
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match=f"{prefix}session:*:meta", count=500)
            count += len(keys)
            if cursor == 0:
                break
        return DiagSessions(total=count)
    except Exception:
        return DiagSessions(total=0)


def _get_audit_count() -> int:
    """Count audit log entries."""
    try:
        rc = get_redis_client()
        r = rc.client
        prefix = os.environ.get("REDIS_KEY_PREFIX", "aona:")
        return r.llen(f"{prefix}{AUDIT_KEY}")
    except Exception:
        return len(_audit_fallback)


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def diagnostics():
    """Comprehensive system diagnostics dashboard.

    Ported from mission-control GET /api/diagnostics (api/diagnostics/route.ts).
    Returns system info, version, security posture, Redis stats,
    task/session counts, retention config, and audit log size.
    """
    import asyncio

    system = _get_system_info()
    version = _get_version_info()
    security = _get_security_info()
    redis = await asyncio.get_event_loop().run_in_executor(None, _get_redis_info)
    tasks = await asyncio.get_event_loop().run_in_executor(None, _get_task_info)
    sessions = await asyncio.get_event_loop().run_in_executor(None, _get_session_count)
    audit_count = await asyncio.get_event_loop().run_in_executor(None, _get_audit_count)

    retention = DiagRetention(
        tasks_done_days=int(os.environ.get("RETENTION_TASKS_DONE_DAYS", 90)),
        tasks_failed_days=int(os.environ.get("RETENTION_TASKS_FAILED_DAYS", 30)),
        sessions_days=int(os.environ.get("RETENTION_SESSIONS_DAYS", 60)),
    )

    # Record this diagnostics access in audit
    record_audit_event("diagnostics_view", actor="admin")

    return DiagnosticsResponse(
        system=system,
        version=version,
        security=security,
        redis=redis,
        tasks=tasks,
        sessions=sessions,
        retention=retention,
        audit_events_count=audit_count,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Doctor — User-friendly self-diagnosis and log bundling
# ═══════════════════════════════════════════════════════════════════════════

class DoctorCheck(BaseModel):
    """A single diagnostic check result."""
    name: str
    status: str  # "pass", "fail", "warn"
    message: str
    detail: Optional[str] = None


class DoctorResponse(BaseModel):
    """User-friendly doctor/self-diagnosis response."""
    healthy: bool
    version: str
    checks: List[DoctorCheck]
    summary: str  # Human-readable summary


@router.get("/doctor", response_model=DoctorResponse, summary="Run self-diagnosis")
async def doctor():
    """User-friendly self-diagnosis for troubleshooting.

    Provides a simple pass/fail/warn status for common issues:
    - Database connectivity
    - Redis connectivity
    - Authentication configured
    - Environment variables
    - Disk space
    - Memory usage

    Returns a summary and suggestion for next steps if issues are found.
    """
    import shutil
    import asyncio

    checks: List[DoctorCheck] = []
    all_passed = True

    # Check 1: Python environment
    checks.append(DoctorCheck(
        name="python",
        status="pass",
        message=f"Python {platform.python_version()} running correctly",
    ))

    # Check 2: Disk space
    try:
        usage = shutil.disk_usage("/")
        free_gb = usage.free / (1024**3)
        if free_gb < 1:
            checks.append(DoctorCheck(
                name="disk_space",
                status="fail",
                message=f"Low disk space: {free_gb:.1f}GB free",
                detail="Less than 1GB free. Clean up old logs or data.",
            ))
            all_passed = False
        elif free_gb < 5:
            checks.append(DoctorCheck(
                name="disk_space",
                status="warn",
                message=f"Disk space running low: {free_gb:.1f}GB free",
                detail="Consider cleaning up old logs or data.",
            ))
        else:
            checks.append(DoctorCheck(
                name="disk_space",
                status="pass",
                message=f"Disk space OK: {free_gb:.1f}GB free",
            ))
    except Exception as e:
        checks.append(DoctorCheck(
            name="disk_space",
            status="warn",
            message="Could not check disk space",
            detail=str(e),
        ))

    # Check 3: Memory usage
    try:
        mem = resource.getrusage(resource.RUSAGE_SELF)
        mem_mb = mem.ru_maxrss / 1024  # KB to MB
        if mem_mb > 1000:
            checks.append(DoctorCheck(
                name="memory",
                status="warn",
                message=f"High memory usage: {mem_mb:.0f}MB",
                detail="Memory usage is high but within acceptable range.",
            ))
        else:
            checks.append(DoctorCheck(
                name="memory",
                status="pass",
                message=f"Memory OK: {mem_mb:.0f}MB used",
            ))
    except Exception as e:
        checks.append(DoctorCheck(
            name="memory",
            status="warn",
            message="Could not check memory usage",
            detail=str(e),
        ))

    # Check 4: Database
    try:
        from src.runtime.stores.db import get_db
        db = get_db()
        with db.conn() as conn:
            conn.execute("SELECT 1")
        checks.append(DoctorCheck(
            name="database",
            status="pass",
            message="SQLite database connected",
            detail=f"Database: {db.db_path}",
        ))
    except Exception as e:
        checks.append(DoctorCheck(
            name="database",
            status="fail",
            message="Database connection failed",
            detail=str(e),
        ))
        all_passed = False

    # Check 5: Redis
    redis_connected = False
    try:
        rc = get_redis_client()
        if rc.ping():
            redis_connected = True
            checks.append(DoctorCheck(
                name="redis",
                status="pass",
                message="Redis connected",
            ))
        else:
            checks.append(DoctorCheck(
                name="redis",
                status="warn",
                message="Redis ping failed",
                detail="Redis may be unavailable but app can still function.",
            ))
    except Exception as e:
        checks.append(DoctorCheck(
            name="redis",
            status="warn",
            message="Redis not configured",
            detail="App will use in-memory fallback. Set REDIS_URL to enable full functionality.",
        ))

    # Check 6: Authentication
    nexus_pw = getattr(settings, "nexus_password", None) or ""
    if nexus_pw and len(nexus_pw) >= 8:
        checks.append(DoctorCheck(
            name="authentication",
            status="pass",
            message="Authentication configured",
        ))
    else:
        checks.append(DoctorCheck(
            name="authentication",
            status="warn",
            message="Authentication may not be configured",
            detail="Set NEXUS_PASSWORD to protect the API.",
        ))

    # Check 7: Environment
    env = os.environ.get("ENVIRONMENT", os.environ.get("ENV", "development"))
    if env == "production":
        checks.append(DoctorCheck(
            name="environment",
            status="pass",
            message="Running in production mode",
        ))
    else:
        checks.append(DoctorCheck(
            name="environment",
            status="warn",
            message=f"Running in {env} mode",
            detail="For production, set ENVIRONMENT=production.",
        ))

    # Check 8: API keys (optional but warned)
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if has_openai or has_anthropic:
        checks.append(DoctorCheck(
            name="api_keys",
            status="pass",
            message="At least one API key configured",
        ))
    else:
        checks.append(DoctorCheck(
            name="api_keys",
            status="warn",
            message="No API keys found",
            detail="Set OPENAI_API_KEY or ANTHROPIC_API_KEY to enable LLM features.",
        ))

    # Generate summary
    fail_count = sum(1 for c in checks if c.status == "fail")
    warn_count = sum(1 for c in checks if c.status == "warn")

    if fail_count > 0:
        summary = f"Found {fail_count} failure(s) and {warn_count} warning(s). See details for troubleshooting."
        healthy = False
    elif warn_count > 0:
        summary = f"Healthy with {warn_count} warning(s). Review warnings for potential issues."
        healthy = True
    else:
        summary = "All checks passed. System is healthy."
        healthy = True

    return DoctorResponse(
        healthy=healthy,
        version=getattr(settings, "version", "0.1.0") if hasattr(settings, "version") else "0.1.0",
        checks=checks,
        summary=summary,
    )


@router.get("/doctor/bundle", summary="Bundle diagnostic information for support")
async def doctor_bundle():
    """Bundle diagnostic information for support/debugging.

    Returns a JSON object containing:
    - System info
    - Recent error logs (if available)
    - Configuration (non-sensitive)
    - Diagnostics output

    This bundle can be shared with support to help diagnose issues.
    """
    from src.server.logger import get_logger

    bundle: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": getattr(settings, "version", "0.1.0") if hasattr(settings, "version") else "0.1.0",
    }

    # Add system info
    bundle["system"] = _get_system_info().model_dump()

    # Add version info
    bundle["version_info"] = _get_version_info().model_dump()

    # Add diagnostics
    try:
        import asyncio
        system = _get_system_info()
        version = _get_version_info()
        security = _get_security_info()
        redis = await asyncio.get_event_loop().run_in_executor(None, _get_redis_info)
        bundle["diagnostics"] = {
            "security_score": security.score,
            "redis_connected": redis.connected,
            "system": system.model_dump(),
        }
    except Exception as e:
        bundle["diagnostics_error"] = str(e)

    # Add recent logs (last 50 lines from logger if available)
    try:
        logger_instance = get_logger()
        # Get recent log entries if possible
        bundle["logs"] = "Log retrieval not implemented - check server logs directly"
    except Exception:
        bundle["logs"] = "Logger not accessible"

    return bundle


# ═══════════════════════════════════════════════════════════════════════════
# Observability — telemetry, latency, cost metrics
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/metrics", summary="Get observability metrics snapshot")
async def get_metrics(path_prefix: str = Query("", description="Filter latency by path prefix")):
    """Return a snapshot of telemetry metrics: latency, token usage, cost, events.

    Query params:
      - path_prefix: Optional prefix to filter latency stats (e.g. "/api/nexus/tasks")
    """
    from ..services.observability import telemetry

    if path_prefix:
        snapshot = telemetry.snapshot()
        snapshot["latency"] = telemetry.latency_for_path(path_prefix)
        return snapshot

    return telemetry.snapshot()

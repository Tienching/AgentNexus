# -*- coding: utf-8 -*-
"""Health check and metrics router.

The /health endpoint now performs real subsystem checks and returns a structured
HealthResponse with a `checks` array, mirroring mission-control's
performHealthCheck pattern (commits 4eda03a / afa8e9d).

Checks performed:
- Redis connectivity and round-trip latency (healthy < 100 ms, warning ≥ 100 ms)
- Process memory usage (warning > 400 MB RSS, critical > 800 MB RSS)
- Disk space on filesystem root (warning ≥ 90%, critical ≥ 95%)

Overall `status` is the worst status across all checks:
  critical > unhealthy > warning > degraded > healthy
"""

from __future__ import annotations

import os
import resource
import subprocess
import time
from typing import Any, List, Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from src.runtime import __version__ as runtime_version

from ..models import HealthCheck, HealthResponse, MetricsResponse
from ..config import settings
from ..logger import get_logger

router = APIRouter(tags=["health"])
logger = get_logger(__name__)

# ─── status ordering (higher index = worse) ─────────────────────────────────
_STATUS_ORDER = ["healthy", "degraded", "warning", "unhealthy", "error", "critical"]


def _worst(statuses: List[str]) -> str:
    """Return the most severe status from *statuses*."""
    rank = {s: i for i, s in enumerate(_STATUS_ORDER)}
    return max(statuses, key=lambda s: rank.get(s, 0), default="healthy")


_STARTUP_SUBSYSTEM_ORDER = [
    "task_executor",
    "task_scheduler",
    "channel_service",
    "terminal_manager",
    "evolution_service",
]


# ─── individual check helpers ────────────────────────────────────────────────

def _check_database() -> HealthCheck:
    """Verify SQLite database is reachable and measure round-trip latency."""
    try:
        from src.runtime.stores.db import get_db
        db = get_db()
        t0 = time.monotonic()
        db.execute_fetchone("SELECT 1")
        elapsed_ms = (time.monotonic() - t0) * 1000

        if elapsed_ms >= 100:
            return HealthCheck(
                name="Database",
                status="warning",
                message=f"SQLite slow ({elapsed_ms:.0f} ms)",
                detail={
                    "latency_ms": round(elapsed_ms, 1),
                    "db_path": db.db_path,
                    "hint": "Inspect disk I/O if this warning persists.",
                },
            )
        return HealthCheck(
            name="Database",
            status="healthy",
            message=f"SQLite OK ({elapsed_ms:.0f} ms)",
            detail={"latency_ms": round(elapsed_ms, 1), "db_path": db.db_path},
        )
    except Exception as exc:
        return HealthCheck(
            name="Database",
            status="unhealthy",
            message=f"SQLite connectivity failed: {exc}",
            detail={
                "error": str(exc),
                "exception_type": type(exc).__name__,
                "hint": "Check NEXUS_DB_PATH and disk permissions.",
            },
        )


def _check_redis_optional() -> HealthCheck:
    """Check Redis as optional backend — degraded, never unhealthy."""
    try:
        from ..services.redis_client import get_redis_client
        r = get_redis_client()
        t0 = time.monotonic()
        r.ping()
        elapsed_ms = (time.monotonic() - t0) * 1000
        return HealthCheck(
            name="Redis (optional)",
            status="healthy",
            message=f"Redis reachable ({elapsed_ms:.0f} ms)",
            detail={"latency_ms": round(elapsed_ms, 1)},
        )
    except Exception:
        return HealthCheck(
            name="Redis (optional)",
            status="degraded",
            message="Redis not available — using SQLite backend",
            detail={"hint": "Redis is optional. All data is stored in SQLite."},
        )


def _check_process_memory() -> HealthCheck:
    """Check this process's RSS memory usage.

    Ported from mission-control process memory check (4eda03a).
    Thresholds: > 400 MB → warning, > 800 MB → critical.
    """
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        # On Linux ru_maxrss is in kilobytes; on macOS it's bytes.
        if os.uname().sysname == "Darwin":
            rss_bytes = usage.ru_maxrss
        else:
            rss_bytes = usage.ru_maxrss * 1024

        rss_mb = rss_bytes / (1024 * 1024)

        if rss_mb > 800:
            status = "critical"
        elif rss_mb > 400:
            status = "warning"
        else:
            status = "healthy"

        return HealthCheck(
            name="Process Memory",
            status=status,
            message=f"RSS: {rss_mb:.0f} MB",
            detail={
                "rss_bytes": rss_bytes,
                "rss_mb": round(rss_mb, 1),
                **(
                    {"hint": "Inspect recent workload spikes or increase the runtime memory budget if this remains elevated."}
                    if status != "healthy"
                    else {}
                ),
            },
        )
    except Exception as exc:
        return HealthCheck(
            name="Process Memory",
            status="error",
            message=f"Failed to check process memory: {exc}",
            detail={
                "error": str(exc),
                "exception_type": type(exc).__name__,
                "hint": "Inspect runtime permissions and process metrics collection on this host.",
            },
        )


def _check_disk_space() -> HealthCheck:
    """Check filesystem usage via `df`.

    Ported from mission-control disk space check (4eda03a).
    Thresholds: ≥ 90% → warning, ≥ 95% → critical.
    """
    try:
        result = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        lines = result.stdout.strip().splitlines()
        last = lines[-1] if lines else ""
        parts = last.split()
        pct_field = next((p for p in parts if p.endswith("%")), "0%")
        usage_pct = int(pct_field.rstrip("%") or "0")

        if usage_pct >= 95:
            status = "critical"
        elif usage_pct >= 90:
            status = "warning"
        else:
            status = "healthy"

        return HealthCheck(
            name="Disk Space",
            status=status,
            message=f"Disk usage: {usage_pct}%",
            detail={
                "usage_percent": usage_pct,
                **(
                    {"hint": "Free disk space on the host before the service runs out of writable capacity."}
                    if status != "healthy"
                    else {}
                ),
            },
        )
    except Exception as exc:
        return HealthCheck(
            name="Disk Space",
            status="error",
            message=f"Failed to check disk space: {exc}",
            detail={
                "error": str(exc),
                "exception_type": type(exc).__name__,
                "hint": "Verify that the host can execute `df` and that the service user can inspect filesystem usage.",
            },
        )


# ─── process start time (for uptime) ─────────────────────────────────────────
_START_TIME = time.monotonic()


def _build_startup_subsystem_checks(
    startup_states: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[List[HealthCheck], List[str]]:
    checks: List[HealthCheck] = []
    required_failure_statuses: List[str] = []

    if not startup_states:
        return checks, required_failure_statuses

    for subsystem in _STARTUP_SUBSYSTEM_ORDER:
        state = startup_states.get(subsystem)
        if not state:
            continue

        status = str(state.get("status", "unknown"))
        required = bool(state.get("required", False))
        detail = dict(state.get("detail") or {})
        detail.setdefault("subsystem", subsystem)
        detail.setdefault("required", required)
        detail.setdefault("startup_status", status)

        checks.append(
            HealthCheck(
                name=str(state.get("name") or subsystem),
                status=status,
                message=str(state.get("message") or ""),
                detail=detail,
            )
        )

        if required and status not in {"healthy", "disabled"}:
            required_failure_statuses.append(status)

    for subsystem, state in startup_states.items():
        if subsystem in _STARTUP_SUBSYSTEM_ORDER or not state:
            continue

        status = str(state.get("status", "unknown"))
        required = bool(state.get("required", False))
        detail = dict(state.get("detail") or {})
        detail.setdefault("subsystem", subsystem)
        detail.setdefault("required", required)
        detail.setdefault("startup_status", status)

        checks.append(
            HealthCheck(
                name=str(state.get("name") or subsystem),
                status=status,
                message=str(state.get("message") or ""),
                detail=detail,
            )
        )

        if required and status not in {"healthy", "disabled"}:
            required_failure_statuses.append(status)

    return checks, required_failure_statuses


def _perform_health_check(
    startup_states: Mapping[str, Mapping[str, Any]] | None = None,
) -> HealthResponse:
    """Run all subsystem checks and assemble the HealthResponse.

    Ported from mission-control performHealthCheck (commits 4eda03a / afa8e9d).
    """
    checks: List[HealthCheck] = [
        _check_database(),
        _check_redis_optional(),
        _check_process_memory(),
        _check_disk_space(),
    ]
    startup_checks, startup_failures = _build_startup_subsystem_checks(startup_states)
    checks.extend(startup_checks)

    # Use database + memory + disk for overall status (skip optional Redis)
    core_checks = [c for c in checks if c.name != "Redis (optional)"]
    overall = _worst([c.status for c in core_checks[:3]] + startup_failures)

    return HealthResponse(
        status=overall,
        service="agent-nexus",
        version=runtime_version,
        uptime_seconds=round(time.monotonic() - _START_TIME, 1),
        checks=checks,
    )


def _build_health_error_response(exc: Exception) -> HealthResponse:
    """Return a structured health payload even when the route itself fails."""
    message = str(exc).strip() or type(exc).__name__
    return HealthResponse(
        status="error",
        service="agent-nexus",
        version=runtime_version,
        uptime_seconds=round(time.monotonic() - _START_TIME, 1),
        checks=[
            HealthCheck(
                name="Health Endpoint",
                status="error",
                message=f"Health check failed before completion: {message}",
                detail={
                    "error": message,
                    "exception_type": type(exc).__name__,
                    "hint": "Inspect server logs and verify runtime dependencies such as database connectivity before retrying.",
                },
            )
        ],
    )


# ─── routes ──────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    """Health check endpoint with structured subsystem checks.

    Returns overall status (healthy / warning / unhealthy / critical) and a
    `checks` array with per-subsystem results.  Ported from mission-control
    performHealthCheck (commits 4eda03a / afa8e9d).
    """
    try:
        startup_states = getattr(request.app.state, "startup_subsystems", {})
        return _perform_health_check(startup_states=startup_states)
    except Exception as exc:
        logger.error("Health endpoint failed before completion", exc_info=True)
        payload = _build_health_error_response(exc)
        return JSONResponse(status_code=503, content=payload.model_dump())


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    """
    获取服务指标

    返回请求统计等信息
    """
    # 从全局 metrics 获取数据
    from ..app import metrics

    return MetricsResponse(
        version="0.1.0",
        cli_command=settings.cli_command,
        requests_total=metrics["requests_total"],
        requests_active=metrics["requests_active"],
    )


@router.get("/nexus")
@router.get("/nexus/")
async def nexus_redirect():
    """旧路径兼容 — /nexus 重定向到根路径"""
    return RedirectResponse(url="/")

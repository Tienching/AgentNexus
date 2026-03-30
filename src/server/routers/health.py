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
from typing import List

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from ..models import HealthCheck, HealthResponse, MetricsResponse
from ..config import settings
from ..services.redis_client import get_redis_client

router = APIRouter(tags=["health"])

# ─── status ordering (higher index = worse) ─────────────────────────────────
_STATUS_ORDER = ["healthy", "degraded", "warning", "unhealthy", "error", "critical"]


def _worst(statuses: List[str]) -> str:
    """Return the most severe status from *statuses*."""
    rank = {s: i for i, s in enumerate(_STATUS_ORDER)}
    return max(statuses, key=lambda s: rank.get(s, 0), default="healthy")


# ─── individual check helpers ────────────────────────────────────────────────

def _check_redis() -> HealthCheck:
    """Verify Redis is reachable and measure round-trip latency.

    Ported from mission-control DB check logic (4eda03a): healthy < threshold,
    warning ≥ threshold.  Redis replaces SQLite in Nexus.
    """
    try:
        r = get_redis_client()
        t0 = time.monotonic()
        r.ping()
        elapsed_ms = (time.monotonic() - t0) * 1000

        if elapsed_ms >= 100:
            return HealthCheck(
                name="Redis",
                status="warning",
                message=f"Redis slow ({elapsed_ms:.0f} ms)",
                detail={"latency_ms": round(elapsed_ms, 1)},
            )
        return HealthCheck(
            name="Redis",
            status="healthy",
            message=f"Redis reachable ({elapsed_ms:.0f} ms)",
            detail={"latency_ms": round(elapsed_ms, 1)},
        )
    except Exception as exc:
        return HealthCheck(
            name="Redis",
            status="unhealthy",
            message=f"Redis connectivity failed: {exc}",
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
            detail={"rss_bytes": rss_bytes, "rss_mb": round(rss_mb, 1)},
        )
    except Exception as exc:
        return HealthCheck(
            name="Process Memory",
            status="error",
            message=f"Failed to check process memory: {exc}",
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
            detail={"usage_percent": usage_pct},
        )
    except Exception as exc:
        return HealthCheck(
            name="Disk Space",
            status="error",
            message=f"Failed to check disk space: {exc}",
        )


# ─── process start time (for uptime) ─────────────────────────────────────────
_START_TIME = time.monotonic()


def _perform_health_check() -> HealthResponse:
    """Run all subsystem checks and assemble the HealthResponse.

    Ported from mission-control performHealthCheck (commits 4eda03a / afa8e9d).
    """
    checks: List[HealthCheck] = [
        _check_redis(),
        _check_process_memory(),
        _check_disk_space(),
    ]

    overall = _worst([c.status for c in checks])

    return HealthResponse(
        status=overall,
        service="agent-nexus",
        version="0.1.0",
        uptime_seconds=round(time.monotonic() - _START_TIME, 1),
        checks=checks,
    )


# ─── routes ──────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint with structured subsystem checks.

    Returns overall status (healthy / warning / unhealthy / critical) and a
    `checks` array with per-subsystem results.  Ported from mission-control
    performHealthCheck (commits 4eda03a / afa8e9d).
    """
    return _perform_health_check()


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

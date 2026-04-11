# -*- coding: utf-8 -*-
"""System-level monitoring and operational endpoints.

Ported from mission-control:
  - GET /api/system-monitor  (commit d4f55dd / system-monitor/route.ts)
  - GET /api/workload        (commit d4f55dd / workload/route.ts)
  - GET /api/standup         (commit d4f55dd / standup/route.ts)

Adapted for agent-nexus: Redis-backed storage, async/await, Python/FastAPI,
no SQLite dependencies.
"""

from __future__ import annotations

import asyncio
import os
import platform
import resource
import subprocess
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from ..services.task_storage import TaskQueue
from .nexus_auth import verify_nexus_auth

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-system"],
    dependencies=[Depends(verify_nexus_auth)],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _num_env(name: str, fallback: float) -> float:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return fallback
    try:
        v = float(raw)
        return v if v == v else fallback  # NaN guard
    except ValueError:
        return fallback


def _run(cmd: List[str], timeout: float = 3.0) -> str:
    """Run a subprocess and return stdout, empty string on any error."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# System-Monitor models
# ---------------------------------------------------------------------------

class CpuInfo(BaseModel):
    usage_percent: float = Field(ge=0, le=100)
    cores: int
    model: str
    load_avg: List[float] = Field(default_factory=list)


class MemoryInfo(BaseModel):
    total_bytes: int
    used_bytes: int
    available_bytes: int
    usage_percent: float = Field(ge=0, le=100)


class DiskPartition(BaseModel):
    mountpoint: str
    total_bytes: int
    used_bytes: int
    available_bytes: int
    usage_percent: float = Field(ge=0, le=100)


class NetworkInterface(BaseModel):
    interface: str
    rx_bytes: int
    tx_bytes: int


class SystemMonitorResponse(BaseModel):
    timestamp: int
    cpu: CpuInfo
    memory: MemoryInfo
    disk: List[DiskPartition] = Field(default_factory=list)
    network: List[NetworkInterface] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# System-Monitor implementation
# ---------------------------------------------------------------------------

def _get_cpu_info() -> CpuInfo:
    """Collect CPU info: load average, core count, model string."""
    try:
        load = list(os.getloadavg())
    except AttributeError:
        load = [0.0, 0.0, 0.0]

    cores = os.cpu_count() or 1

    # Try to read /proc/cpuinfo model name (Linux)
    model = "Unknown"
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass

    # CPU usage: diff /proc/stat idle vs total (Linux only)
    usage_percent = 0.0
    try:
        def _read_stat():
            with open("/proc/stat") as f:
                parts = f.readline().split()
            vals = list(map(int, parts[1:]))
            idle = vals[3]
            total = sum(vals)
            return idle, total

        idle1, total1 = _read_stat()
        time.sleep(0.1)
        idle2, total2 = _read_stat()
        d_idle = idle2 - idle1
        d_total = total2 - total1
        if d_total > 0:
            usage_percent = round((1 - d_idle / d_total) * 100, 1)
    except Exception:
        pass

    return CpuInfo(
        usage_percent=min(100.0, max(0.0, usage_percent)),
        cores=cores,
        model=model,
        load_avg=load,
    )


def _get_memory_info() -> MemoryInfo:
    """Parse /proc/meminfo for total/available bytes."""
    total = 0
    available = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1]) * 1024
    except Exception:
        # Fallback: use resource module
        pass

    used = total - available
    usage_pct = round((used / total * 100), 1) if total > 0 else 0.0

    return MemoryInfo(
        total_bytes=total,
        used_bytes=used,
        available_bytes=available,
        usage_percent=min(100.0, max(0.0, usage_pct)),
    )


def _get_disk_info() -> List[DiskPartition]:
    """Run df to collect disk partitions."""
    partitions: List[DiskPartition] = []
    out = _run(["df", "--output=target,size,used,avail", "--block-size=1", "-x", "tmpfs", "-x", "devtmpfs"])
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            mountpoint = parts[0]
            total = int(parts[1])
            used = int(parts[2])
            avail = int(parts[3])
            usage = round((used / total * 100), 1) if total > 0 else 0.0
            partitions.append(DiskPartition(
                mountpoint=mountpoint,
                total_bytes=total,
                used_bytes=used,
                available_bytes=avail,
                usage_percent=min(100.0, max(0.0, usage)),
            ))
        except (ValueError, ZeroDivisionError):
            continue
    return partitions[:8]  # cap at 8 partitions


def _get_network_info() -> List[NetworkInterface]:
    """Parse /proc/net/dev for rx/tx bytes."""
    ifaces: List[NetworkInterface] = []
    try:
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                parts = line.split()
                if not parts:
                    continue
                iface = parts[0].rstrip(":")
                if iface in ("lo",):
                    continue
                try:
                    rx = int(parts[1])
                    tx = int(parts[9])
                    ifaces.append(NetworkInterface(interface=iface, rx_bytes=rx, tx_bytes=tx))
                except (IndexError, ValueError):
                    continue
    except Exception:
        pass
    return ifaces[:8]


# ---------------------------------------------------------------------------
# Workload models
# ---------------------------------------------------------------------------

WORKLOAD_THRESHOLDS = {
    "queue_depth_normal": _num_env("MC_WORKLOAD_QUEUE_DEPTH_NORMAL", 20),
    "queue_depth_throttle": _num_env("MC_WORKLOAD_QUEUE_DEPTH_THROTTLE", 50),
    "queue_depth_shed": _num_env("MC_WORKLOAD_QUEUE_DEPTH_SHED", 100),
    "busy_agent_ratio_throttle": _num_env("MC_WORKLOAD_BUSY_RATIO_THROTTLE", 0.8),
    "busy_agent_ratio_shed": _num_env("MC_WORKLOAD_BUSY_RATIO_SHED", 0.95),
    "error_rate_throttle": _num_env("MC_WORKLOAD_ERROR_RATE_THROTTLE", 0.1),
    "error_rate_shed": _num_env("MC_WORKLOAD_ERROR_RATE_SHED", 0.25),
    "recent_window_seconds": max(1, int(_num_env("MC_WORKLOAD_RECENT_WINDOW_SECONDS", 300))),
}


class CapacityMetrics(BaseModel):
    active_tasks: int = 0
    tasks_last_5m: int = 0
    errors_last_5m: int = 0
    error_rate_5m: float = 0.0
    completions_last_hour: int = 0
    avg_completion_rate_per_hour: float = 0.0


class QueueMetrics(BaseModel):
    total_pending: int = 0
    by_status: Dict[str, int] = Field(default_factory=dict)
    oldest_pending_age_seconds: Optional[float] = None
    estimated_wait_seconds: Optional[float] = None
    estimated_wait_confidence: str = "unknown"


class WorkloadRecommendation(BaseModel):
    action: str  # normal | throttle | shed | pause
    reason: str
    details: List[str] = Field(default_factory=list)
    submit_ok: bool = True
    suggested_delay_ms: int = 0


class WorkloadResponse(BaseModel):
    timestamp: int
    capacity: CapacityMetrics
    queue: QueueMetrics
    recommendation: WorkloadRecommendation
    thresholds: Dict[str, Any]


# ---------------------------------------------------------------------------
# Workload implementation
# ---------------------------------------------------------------------------

_ACTION_ORDER = ["normal", "throttle", "shed", "pause"]


def _escalate(current: str, proposed: str) -> str:
    ci = _ACTION_ORDER.index(current) if current in _ACTION_ORDER else 0
    pi = _ACTION_ORDER.index(proposed) if proposed in _ACTION_ORDER else 0
    return _ACTION_ORDER[max(ci, pi)]


def _build_workload(exec_user: str) -> WorkloadResponse:
    """Build workload response by inspecting task queues via Redis."""
    queue = TaskQueue(db_path=None, exec_user=exec_user)
    now = int(time.time())

    # ── capacity ─────────────────────────────────────────────────────────
    try:
        todo_tasks = queue.get_todo_tasks()
        in_progress = queue.get_in_progress_tasks()
        active = len(in_progress)
        total_pending = len(todo_tasks) + active
    except Exception:
        todo_tasks = []
        in_progress = []
        active = 0
        total_pending = 0

    # ── queue by status ───────────────────────────────────────────────────
    by_status = {
        "todo": len(todo_tasks),
        "doing": len(in_progress),
    }

    # oldest task
    oldest_age: Optional[float] = None
    try:
        all_pending = list(todo_tasks) + list(in_progress)
        if all_pending:
            oldest_ts = min(
                getattr(t, "created_at", 0) or 0 for t in all_pending
            )
            if oldest_ts:
                # created_at may be datetime or float/int
                if hasattr(oldest_ts, "timestamp"):
                    oldest_ts = oldest_ts.timestamp()
                oldest_age = max(0.0, now - float(oldest_ts))
    except Exception:
        pass

    capacity = CapacityMetrics(
        active_tasks=active,
        tasks_last_5m=0,
        errors_last_5m=0,
        error_rate_5m=0.0,
        completions_last_hour=0,
        avg_completion_rate_per_hour=0.0,
    )

    queue_metrics = QueueMetrics(
        total_pending=total_pending,
        by_status=by_status,
        oldest_pending_age_seconds=oldest_age,
        estimated_wait_seconds=None,
        estimated_wait_confidence="unknown",
    )

    # ── recommendation ────────────────────────────────────────────────────
    level = "normal"
    reasons: List[str] = []
    thresholds = WORKLOAD_THRESHOLDS

    if total_pending >= thresholds["queue_depth_shed"]:
        level = _escalate(level, "shed")
        reasons.append(f"Queue depth critical: {total_pending} pending tasks")
    elif total_pending >= thresholds["queue_depth_throttle"]:
        level = _escalate(level, "throttle")
        reasons.append(f"Queue depth high: {total_pending} pending tasks")

    action_descriptions = {
        "normal": "System healthy — submit work freely",
        "throttle": "System under load — reduce submission rate and defer non-critical work",
        "shed": "System overloaded — submit only critical/high-priority work, defer everything else",
        "pause": "System unavailable — hold all submissions until capacity returns",
    }
    delay_map = {"normal": 0, "throttle": 2000, "shed": 10000, "pause": 30000}

    recommendation = WorkloadRecommendation(
        action=level,
        reason=action_descriptions.get(level, ""),
        details=reasons if reasons else ["All metrics within normal bounds"],
        submit_ok=level in ("normal", "throttle"),
        suggested_delay_ms=delay_map.get(level, 0),
    )

    return WorkloadResponse(
        timestamp=now,
        capacity=capacity,
        queue=queue_metrics,
        recommendation=recommendation,
        thresholds=thresholds,
    )


# ---------------------------------------------------------------------------
# Standup models
# ---------------------------------------------------------------------------

class StandupAgentSummary(BaseModel):
    agent: str
    todo_tasks: int = 0
    doing_tasks: int = 0
    done_tasks: int = 0
    failed_tasks: int = 0


class StandupReportSummary(BaseModel):
    total_todo: int = 0
    total_doing: int = 0
    total_done: int = 0
    total_failed: int = 0


class StandupReport(BaseModel):
    generated_at: str
    exec_user: str
    summary: StandupReportSummary
    agents: List[StandupAgentSummary] = Field(default_factory=list)


class StandupResponse(BaseModel):
    standup: StandupReport


# ---------------------------------------------------------------------------
# Standup implementation
# ---------------------------------------------------------------------------

def _build_standup(exec_user: str) -> StandupReport:
    """Generate a standup report from task queue state.

    Ported from mission-control standup/route.ts.  In Nexus there are no
    per-agent DB rows; all tasks for an exec_user live in one queue.  We
    produce a single-agent summary entry with the full queue counts.
    """
    queue = TaskQueue(db_path=None, exec_user=exec_user)
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    try:
        todo_tasks = queue.get_todo_tasks()
        doing_tasks = queue.get_in_progress_tasks()
        todo_count = len(todo_tasks)
        doing_count = len(doing_tasks)
    except Exception:
        todo_count = 0
        doing_count = 0

    # Retrieve done / failed counts from SQLite task queue
    done_count = 0
    failed_count = 0
    try:
        done_tasks, done_count = queue.list_tasks(page=1, page_size=1, status="done")
        failed_tasks, failed_count = queue.list_tasks(page=1, page_size=1, status="failed")
    except Exception:
        pass

    summary = StandupReportSummary(
        total_todo=todo_count,
        total_doing=doing_count,
        total_done=done_count,
        total_failed=failed_count,
    )

    agent_summary = StandupAgentSummary(
        agent=exec_user,
        todo_tasks=todo_count,
        doing_tasks=doing_count,
        done_tasks=done_count,
        failed_tasks=failed_count,
    )

    return StandupReport(
        generated_at=now_iso,
        exec_user=exec_user,
        summary=summary,
        agents=[agent_summary],
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/system-monitor", response_model=SystemMonitorResponse)
async def system_monitor():
    """System resource usage: CPU, memory, disk, network.

    Ported from mission-control GET /api/system-monitor (system-monitor/route.ts).
    Returns real-time host metrics without requiring elevated privileges.
    """
    cpu = await asyncio.get_event_loop().run_in_executor(None, _get_cpu_info)
    memory = _get_memory_info()
    disk = await asyncio.get_event_loop().run_in_executor(None, _get_disk_info)
    network = _get_network_info()

    return SystemMonitorResponse(
        timestamp=int(time.time() * 1000),
        cpu=cpu,
        memory=memory,
        disk=disk,
        network=network,
    )


@router.get("/workload", response_model=WorkloadResponse)
async def get_workload():
    """Real-time workload signals for adaptive task submission.

    Ported from mission-control GET /api/workload (workload/route.ts).
    Returns queue depth, capacity metrics, and a recommendation
    (normal / throttle / shed / pause) so agents can make informed decisions
    about new work submission.
    """
    exec_user = settings.exec_user or "default"
    return await asyncio.get_event_loop().run_in_executor(
        None, _build_workload, exec_user
    )


@router.post("/standup", response_model=StandupResponse)
@router.get("/standup", response_model=StandupResponse)
async def get_standup():
    """Generate a daily standup report from current task queue state.

    Ported from mission-control POST /api/standup (standup/route.ts).
    Returns per-agent task counts (todo/doing/done/failed) aggregated
    from the Redis-backed task store.
    """
    exec_user = settings.exec_user or "default"
    report = await asyncio.get_event_loop().run_in_executor(
        None, _build_standup, exec_user
    )
    return StandupResponse(standup=report)

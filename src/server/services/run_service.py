# -*- coding: utf-8 -*-
"""Agent Run Protocol — Redis-backed implementation.

Ported from mission-control src/lib/runs.ts (commit d4f55dd).

Manages AgentRun objects per the agent-run protocol spec
(https://github.com/0xNyk/agent-run).  SQLite replaced by Redis:

Key layout (per exec_user namespace):
  run:{exec_user}:{run_id}        — HASH  full run fields
  runs:{exec_user}:all            — ZSET  run_id -> started_at (epoch)
  runs:{exec_user}:by_agent:{aid} — ZSET  run_id -> started_at
  runs:{exec_user}:by_status:{s}  — ZSET  run_id -> started_at
  runs:{exec_user}:by_task:{tid}  — ZSET  run_id -> started_at
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, List, Optional

from ..logger import get_logger
from .redis_client import get_redis_client, RedisClient

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_EXEC_USER = "default"
_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 200
_PROTOCOL_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Type literals (mirrors agent-run spec)
# ---------------------------------------------------------------------------

RunStatus = str   # 'pending'|'running'|'completed'|'failed'|'cancelled'|'timeout'
RunOutcome = str  # 'success'|'failed'|'partial'|'abandoned'
RunTrigger = str  # 'manual'|'cron'|'webhook'|'agent'|'pipeline'|'queue'
StepType = str    # 'reasoning'|'tool_call'|'tool_result'|'message'|'error'|'handoff'

VALID_STATUSES = {"pending", "running", "completed", "failed", "cancelled", "timeout"}
VALID_OUTCOMES = {"success", "failed", "partial", "abandoned"}


# ---------------------------------------------------------------------------
# Provenance helpers (SHA-256, same algorithm as MC)
# ---------------------------------------------------------------------------

def compute_run_hash(
    agent_id: str,
    model: Optional[str] = None,
    tools_available: Optional[List[str]] = None,
    config_hash: Optional[str] = None,
    trigger: Optional[str] = None,
) -> str:
    """Compute a deterministic SHA-256 run hash.

    Canonical form mirrors MC's computeRunHash() so hashes are compatible
    when both systems track the same agent.
    """
    canonical = "|".join([
        agent_id,
        model or "",
        json.dumps(sorted(tools_available or [])),
        config_hash or "",
        trigger or "",
    ])
    return hashlib.sha256(canonical.encode()).hexdigest()


def compute_config_hash(config: Any) -> str:
    return hashlib.sha256(json.dumps(config or {}).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------

def _run_key(exec_user: str, run_id: str) -> str:
    return f"run:{exec_user}:{run_id}"

def _all_runs_key(exec_user: str) -> str:
    return f"runs:{exec_user}:all"

def _agent_runs_key(exec_user: str, agent_id: str) -> str:
    return f"runs:{exec_user}:by_agent:{agent_id}"

def _status_runs_key(exec_user: str, status: str) -> str:
    return f"runs:{exec_user}:by_status:{status}"

def _task_runs_key(exec_user: str, task_id: str) -> str:
    return f"runs:{exec_user}:by_task:{task_id}"


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _to_hash(run: dict) -> dict[str, str]:
    """Flatten an AgentRun dict for storage as a Redis HASH (all values strings)."""
    def _s(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, (dict, list)):
            return json.dumps(v)
        return str(v)

    return {k: _s(v) for k, v in run.items()}


def _from_hash(data: dict[str, str]) -> dict:
    """Reconstruct an AgentRun dict from a Redis HASH."""
    def _parse_json(v: str, fallback: Any) -> Any:
        if not v:
            return fallback
        try:
            return json.loads(v)
        except Exception:
            return fallback

    def _maybe(v: str) -> Optional[str]:
        return v if v else None

    def _maybeint(v: str) -> Optional[int]:
        if not v:
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    def _maybefloat(v: str) -> Optional[float]:
        if not v:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    return {
        "id": data.get("id", ""),
        "agent_id": data.get("agent_id", ""),
        "agent_name": _maybe(data.get("agent_name", "")),
        "model": _maybe(data.get("model", "")),
        "provider": _maybe(data.get("provider", "")),
        "runtime": _maybe(data.get("runtime", "")),
        "runtime_version": _maybe(data.get("runtime_version", "")),
        "trigger": _maybe(data.get("trigger", "")),
        "parent_run_id": _maybe(data.get("parent_run_id", "")),
        "task_id": _maybe(data.get("task_id", "")),
        "status": data.get("status", "pending"),
        "outcome": _maybe(data.get("outcome", "")),
        "started_at": data.get("started_at", ""),
        "ended_at": _maybe(data.get("ended_at", "")),
        "duration_ms": _maybeint(data.get("duration_ms", "")),
        "steps": _parse_json(data.get("steps", ""), []),
        "tools_available": _parse_json(data.get("tools_available", ""), []),
        "cost": _parse_json(data.get("cost", ""), {"input_tokens": 0, "output_tokens": 0}),
        "provenance": _parse_json(data.get("provenance", ""), {}),
        "eval": _parse_json(data.get("eval", ""), None),
        "error": _maybe(data.get("error", "")),
        "git_branch": _maybe(data.get("git_branch", "")),
        "git_commit": _maybe(data.get("git_commit", "")),
        "workspace_id": _maybe(data.get("workspace_id", "")),
        "tags": _parse_json(data.get("tags", ""), []),
        "metadata": _parse_json(data.get("metadata", ""), {}),
    }


# ---------------------------------------------------------------------------
# RunService
# ---------------------------------------------------------------------------

class RunService:
    """Agent Run Protocol service backed by Redis.

    Mirrors MC's runs.ts CRUD surface, ported to Python/Redis.
    """

    def __init__(self, exec_user: str = _DEFAULT_EXEC_USER, redis_client: Optional[RedisClient] = None):
        self.exec_user = exec_user
        self._redis: RedisClient = redis_client or get_redis_client()

    # --- CRUD ---

    def create_run(self, run: dict) -> dict:
        """Persist a new AgentRun and return the hydrated record."""
        run_id = run.get("id") or str(uuid.uuid4())
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        started_at = run.get("started_at") or now_iso

        # Compute provenance hash if not supplied
        provenance = run.get("provenance") or {}
        if not provenance.get("run_hash"):
            provenance["run_hash"] = compute_run_hash(
                agent_id=run.get("agent_id", ""),
                model=run.get("model"),
                tools_available=run.get("tools_available"),
                config_hash=provenance.get("config_hash"),
                trigger=run.get("trigger"),
            )
        if not provenance.get("created_at"):
            provenance["created_at"] = now_iso

        # Build the canonical record
        record: dict = {
            "id": run_id,
            "agent_id": run.get("agent_id", ""),
            "agent_name": run.get("agent_name"),
            "model": run.get("model"),
            "provider": run.get("provider"),
            "runtime": run.get("runtime", "nexus"),
            "runtime_version": run.get("runtime_version"),
            "trigger": run.get("trigger"),
            "parent_run_id": run.get("parent_run_id"),
            "task_id": run.get("task_id"),
            "status": run.get("status", "pending"),
            "outcome": run.get("outcome"),
            "started_at": started_at,
            "ended_at": run.get("ended_at"),
            "duration_ms": run.get("duration_ms"),
            "steps": run.get("steps") or [],
            "tools_available": run.get("tools_available") or [],
            "cost": run.get("cost") or {"input_tokens": 0, "output_tokens": 0},
            "provenance": provenance,
            "eval": run.get("eval"),
            "error": run.get("error"),
            "git_branch": run.get("git_branch"),
            "git_commit": run.get("git_commit"),
            "workspace_id": run.get("workspace_id"),
            "tags": run.get("tags") or [],
            "metadata": run.get("metadata") or {},
        }

        # Persist to Redis
        key = _run_key(self.exec_user, run_id)
        self._redis.hset(key, mapping=_to_hash(record))

        # Index in sorted sets using started_at epoch as score
        try:
            score = time.mktime(time.strptime(started_at, "%Y-%m-%dT%H:%M:%SZ"))
        except Exception:
            score = time.time()

        self._redis.zadd(_all_runs_key(self.exec_user), {run_id: score})
        self._redis.zadd(_agent_runs_key(self.exec_user, record["agent_id"]), {run_id: score})
        self._redis.zadd(_status_runs_key(self.exec_user, record["status"]), {run_id: score})
        if record.get("task_id"):
            self._redis.zadd(_task_runs_key(self.exec_user, record["task_id"]), {run_id: score})

        logger.info(f"run.created id={run_id} agent={record['agent_id']}")
        return record

    def get_run(self, run_id: str) -> Optional[dict]:
        """Return a single run by ID, or None if not found."""
        key = _run_key(self.exec_user, run_id)
        data = self._redis.hgetall(key)
        if not data:
            return None
        return _from_hash(data)

    def update_run(self, run_id: str, updates: dict) -> Optional[dict]:
        """Apply partial updates to a run. Returns updated record or None."""
        existing = self.get_run(run_id)
        if existing is None:
            return None

        # Track old status to update index
        old_status = existing.get("status", "")

        # Apply simple scalar updates
        for field in ("status", "outcome", "ended_at", "duration_ms", "error",
                      "model", "provider", "git_branch", "git_commit"):
            if field in updates and updates[field] is not None:
                existing[field] = updates[field]

        # Apply complex fields
        for field in ("steps", "cost", "tags", "metadata"):
            if field in updates and updates[field] is not None:
                existing[field] = updates[field]

        # Persist
        key = _run_key(self.exec_user, run_id)
        self._redis.hset(key, mapping=_to_hash(existing))

        # Update status index if status changed
        new_status = existing.get("status", "")
        if old_status != new_status:
            self._redis.zrem(_status_runs_key(self.exec_user, old_status), run_id)
            try:
                score = time.mktime(time.strptime(existing["started_at"], "%Y-%m-%dT%H:%M:%SZ"))
            except Exception:
                score = time.time()
            self._redis.zadd(_status_runs_key(self.exec_user, new_status), {run_id: score})

        logger.debug(f"run.updated id={run_id} status={new_status}")
        return existing

    def attach_eval(self, run_id: str, eval_result: dict) -> Optional[dict]:
        """Attach an eval result to an existing run."""
        existing = self.get_run(run_id)
        if existing is None:
            return None
        existing["eval"] = eval_result
        key = _run_key(self.exec_user, run_id)
        self._redis.hset(key, mapping=_to_hash(existing))
        logger.debug(f"run.eval_attached id={run_id}")
        return existing

    def list_runs(
        self,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        since: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = _DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> dict:
        """List runs with optional filtering. Returns {runs, total}."""
        limit = min(limit, _MAX_LIST_LIMIT)

        # Pick the tightest index available
        if task_id:
            index_key = _task_runs_key(self.exec_user, task_id)
        elif agent_id:
            index_key = _agent_runs_key(self.exec_user, agent_id)
        elif status:
            index_key = _status_runs_key(self.exec_user, status)
        else:
            index_key = _all_runs_key(self.exec_user)

        # Convert 'since' ISO string to epoch score for range filter
        since_score: float = 0.0
        if since:
            try:
                since_score = time.mktime(time.strptime(since, "%Y-%m-%dT%H:%M:%SZ"))
            except Exception:
                since_score = 0.0

        # Fetch IDs from sorted set, newest first (REV + score range)
        all_ids: List[str] = self._redis.zrangebyscore(
            index_key,
            since_score if since_score else "-inf",
            "+inf",
        ) or []
        all_ids = list(reversed(all_ids))  # newest first

        # Secondary in-Python filters for combinations not covered by index
        runs: List[dict] = []
        for run_id in all_ids:
            run = self.get_run(run_id)
            if run is None:
                continue
            # Secondary filter: cross-field AND conditions
            if agent_id and run.get("agent_id") != agent_id:
                continue
            if status and run.get("status") != status:
                continue
            if task_id and run.get("task_id") != task_id:
                continue
            runs.append(run)

        total = len(runs)
        page = runs[offset: offset + limit]
        return {"runs": page, "total": total}

    def get_leaderboard(
        self,
        benchmark_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        """Return eval leaderboard: agents ranked by avg_score DESC."""
        all_ids: List[str] = self._redis.zrangebyscore(
            _all_runs_key(self.exec_user), "-inf", "+inf"
        ) or []

        # Aggregate by (agent_name or agent_id, model, runtime)
        agg: dict[tuple, dict] = {}
        for run_id in all_ids:
            run = self.get_run(run_id)
            if not run:
                continue
            ev = run.get("eval")
            if not isinstance(ev, dict) or ev.get("score") is None:
                continue
            if benchmark_id and ev.get("benchmark_id") != benchmark_id:
                continue

            key = (
                run.get("agent_name") or run.get("agent_id", ""),
                run.get("model") or "unknown",
                run.get("runtime") or "unknown",
            )
            if key not in agg:
                agg[key] = {"scores": [], "passes": [], "costs": []}
            agg[key]["scores"].append(float(ev["score"]))
            agg[key]["passes"].append(1 if ev.get("pass") else 0)
            cost = run.get("cost") or {}
            agg[key]["costs"].append(float(cost.get("cost_usd") or 0))

        rows = []
        for (agent_name, model, runtime), vals in agg.items():
            n = len(vals["scores"])
            rows.append({
                "agent_name": agent_name,
                "model": model,
                "runtime": runtime,
                "avg_score": sum(vals["scores"]) / n,
                "pass_rate": sum(vals["passes"]) / n,
                "avg_cost_usd": sum(vals["costs"]) / n,
                "run_count": n,
            })

        rows.sort(key=lambda r: r["avg_score"], reverse=True)
        return rows[:limit]


# ---------------------------------------------------------------------------
# Module-level factory (mirrors MC's singleton getDatabase() pattern)
# ---------------------------------------------------------------------------

def get_run_service(exec_user: str = _DEFAULT_EXEC_USER) -> RunService:
    """Return a RunService for the given exec_user."""
    return RunService(exec_user=exec_user)

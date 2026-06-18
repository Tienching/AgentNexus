# -*- coding: utf-8 -*-
"""Agent Run Protocol — SQLite-backed implementation.

Ported from mission-control src/lib/runs.ts (commit d4f55dd).

Manages AgentRun objects per the agent-run protocol spec.
Replaces Redis multi-key structure with a single `agent_runs` table plus SQL indexes.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, List, Optional

from ..logger import get_logger
from ...runtime.stores.db import Database, get_db

logger = get_logger(__name__)

_DEFAULT_EXEC_USER = "default"
_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 200

_PROTOCOL_VERSION = "v1"
VALID_STATUSES = {"pending", "running", "completed", "failed", "cancelled", "timeout"}
VALID_OUTCOMES = {"success", "failed", "partial", "abandoned"}


def compute_run_hash(
    agent_id: str,
    model: Optional[str] = None,
    tools_available: Optional[List[str]] = None,
    config_hash: Optional[str] = None,
    trigger: Optional[str] = None,
) -> str:
    canonical = "|".join([
        agent_id, model or "",
        json.dumps(sorted(tools_available or [])),
        config_hash or "", trigger or "",
    ])
    return hashlib.sha256(canonical.encode()).hexdigest()


def compute_config_hash(config: Any) -> str:
    return hashlib.sha256(json.dumps(config or {}).encode()).hexdigest()


def _to_row(run: dict, exec_user: str) -> dict:
    def _j(v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, (dict, list)):
            return json.dumps(v)
        return str(v)

    return {
        "id": run.get("id", ""),
        "exec_user": exec_user,
        "agent_id": run.get("agent_id", ""),
        "agent_name": run.get("agent_name"),
        "model": run.get("model"),
        "provider": run.get("provider"),
        "runtime": run.get("runtime", "claude"),
        "runtime_version": run.get("runtime_version"),
        "trigger": run.get("trigger"),
        "parent_run_id": run.get("parent_run_id"),
        "task_id": run.get("task_id"),
        "status": run.get("status", "pending"),
        "outcome": run.get("outcome"),
        "started_at": run.get("started_at", ""),
        "ended_at": run.get("ended_at"),
        "duration_ms": run.get("duration_ms"),
        "steps_json": _j(run.get("steps")),
        "tools_available_json": _j(run.get("tools_available")),
        "cost_json": _j(run.get("cost")),
        "provenance_json": _j(run.get("provenance")),
        "eval_json": _j(run.get("eval")),
        "error": run.get("error"),
        "git_branch": run.get("git_branch"),
        "git_commit": run.get("git_commit"),
        "workspace_id": run.get("workspace_id"),
        "tags_json": _j(run.get("tags")),
        "metadata_json": _j(run.get("metadata")),
    }


def _from_row(row: dict) -> dict:
    def _pj(v: Optional[str], fallback: Any) -> Any:
        if not v:
            return fallback
        try:
            return json.loads(v)
        except Exception:
            return fallback

    return {
        "id": row.get("id", ""),
        "agent_id": row.get("agent_id", ""),
        "agent_name": row.get("agent_name"),
        "model": row.get("model"),
        "provider": row.get("provider"),
        "runtime": row.get("runtime", "nexus"),
        "runtime_version": row.get("runtime_version"),
        "trigger": row.get("trigger"),
        "parent_run_id": row.get("parent_run_id"),
        "task_id": row.get("task_id"),
        "status": row.get("status", "pending"),
        "outcome": row.get("outcome"),
        "started_at": row.get("started_at", ""),
        "ended_at": row.get("ended_at"),
        "duration_ms": row.get("duration_ms"),
        "steps": _pj(row.get("steps_json"), []),
        "tools_available": _pj(row.get("tools_available_json"), []),
        "cost": _pj(row.get("cost_json"), {"input_tokens": 0, "output_tokens": 0}),
        "provenance": _pj(row.get("provenance_json"), {}),
        "eval": _pj(row.get("eval_json"), None),
        "error": row.get("error"),
        "git_branch": row.get("git_branch"),
        "git_commit": row.get("git_commit"),
        "workspace_id": row.get("workspace_id"),
        "tags": _pj(row.get("tags_json"), []),
        "metadata": _pj(row.get("metadata_json"), {}),
    }


_RUN_FIELDS = list(_to_row({}, "x").keys())
_RUN_COLUMNS = ", ".join(_RUN_FIELDS)
_RUN_PLACEHOLDERS = ", ".join(["?"] * len(_RUN_FIELDS))


class RunService:
    """Agent Run Protocol service backed by SQLite."""

    def __init__(self, exec_user: str = _DEFAULT_EXEC_USER, db: Optional[Database] = None, redis_client=None):
        self.exec_user = exec_user
        self._db = db or get_db()
        self._redis = redis_client

    def _redis_run_key(self, run_id: str) -> str:
        return f"runs:{self.exec_user}:run:{run_id}"

    def _redis_index_all(self) -> str:
        return f"runs:{self.exec_user}:all"

    def _redis_index_agent(self, agent_id: str) -> str:
        return f"runs:{self.exec_user}:by_agent:{agent_id}"

    def _redis_index_status(self, status: str) -> str:
        return f"runs:{self.exec_user}:by_status:{status}"

    def _redis_index_task(self, task_id: str) -> str:
        return f"runs:{self.exec_user}:by_task:{task_id}"

    def _sync_redis_indexes(self, run: dict, *, previous_status: Optional[str] = None) -> None:
        if self._redis is None:
            return
        score = time.time()
        run_id = run.get("id", "")
        agent_id = run.get("agent_id", "")
        status = run.get("status", "pending")
        task_id = run.get("task_id")
        self._redis.hset(self._redis_run_key(run_id), mapping={"data": json.dumps(run)})
        self._redis.zadd(self._redis_index_all(), {run_id: score})
        if agent_id:
            self._redis.zadd(self._redis_index_agent(agent_id), {run_id: score})
        self._redis.zadd(self._redis_index_status(status), {run_id: score})
        if previous_status and previous_status != status:
            self._redis.zrem(self._redis_index_status(previous_status), run_id)
        if task_id:
            self._redis.zadd(self._redis_index_task(task_id), {run_id: score})

    def create_run(self, run: dict) -> dict:
        run_id = run.get("id") or str(uuid.uuid4())
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        started_at = run.get("started_at") or now_iso

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

        record = {
            "id": run_id, "agent_id": run.get("agent_id", ""),
            "agent_name": run.get("agent_name"), "model": run.get("model"),
            "provider": run.get("provider"), "runtime": run.get("runtime", "claude"),
            "runtime_version": run.get("runtime_version"), "trigger": run.get("trigger"),
            "parent_run_id": run.get("parent_run_id"), "task_id": run.get("task_id"),
            "status": run.get("status", "pending"), "outcome": run.get("outcome"),
            "started_at": started_at, "ended_at": run.get("ended_at"),
            "duration_ms": run.get("duration_ms"),
            "steps": run.get("steps") or [], "tools_available": run.get("tools_available") or [],
            "cost": run.get("cost") or {"input_tokens": 0, "output_tokens": 0},
            "provenance": provenance, "eval": run.get("eval"), "error": run.get("error"),
            "git_branch": run.get("git_branch"), "git_commit": run.get("git_commit"),
            "workspace_id": run.get("workspace_id"),
            "tags": run.get("tags") or [], "metadata": run.get("metadata") or {},
        }

        row = _to_row(record, self.exec_user)
        values = [row[k] for k in _RUN_FIELDS]

        with self._db.transaction() as conn:
            conn.execute(f"INSERT INTO agent_runs ({_RUN_COLUMNS}) VALUES ({_RUN_PLACEHOLDERS})", values)

        self._sync_redis_indexes(record)
        logger.info(f"run.created id={run_id} agent={record['agent_id']}")
        return record

    def get_run(self, run_id: str) -> Optional[dict]:
        row = self._db.execute_fetchone(
            "SELECT * FROM agent_runs WHERE exec_user = ? AND id = ?",
            (self.exec_user, run_id),
        )
        if not row:
            return None
        return _from_row(row)

    def update_run(self, run_id: str, updates: dict) -> Optional[dict]:
        existing = self.get_run(run_id)
        if existing is None:
            return None
        previous_status = existing.get("status")
        for field in ("status", "outcome", "ended_at", "duration_ms", "error", "model", "provider", "git_branch", "git_commit"):
            if field in updates and updates[field] is not None:
                existing[field] = updates[field]
        for field in ("steps", "cost", "tags", "metadata"):
            if field in updates and updates[field] is not None:
                existing[field] = updates[field]
        row = _to_row(existing, self.exec_user)
        update_cols = [k for k in _RUN_FIELDS if k not in ("id", "exec_user")]
        set_clause = ", ".join(f"{k} = ?" for k in update_cols)
        values = [row[k] for k in update_cols] + [self.exec_user, run_id]
        with self._db.transaction() as conn:
            conn.execute(f"UPDATE agent_runs SET {set_clause} WHERE exec_user = ? AND id = ?", values)
        self._sync_redis_indexes(existing, previous_status=previous_status)
        logger.debug(f"run.updated id={run_id} status={existing.get('status', '')}")
        return existing

    def attach_eval(self, run_id: str, eval_result: dict) -> Optional[dict]:
        existing = self.get_run(run_id)
        if existing is None:
            return None
        existing["eval"] = eval_result
        row = _to_row(existing, self.exec_user)
        update_cols = [k for k in _RUN_FIELDS if k not in ("id", "exec_user")]
        set_clause = ", ".join(f"{k} = ?" for k in update_cols)
        values = [row[k] for k in update_cols] + [self.exec_user, run_id]
        with self._db.transaction() as conn:
            conn.execute(f"UPDATE agent_runs SET {set_clause} WHERE exec_user = ? AND id = ?", values)
        self._sync_redis_indexes(existing)
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
        limit = min(limit, _MAX_LIST_LIMIT)
        conditions = ["exec_user = ?"]
        params: list = [self.exec_user]
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if task_id:
            conditions.append("task_id = ?")
            params.append(task_id)
        if since:
            conditions.append("started_at >= ?")
            params.append(since)
        where = " AND ".join(conditions)
        count_row = self._db.execute_fetchone(f"SELECT COUNT(*) as cnt FROM agent_runs WHERE {where}", params)
        total = count_row["cnt"] if count_row else 0
        rows = self._db.execute_fetchall(f"SELECT * FROM agent_runs WHERE {where} ORDER BY started_at DESC LIMIT ? OFFSET ?", params + [limit, offset])
        runs = [_from_row(r) for r in rows]
        return {"runs": runs, "total": total}

    def get_leaderboard(self, benchmark_id: Optional[str] = None, limit: int = 50) -> List[dict]:
        rows = self._db.execute_fetchall(
            "SELECT agent_name, agent_id, model, runtime, eval_json, cost_json FROM agent_runs WHERE exec_user = ?",
            (self.exec_user,),
        )
        agg: dict[tuple, dict] = {}
        for row in rows:
            ev = _parse_json_safe(row.get("eval_json"))
            if not isinstance(ev, dict) or ev.get("score") is None:
                continue
            if benchmark_id and ev.get("benchmark_id") != benchmark_id:
                continue
            key = (row.get("agent_name") or row.get("agent_id", ""), row.get("model") or "unknown", row.get("runtime") or "unknown")
            if key not in agg:
                agg[key] = {"scores": [], "passes": [], "costs": []}
            agg[key]["scores"].append(float(ev["score"]))
            agg[key]["passes"].append(1 if ev.get("pass") else 0)
            cost = _parse_json_safe(row.get("cost_json")) or {}
            agg[key]["costs"].append(float(cost.get("cost_usd") or 0))
        result = []
        for (agent_name, model, runtime), vals in agg.items():
            n = len(vals["scores"])
            result.append({"agent_name": agent_name, "model": model, "runtime": runtime, "avg_score": sum(vals["scores"]) / n, "pass_rate": sum(vals["passes"]) / n, "avg_cost_usd": sum(vals["costs"]) / n, "run_count": n})
        result.sort(key=lambda r: r["avg_score"], reverse=True)
        return result[:limit]


def _parse_json_safe(v: Optional[str]) -> Any:
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None


def get_run_service(exec_user: str = _DEFAULT_EXEC_USER) -> RunService:
    return RunService(exec_user=exec_user)

# -*- coding: utf-8 -*-
"""Tests for the Agent Run Protocol service and API router.

Ported from mission-control (commit d4f55dd).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_redis():
    """Minimal Redis mock that supports HASH + ZSET operations."""
    store: dict = {}   # key -> {field: value}  for HASH
    zsets: dict = {}   # key -> {member: score}  for ZSET

    mock = MagicMock()

    def hset(key, mapping=None, **kwargs):
        if mapping:
            store.setdefault(key, {}).update(mapping)
        for k, v in kwargs.items():
            store.setdefault(key, {})[k] = v

    def hgetall(key):
        return dict(store.get(key, {}))

    def zadd(key, members: dict):
        zsets.setdefault(key, {}).update(members)

    def zrem(key, *members):
        z = zsets.get(key, {})
        for m in members:
            z.pop(m, None)

    def zrangebyscore(key, min_score, max_score):
        z = zsets.get(key, {})
        result = []
        for member, score in z.items():
            if min_score == "-inf" or float(min_score) <= score:
                if max_score == "+inf" or score <= float(max_score):
                    result.append(member)
        result.sort(key=lambda m: z[m])
        return result

    mock.hset.side_effect = hset
    mock.hgetall.side_effect = hgetall
    mock.zadd.side_effect = zadd
    mock.zrem.side_effect = zrem
    mock.zrangebyscore.side_effect = zrangebyscore
    return mock


@pytest.fixture(autouse=True)
def _isolate_run_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_runs.db")
    monkeypatch.setenv("NEXUS_DB_PATH", db_path)
    from src.runtime.stores.db import Database
    Database._instance = None
    yield Path(db_path)
    Database._instance = None


def _make_svc(redis=None):
    from src.server.services.run_service import RunService
    return RunService(exec_user="test_user", redis_client=redis or _make_redis())


def _minimal_run(**kwargs):
    base = {
        "agent_id": "agent-alpha",
        "status": "pending",
        "started_at": "2026-03-31T08:00:00Z",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# compute_run_hash
# ---------------------------------------------------------------------------

class TestComputeRunHash:
    def test_deterministic(self):
        from src.server.services.run_service import compute_run_hash
        h1 = compute_run_hash("agent-1", model="claude", tools_available=["bash", "grep"])
        h2 = compute_run_hash("agent-1", model="claude", tools_available=["bash", "grep"])
        assert h1 == h2

    def test_tools_order_insensitive(self):
        from src.server.services.run_service import compute_run_hash
        h1 = compute_run_hash("a", tools_available=["grep", "bash"])
        h2 = compute_run_hash("a", tools_available=["bash", "grep"])
        assert h1 == h2

    def test_different_agents_differ(self):
        from src.server.services.run_service import compute_run_hash
        assert compute_run_hash("a") != compute_run_hash("b")

    def test_sha256_length(self):
        from src.server.services.run_service import compute_run_hash
        assert len(compute_run_hash("x")) == 64

    def test_none_fields_stable(self):
        from src.server.services.run_service import compute_run_hash
        h = compute_run_hash("a", model=None, tools_available=None, config_hash=None, trigger=None)
        assert len(h) == 64


class TestComputeConfigHash:
    def test_deterministic(self):
        from src.server.services.run_service import compute_config_hash
        assert compute_config_hash({"k": "v"}) == compute_config_hash({"k": "v"})

    def test_none_stable(self):
        from src.server.services.run_service import compute_config_hash
        assert len(compute_config_hash(None)) == 64


# ---------------------------------------------------------------------------
# RunService.create_run
# ---------------------------------------------------------------------------

class TestCreateRun:
    def test_returns_record_with_id(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run())
        assert run["id"]
        assert run["agent_id"] == "agent-alpha"

    def test_auto_generates_run_hash(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run())
        prov = run.get("provenance") or {}
        assert prov.get("run_hash")
        assert len(prov["run_hash"]) == 64

    def test_preserves_supplied_id(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run(id="my-run-id"))
        assert run["id"] == "my-run-id"

    def test_default_runtime_is_claude(self):
        # The default runtime/provider is claude (was nexus before the
        # daemon-platform refactor; nexus provider was removed).
        svc = _make_svc()
        run = svc.create_run(_minimal_run())
        assert run["runtime"] == "claude"

    def test_custom_fields_preserved(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run(
            model="claude-3",
            provider="claude",
            task_id="task-99",
            tags=["ci", "smoke"],
        ))
        assert run["model"] == "claude-3"
        assert run["provider"] == "claude"
        assert run["task_id"] == "task-99"
        assert "ci" in run["tags"]

    def test_cost_defaults(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run())
        cost = run.get("cost") or {}
        assert cost.get("input_tokens") == 0
        assert cost.get("output_tokens") == 0

    def test_steps_default_empty(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run())
        assert run["steps"] == []

    def test_supplied_provenance_hash_preserved(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run(provenance={"run_hash": "abc123"}))
        assert run["provenance"]["run_hash"] == "abc123"

    def test_indexed_in_all_runs_zset(self):
        redis = _make_redis()
        svc = _make_svc(redis)
        run = svc.create_run(_minimal_run())
        # zrangebyscore should find the ID
        ids = redis.zrangebyscore("runs:test_user:all", "-inf", "+inf")
        assert run["id"] in ids

    def test_indexed_by_agent(self):
        redis = _make_redis()
        svc = _make_svc(redis)
        run = svc.create_run(_minimal_run())
        ids = redis.zrangebyscore("runs:test_user:by_agent:agent-alpha", "-inf", "+inf")
        assert run["id"] in ids

    def test_indexed_by_status(self):
        redis = _make_redis()
        svc = _make_svc(redis)
        run = svc.create_run(_minimal_run(status="running"))
        ids = redis.zrangebyscore("runs:test_user:by_status:running", "-inf", "+inf")
        assert run["id"] in ids

    def test_indexed_by_task_when_present(self):
        redis = _make_redis()
        svc = _make_svc(redis)
        run = svc.create_run(_minimal_run(task_id="t-1"))
        ids = redis.zrangebyscore("runs:test_user:by_task:t-1", "-inf", "+inf")
        assert run["id"] in ids

    def test_no_task_index_when_absent(self):
        redis = _make_redis()
        svc = _make_svc(redis)
        run = svc.create_run(_minimal_run())
        ids = redis.zrangebyscore("runs:test_user:by_task:", "-inf", "+inf")
        assert run["id"] not in ids


# ---------------------------------------------------------------------------
# RunService.get_run
# ---------------------------------------------------------------------------

class TestGetRun:
    def test_returns_none_for_missing(self):
        svc = _make_svc()
        assert svc.get_run("nonexistent") is None

    def test_round_trip(self):
        svc = _make_svc()
        created = svc.create_run(_minimal_run(model="gemini"))
        fetched = svc.get_run(created["id"])
        assert fetched is not None
        assert fetched["model"] == "gemini"
        assert fetched["agent_id"] == "agent-alpha"

    def test_provenance_round_trip(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run())
        fetched = svc.get_run(run["id"])
        assert fetched["provenance"]["run_hash"]

    def test_tags_round_trip(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run(tags=["a", "b"]))
        fetched = svc.get_run(run["id"])
        assert fetched["tags"] == ["a", "b"]


# ---------------------------------------------------------------------------
# RunService.update_run
# ---------------------------------------------------------------------------

class TestUpdateRun:
    def test_returns_none_for_missing(self):
        svc = _make_svc()
        assert svc.update_run("nope", {"status": "completed"}) is None

    def test_updates_status(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run(status="running"))
        updated = svc.update_run(run["id"], {"status": "completed"})
        assert updated["status"] == "completed"

    def test_status_index_migrated(self):
        redis = _make_redis()
        svc = _make_svc(redis)
        run = svc.create_run(_minimal_run(status="running"))
        svc.update_run(run["id"], {"status": "completed"})
        # Should be in completed index, not running
        in_completed = redis.zrangebyscore("runs:test_user:by_status:completed", "-inf", "+inf")
        in_running = redis.zrangebyscore("runs:test_user:by_status:running", "-inf", "+inf")
        assert run["id"] in in_completed
        assert run["id"] not in in_running

    def test_updates_cost(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run())
        updated = svc.update_run(run["id"], {"cost": {"input_tokens": 100, "output_tokens": 50}})
        assert updated["cost"]["input_tokens"] == 100

    def test_updates_error(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run())
        updated = svc.update_run(run["id"], {"error": "timeout reached"})
        assert updated["error"] == "timeout reached"

    def test_no_op_fields_unchanged(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run(model="claude"))
        updated = svc.update_run(run["id"], {"status": "completed"})
        assert updated["model"] == "claude"


# ---------------------------------------------------------------------------
# RunService.attach_eval
# ---------------------------------------------------------------------------

class TestAttachEval:
    def test_returns_none_for_missing(self):
        svc = _make_svc()
        assert svc.attach_eval("nope", {"pass": True, "score": 1.0}) is None

    def test_eval_attached(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run())
        result = svc.attach_eval(run["id"], {"pass": True, "score": 0.9, "detail": "ok"})
        assert result is not None
        assert result["eval"]["score"] == 0.9
        assert result["eval"]["pass"] is True

    def test_eval_persisted(self):
        svc = _make_svc()
        run = svc.create_run(_minimal_run())
        svc.attach_eval(run["id"], {"pass": False, "score": 0.4})
        fetched = svc.get_run(run["id"])
        assert fetched["eval"]["score"] == 0.4


# ---------------------------------------------------------------------------
# RunService.list_runs
# ---------------------------------------------------------------------------

class TestListRuns:
    def _svc_with_runs(self):
        svc = _make_svc()
        svc.create_run(_minimal_run(agent_id="a1", status="completed", task_id="t1"))
        svc.create_run(_minimal_run(agent_id="a2", status="running"))
        svc.create_run(_minimal_run(agent_id="a1", status="running", task_id="t1"))
        return svc

    def test_returns_all(self):
        svc = self._svc_with_runs()
        result = svc.list_runs()
        assert result["total"] == 3

    def test_filter_by_agent(self):
        svc = self._svc_with_runs()
        result = svc.list_runs(agent_id="a1")
        assert result["total"] == 2
        assert all(r["agent_id"] == "a1" for r in result["runs"])

    def test_filter_by_status(self):
        svc = self._svc_with_runs()
        result = svc.list_runs(status="running")
        assert result["total"] == 2

    def test_filter_by_task_id(self):
        svc = self._svc_with_runs()
        result = svc.list_runs(task_id="t1")
        assert result["total"] == 2

    def test_pagination(self):
        svc = self._svc_with_runs()
        page1 = svc.list_runs(limit=2, offset=0)
        page2 = svc.list_runs(limit=2, offset=2)
        assert len(page1["runs"]) == 2
        assert len(page2["runs"]) == 1

    def test_limit_capped_at_200(self):
        from src.server.services.run_service import _MAX_LIST_LIMIT
        assert _MAX_LIST_LIMIT == 200


# ---------------------------------------------------------------------------
# RunService.get_leaderboard
# ---------------------------------------------------------------------------

class TestGetLeaderboard:
    def test_empty_when_no_evals(self):
        svc = _make_svc()
        svc.create_run(_minimal_run())
        rows = svc.get_leaderboard()
        assert rows == []

    def test_ranked_by_avg_score_desc(self):
        svc = _make_svc()
        r1 = svc.create_run(_minimal_run(agent_id="slow"))
        r2 = svc.create_run(_minimal_run(agent_id="fast"))
        svc.attach_eval(r1["id"], {"pass": False, "score": 0.4})
        svc.attach_eval(r2["id"], {"pass": True, "score": 0.9})
        rows = svc.get_leaderboard()
        assert rows[0]["agent_name"] == "fast"
        assert rows[1]["agent_name"] == "slow"

    def test_pass_rate_calculated(self):
        svc = _make_svc()
        for score, passed in [(0.8, True), (0.6, False)]:
            r = svc.create_run(_minimal_run(agent_id="mix"))
            svc.attach_eval(r["id"], {"pass": passed, "score": score})
        rows = svc.get_leaderboard()
        assert len(rows) == 1
        assert rows[0]["pass_rate"] == pytest.approx(0.5)
        assert rows[0]["run_count"] == 2

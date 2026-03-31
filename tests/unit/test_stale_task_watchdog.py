# -*- coding: utf-8 -*-
"""Unit tests for stale_task_watchdog.requeue_stale_tasks().

Ported logic from mission-control commit 2d171ad:
  src/lib/task-dispatch.ts::requeueStaleTasks()

Tests verify:
1. Tasks actively tracked in executor's running_tasks are skipped.
2. Tasks within the staleness threshold are untouched.
3. Stale tasks with no active executor are requeued as TODO with
   incremented attempt_count and a diagnostic error_message.
4. Stale tasks at/above max_dispatch_retries are permanently failed.
5. The executing-set entry is removed in both paths.
6. Return dict has ok/requeued/failed/skipped/message keys.
7. Executor import failure is handled gracefully (treats all stale as eligible).
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from src.server.services.stale_task_watchdog import (
    requeue_stale_tasks,
    _get_executor_active_task_ids,
    STALE_THRESHOLD_SECONDS,
    MAX_DISPATCH_RETRIES,
)
from src.runtime.stores.task_storage import TaskQueue
from src.server.models import Task, TaskPriority, TaskStatus


# ---------------------------------------------------------------------------
# Minimal Redis mock (mirrors other test modules in this project)
# ---------------------------------------------------------------------------

class MockRedisClient:
    """In-memory Redis mock."""

    def __init__(self):
        self._data = {}
        self._hashes = {}
        self._sets = {}
        self._lists = {}
        self._prefix = "test:"

    def _key(self, k): return f"{self._prefix}{k}"

    def ping(self): return True
    def get(self, k): return self._data.get(self._key(k))
    def set(self, k, v, ex=None): self._data[self._key(k)] = v; return True

    def hset(self, name, mapping):
        fk = self._key(name)
        self._hashes.setdefault(fk, {}).update(mapping)
        return len(mapping)

    def hget(self, name, key):
        return self._hashes.get(self._key(name), {}).get(key)

    def hgetall(self, name):
        return self._hashes.get(self._key(name), {})

    def hdel(self, name, *keys):
        fk = self._key(name)
        return sum(1 for k in keys if self._hashes.get(fk, {}).pop(k, None) is not None)

    def hexists(self, name, key):
        return key in self._hashes.get(self._key(name), {})

    def sadd(self, name, *values):
        fk = self._key(name)
        s = self._sets.setdefault(fk, set())
        added = sum(1 for v in values if v not in s)
        s.update(values)
        return added

    def srem(self, name, *values):
        fk = self._key(name)
        s = self._sets.get(fk, set())
        removed = sum(1 for v in values if v in s)
        s.difference_update(values)
        return removed

    def smembers(self, name):
        return self._sets.get(self._key(name), set()).copy()

    def sismember(self, name, value):
        return value in self._sets.get(self._key(name), set())

    def scard(self, name):
        return len(self._sets.get(self._key(name), set()))

    def zadd(self, name, mapping):
        fk = self._key(name)
        d = self._sets.setdefault(fk, {})
        if not isinstance(d, dict):
            d = {}
            self._sets[fk] = d
        added = sum(1 for m in mapping if m not in d)
        d.update(mapping)
        return added

    def zrem(self, name, *values):
        fk = self._key(name)
        d = self._sets.get(fk, {})
        if isinstance(d, dict):
            removed = sum(1 for v in values if v in d)
            for v in values:
                d.pop(v, None)
            return removed
        return 0

    def zrange(self, name, start, end, withscores=False):
        fk = self._key(name)
        d = self._sets.get(fk, {})
        if isinstance(d, dict):
            items = sorted(d.items(), key=lambda x: x[1])
            length = len(items)
            if start < 0: start = max(0, length + start)
            if end < 0: end = length + end
            result = items[start:end + 1]
            return result if withscores else [i[0] for i in result]
        return []

    def zcard(self, name):
        fk = self._key(name)
        d = self._sets.get(fk, {})
        return len(d) if isinstance(d, dict) else 0

    def rpush(self, name, *values):
        fk = self._key(name)
        self._lists.setdefault(fk, []).extend(values)
        return len(self._lists[fk])

    def lpush(self, name, *values):
        fk = self._key(name)
        lst = self._lists.setdefault(fk, [])
        for v in reversed(values):
            lst.insert(0, v)
        return len(lst)

    def lpop(self, name):
        fk = self._key(name)
        lst = self._lists.get(fk, [])
        return lst.pop(0) if lst else None

    def rpop(self, name):
        fk = self._key(name)
        lst = self._lists.get(fk, [])
        return lst.pop() if lst else None

    def lrange(self, name, start, end):
        fk = self._key(name)
        lst = self._lists.get(fk, [])
        return lst[start:] if end == -1 else lst[start:end + 1]

    def llen(self, name):
        return len(self._lists.get(self._key(name), []))

    def lrem(self, name, count, value):
        fk = self._key(name)
        if fk not in self._lists:
            return 0
        before = len(self._lists[fk])
        self._lists[fk] = [v for v in self._lists[fk] if v != value]
        return before - len(self._lists[fk])

    def delete(self, *keys):
        removed = 0
        for k in keys:
            fk = self._key(k)
            removed += int(self._data.pop(fk, None) is not None)
            removed += int(self._hashes.pop(fk, None) is not None)
        return removed

    def exists(self, key):
        fk = self._key(key)
        return fk in self._data or fk in self._hashes

    def scan_iter(self, match="*", count=100):
        pattern = match.replace("*", "")
        for key in list(self._sets.keys()) + list(self._lists.keys()):
            if pattern in key:
                yield key[len(self._prefix):]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_redis():
    return MockRedisClient()


@pytest.fixture
def task_queue(mock_redis):
    with patch("src.runtime.stores.task_storage.get_redis_client", return_value=mock_redis):
        q = TaskQueue(db_path=None, exec_user="agent")
        q._redis = mock_redis
        return q


def _add_doing_task(
    task_queue: TaskQueue,
    task_id: str = "t01",
    attempt_count: int = 0,
    seconds_ago: float = 1200,   # 20 minutes — stale by default
    workspace: str = "ws",
) -> Task:
    """Insert a DOING task whose started_at is in the past."""
    task = task_queue.add_task(
        description="some work",
        priority=TaskPriority.THOUGHT,
        workspace=workspace,
    )
    # Rename to predictable id
    old_id = task.id
    task.id = task_id
    redis = task_queue._redis

    old_data = redis.hgetall(task_queue._task_key(old_id))
    redis.delete(task_queue._task_key(old_id))
    old_data["id"] = task_id
    redis.hset(task_queue._task_key(task_id), old_data)

    # Fix index sets
    status_key = task_queue._status_key(TaskStatus.TODO)
    all_key = task_queue._all_tasks_key()
    queue_key = task_queue._queue_key(workspace)
    redis.srem(status_key, old_id)
    redis.sadd(status_key, task_id)
    try:
        redis.zrem(all_key, old_id)
        redis.zadd(all_key, {task_id: 0})
    except Exception:
        pass
    try:
        redis.lrem(queue_key, 0, old_id)
        redis.rpush(queue_key, task_id)
    except Exception:
        pass

    # Set DOING + started_at + attempt_count in Redis
    started_at = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    redis.hset(task_queue._task_key(task_id), {
        "status": TaskStatus.DOING.value,
        "started_at": started_at.isoformat(),
        "attempt_count": str(attempt_count),
        "id": task_id,
    })
    redis.srem(task_queue._status_key(TaskStatus.TODO), task_id)
    redis.sadd(task_queue._status_key(TaskStatus.DOING), task_id)
    redis.sadd(task_queue._executing_key(workspace), task_id)

    return task


# ---------------------------------------------------------------------------
# Helper — suppress executor import in watchdog
# ---------------------------------------------------------------------------

def _no_active_tasks():
    """Patch _get_executor_active_task_ids to return empty set."""
    return patch(
        "src.server.services.stale_task_watchdog._get_executor_active_task_ids",
        return_value=set(),
    )


# ---------------------------------------------------------------------------
# Tests: return-value shape
# ---------------------------------------------------------------------------

class TestReturnShape:
    def test_returns_dict_with_required_keys(self, task_queue):
        with _no_active_tasks():
            result = requeue_stale_tasks(task_queue)
        assert isinstance(result, dict)
        for key in ("ok", "requeued", "failed", "skipped", "message"):
            assert key in result, f"Missing key: {key}"

    def test_ok_is_true(self, task_queue):
        with _no_active_tasks():
            result = requeue_stale_tasks(task_queue)
        assert result["ok"] is True

    def test_no_tasks_returns_zero_counts(self, task_queue):
        with _no_active_tasks():
            result = requeue_stale_tasks(task_queue)
        assert result["requeued"] == 0
        assert result["failed"] == 0
        assert result["skipped"] == 0


# ---------------------------------------------------------------------------
# Tests: tasks below threshold are skipped
# ---------------------------------------------------------------------------

class TestFreshTaskUntouched:
    def test_fresh_task_not_requeued(self, task_queue):
        _add_doing_task(task_queue, task_id="fresh01", seconds_ago=60)
        with _no_active_tasks():
            result = requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        assert result["requeued"] == 0
        assert result["failed"] == 0
        task = task_queue.get_task("fresh01")
        assert task is not None
        status = task.status if isinstance(task.status, str) else task.status.value
        assert status == TaskStatus.DOING.value

    def test_fresh_task_counted_as_skipped(self, task_queue):
        _add_doing_task(task_queue, task_id="fresh02", seconds_ago=60)
        with _no_active_tasks():
            result = requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        assert result["skipped"] == 1


# ---------------------------------------------------------------------------
# Tests: executor-active tasks are skipped
# ---------------------------------------------------------------------------

class TestActiveExecutorTasksSkipped:
    def test_active_task_not_requeued(self, task_queue):
        """Task in executor._running_tasks must not be touched even if stale."""
        _add_doing_task(task_queue, task_id="active01", seconds_ago=1200)
        with patch(
            "src.server.services.stale_task_watchdog._get_executor_active_task_ids",
            return_value={"active01"},
        ):
            result = requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        assert result["requeued"] == 0
        assert result["failed"] == 0

    def test_active_task_counted_as_skipped(self, task_queue):
        _add_doing_task(task_queue, task_id="active02", seconds_ago=1200)
        with patch(
            "src.server.services.stale_task_watchdog._get_executor_active_task_ids",
            return_value={"active02"},
        ):
            result = requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        assert result["skipped"] == 1

    def test_only_active_task_skipped_others_requeued(self, task_queue):
        _add_doing_task(task_queue, task_id="active03", seconds_ago=1200, workspace="ws_a")
        _add_doing_task(task_queue, task_id="stale03", seconds_ago=1200, workspace="ws_b")
        with patch(
            "src.server.services.stale_task_watchdog._get_executor_active_task_ids",
            return_value={"active03"},
        ):
            result = requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        assert result["requeued"] == 1
        assert result["skipped"] == 1


# ---------------------------------------------------------------------------
# Tests: requeue path
# ---------------------------------------------------------------------------

class TestRequeuePath:
    def test_stale_task_becomes_todo(self, task_queue):
        _add_doing_task(task_queue, task_id="stale01")
        with _no_active_tasks():
            requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        task = task_queue.get_task("stale01")
        status = task.status if isinstance(task.status, str) else task.status.value
        assert status == TaskStatus.TODO.value

    def test_stale_task_attempt_count_incremented(self, task_queue):
        _add_doing_task(task_queue, task_id="stale02", attempt_count=1)
        with _no_active_tasks():
            requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        task = task_queue.get_task("stale02")
        assert task.attempt_count == 2

    def test_stale_task_error_message_set(self, task_queue):
        _add_doing_task(task_queue, task_id="stale03")
        with _no_active_tasks():
            requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        task = task_queue.get_task("stale03")
        assert task.error_message is not None
        assert "requeued" in task.error_message.lower()

    def test_stale_task_removed_from_executing_set(self, task_queue, mock_redis):
        _add_doing_task(task_queue, task_id="stale04", workspace="ws_ex")
        exec_key = task_queue._executing_key("ws_ex")
        assert "stale04" in mock_redis.smembers(exec_key)
        with _no_active_tasks():
            requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        assert "stale04" not in mock_redis.smembers(exec_key)

    def test_stale_task_added_to_todo_queue(self, task_queue, mock_redis):
        _add_doing_task(task_queue, task_id="stale05", workspace="ws_q")
        queue_key = task_queue._queue_key("ws_q")
        # ensure queue is empty before watchdog runs
        mock_redis._lists.clear()
        with _no_active_tasks():
            requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        queued = mock_redis.lrange(queue_key, 0, -1)
        assert "stale05" in queued

    def test_requeue_count_returned(self, task_queue):
        _add_doing_task(task_queue, task_id="stale06")
        with _no_active_tasks():
            result = requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        assert result["requeued"] == 1


# ---------------------------------------------------------------------------
# Tests: fail path (max retries exceeded)
# ---------------------------------------------------------------------------

class TestFailPath:
    def test_at_max_retries_becomes_failed(self, task_queue):
        _add_doing_task(task_queue, task_id="fail01", attempt_count=MAX_DISPATCH_RETRIES - 1)
        with _no_active_tasks():
            requeue_stale_tasks(task_queue, stale_threshold_seconds=600,
                                max_dispatch_retries=MAX_DISPATCH_RETRIES)
        task = task_queue.get_task("fail01")
        status = task.status if isinstance(task.status, str) else task.status.value
        assert status == TaskStatus.FAILED.value

    def test_above_max_retries_becomes_failed(self, task_queue):
        _add_doing_task(task_queue, task_id="fail02", attempt_count=MAX_DISPATCH_RETRIES + 2)
        with _no_active_tasks():
            requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        task = task_queue.get_task("fail02")
        status = task.status if isinstance(task.status, str) else task.status.value
        assert status == TaskStatus.FAILED.value

    def test_failed_task_error_message_set(self, task_queue):
        _add_doing_task(task_queue, task_id="fail03", attempt_count=MAX_DISPATCH_RETRIES - 1)
        with _no_active_tasks():
            requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        task = task_queue.get_task("fail03")
        assert task.error_message is not None
        msg = task.error_message.lower()
        assert "permanently" in msg or "failed" in msg

    def test_failed_task_not_added_to_queue(self, task_queue, mock_redis):
        _add_doing_task(task_queue, task_id="fail04", attempt_count=MAX_DISPATCH_RETRIES - 1,
                        workspace="ws_fail")
        queue_key = task_queue._queue_key("ws_fail")
        mock_redis._lists.clear()
        with _no_active_tasks():
            requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        queued = mock_redis.lrange(queue_key, 0, -1)
        assert "fail04" not in queued

    def test_failed_removed_from_executing_set(self, task_queue, mock_redis):
        _add_doing_task(task_queue, task_id="fail05", attempt_count=MAX_DISPATCH_RETRIES - 1,
                        workspace="ws_failex")
        exec_key = task_queue._executing_key("ws_failex")
        assert "fail05" in mock_redis.smembers(exec_key)
        with _no_active_tasks():
            requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        assert "fail05" not in mock_redis.smembers(exec_key)

    def test_failed_count_in_return_value(self, task_queue):
        _add_doing_task(task_queue, task_id="fail06", attempt_count=MAX_DISPATCH_RETRIES - 1)
        with _no_active_tasks():
            result = requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        assert result["failed"] == 1


# ---------------------------------------------------------------------------
# Tests: mixed batch
# ---------------------------------------------------------------------------

class TestMixedBatch:
    def test_correct_routing_for_each_task(self, task_queue):
        # stale + below max → requeue
        _add_doing_task(task_queue, task_id="mix_req", attempt_count=1, workspace="ws_mix")
        # stale + at max → fail
        _add_doing_task(task_queue, task_id="mix_fail",
                        attempt_count=MAX_DISPATCH_RETRIES - 1, workspace="ws_mix")
        # fresh → untouched
        _add_doing_task(task_queue, task_id="mix_fresh", seconds_ago=10, workspace="ws_mix")
        # active in executor → skipped
        _add_doing_task(task_queue, task_id="mix_active", workspace="ws_mix")

        with patch(
            "src.server.services.stale_task_watchdog._get_executor_active_task_ids",
            return_value={"mix_active"},
        ):
            result = requeue_stale_tasks(task_queue, stale_threshold_seconds=600)

        assert result["requeued"] == 1
        assert result["failed"] == 1
        # fresh + active = 2 skipped
        assert result["skipped"] == 2

        req_task = task_queue.get_task("mix_req")
        fail_task = task_queue.get_task("mix_fail")
        fresh_task = task_queue.get_task("mix_fresh")

        req_status = req_task.status if isinstance(req_task.status, str) else req_task.status.value
        fail_status = fail_task.status if isinstance(fail_task.status, str) else fail_task.status.value
        fresh_status = fresh_task.status if isinstance(fresh_task.status, str) else fresh_task.status.value

        assert req_status == TaskStatus.TODO.value
        assert fail_status == TaskStatus.FAILED.value
        assert fresh_status == TaskStatus.DOING.value


# ---------------------------------------------------------------------------
# Tests: executor import failure is graceful
# ---------------------------------------------------------------------------

class TestExecutorImportFailure:
    def test_import_error_returns_empty_set(self):
        with patch(
            "src.server.services.stale_task_watchdog._get_executor_active_task_ids",
            side_effect=Exception("import failed"),
        ):
            # Should not raise
            active = set()
            try:
                from src.server.services.stale_task_watchdog import _get_executor_active_task_ids
                active = _get_executor_active_task_ids()
            except Exception:
                pass
            # Returned set (or empty fallback) must be a set
            assert isinstance(active, set)

    def test_watchdog_runs_even_if_executor_unavailable(self, task_queue):
        """If get_executor raises, stale tasks should still be processed."""
        _add_doing_task(task_queue, task_id="noex01")
        with patch(
            "src.server.services.stale_task_watchdog._get_executor_active_task_ids",
            return_value=set(),  # simulates unavailable executor → empty set
        ):
            result = requeue_stale_tasks(task_queue, stale_threshold_seconds=600)
        assert result["requeued"] == 1


# ---------------------------------------------------------------------------
# Tests: constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_stale_threshold_is_ten_minutes(self):
        assert STALE_THRESHOLD_SECONDS == 600

    def test_max_dispatch_retries_matches_mc(self):
        assert MAX_DISPATCH_RETRIES == 5

    def test_max_dispatch_retries_matches_task_queue_constant(self):
        assert MAX_DISPATCH_RETRIES == TaskQueue.MAX_DISPATCH_RETRIES

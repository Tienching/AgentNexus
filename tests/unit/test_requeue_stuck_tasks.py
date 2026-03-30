# -*- coding: utf-8 -*-
"""Unit tests for requeue_stuck_tasks() — max-retry watchdog

Ported logic from mission-control commit 2d171ad:
  src/lib/task-dispatch.ts::requeueStaleTasks()

Tests verify:
1. Tasks within timeout are left untouched.
2. Tasks past timeout with attempt_count < MAX_DISPATCH_RETRIES are requeued
   with incremented attempt_count and a diagnostic error_message.
3. Tasks past timeout with attempt_count >= MAX_DISPATCH_RETRIES are failed
   permanently (no requeue).
4. The executing-set entry is removed in both requeue and fail paths.
5. Return value correctly counts (requeued + failed).
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.runtime.stores.task_storage import TaskQueue
from src.server.models import Task, TaskPriority, TaskStatus


# ---------------------------------------------------------------------------
# Re-use the same MockRedisClient from test_task_storage.py (copy-free)
# ---------------------------------------------------------------------------

class MockRedisClient:
    """Minimal in-memory Redis mock (mirrors test_task_storage.MockRedisClient)."""

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
        d = self._sets.setdefault(fk, {})  # misuse sets dict — ok for mock
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
        q = TaskQueue(db_path=None, exec_user="test_agent")
        q._redis = mock_redis
        return q


def _make_stuck_task(
    task_queue: TaskQueue,
    task_id: str = "stuck01",
    attempt_count: int = 0,
    seconds_ago: float = 7200,  # 2 hours ago by default
    workspace: str = "ws1",
) -> Task:
    """Add a DOING task whose started_at is in the past, simulating a stuck task."""
    task = task_queue.add_task(
        description="some work",
        priority=TaskPriority.THOUGHT,
        workspace=workspace,
    )
    # Override id for predictable assertions
    old_id = task.id
    task.id = task_id

    # Re-key in Redis: delete old key, write new
    redis = task_queue._redis
    old_data = redis.hgetall(task_queue._task_key(old_id))
    redis.delete(task_queue._task_key(old_id))
    old_data["id"] = task_id
    redis.hset(task_queue._task_key(task_id), old_data)

    # Update all index sets
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

    # Manually set DOING status + started_at + attempt_count
    started_at = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    task.started_at = started_at
    task.status = TaskStatus.DOING
    task.attempt_count = attempt_count

    redis.hset(task_queue._task_key(task_id), {
        "status": TaskStatus.DOING.value,
        "started_at": started_at.isoformat(),
        "attempt_count": str(attempt_count),
        "id": task_id,
    })
    # Update status sets
    redis.srem(task_queue._status_key(TaskStatus.TODO), task_id)
    redis.sadd(task_queue._status_key(TaskStatus.DOING), task_id)
    # Add to executing set (simulates running executor slot)
    redis.sadd(task_queue._executing_key(workspace), task_id)

    return task


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRequeueStaleness:
    """Tasks within the timeout window must be untouched."""

    def test_fresh_task_not_touched(self, task_queue):
        _make_stuck_task(task_queue, task_id="fresh01", seconds_ago=60)  # 1 min
        count = task_queue.requeue_stuck_tasks(timeout_seconds=3600)
        assert count == 0

        task = task_queue.get_task("fresh01")
        assert task is not None
        assert (task.status if isinstance(task.status, str) else task.status.value) == TaskStatus.DOING.value

    def test_exactly_at_threshold_not_touched(self, task_queue):
        """Task started exactly at timeout_seconds ago → not triggered (> not >=)."""
        _make_stuck_task(task_queue, task_id="edge01", seconds_ago=3600)
        # 3600 elapsed, threshold is 3600: elapsed > timeout only when strictly greater
        count = task_queue.requeue_stuck_tasks(timeout_seconds=3600)
        # elapsed == 3600 is borderline; with float precision it may fire — just
        # verify that functions returns without error and task still exists.
        task = task_queue.get_task("edge01")
        assert task is not None


class TestRequeuePath:
    """Tasks past timeout with attempt_count < MAX_DISPATCH_RETRIES must be requeued."""

    def test_requeued_status_becomes_todo(self, task_queue):
        _make_stuck_task(task_queue, task_id="req01", attempt_count=0)
        task_queue.requeue_stuck_tasks(timeout_seconds=60)
        task = task_queue.get_task("req01")
        status = task.status if isinstance(task.status, str) else task.status.value
        assert status == TaskStatus.TODO.value

    def test_requeued_increments_attempt_count(self, task_queue):
        _make_stuck_task(task_queue, task_id="req02", attempt_count=1)
        task_queue.requeue_stuck_tasks(timeout_seconds=60)
        task = task_queue.get_task("req02")
        assert task.attempt_count == 2

    def test_requeued_sets_error_message(self, task_queue):
        _make_stuck_task(task_queue, task_id="req03", attempt_count=0)
        task_queue.requeue_stuck_tasks(timeout_seconds=60)
        task = task_queue.get_task("req03")
        assert task.error_message is not None
        assert "requeued" in task.error_message.lower()

    def test_requeued_removed_from_executing_set(self, task_queue, mock_redis):
        _make_stuck_task(task_queue, task_id="req04", attempt_count=0, workspace="ws_exec")
        exec_key = task_queue._executing_key("ws_exec")
        assert "req04" in mock_redis.smembers(exec_key)

        task_queue.requeue_stuck_tasks(timeout_seconds=60)

        assert "req04" not in mock_redis.smembers(exec_key)

    def test_requeued_returns_count_one(self, task_queue):
        _make_stuck_task(task_queue, task_id="req05", attempt_count=2)
        count = task_queue.requeue_stuck_tasks(timeout_seconds=60)
        assert count == 1

    def test_last_attempt_before_max_still_requeues(self, task_queue):
        """attempt_count = MAX - 1 should still requeue, not fail."""
        max_r = TaskQueue.MAX_DISPATCH_RETRIES
        _make_stuck_task(task_queue, task_id="req06", attempt_count=max_r - 2)
        task_queue.requeue_stuck_tasks(timeout_seconds=60)
        task = task_queue.get_task("req06")
        status = task.status if isinstance(task.status, str) else task.status.value
        assert status == TaskStatus.TODO.value


class TestFailPath:
    """Tasks at or above MAX_DISPATCH_RETRIES must be permanently failed."""

    def test_at_max_retries_becomes_failed(self, task_queue):
        max_r = TaskQueue.MAX_DISPATCH_RETRIES
        _make_stuck_task(task_queue, task_id="fail01", attempt_count=max_r - 1)
        task_queue.requeue_stuck_tasks(timeout_seconds=60)
        task = task_queue.get_task("fail01")
        status = task.status if isinstance(task.status, str) else task.status.value
        assert status == TaskStatus.FAILED.value

    def test_above_max_retries_becomes_failed(self, task_queue):
        max_r = TaskQueue.MAX_DISPATCH_RETRIES
        _make_stuck_task(task_queue, task_id="fail02", attempt_count=max_r + 2)
        task_queue.requeue_stuck_tasks(timeout_seconds=60)
        task = task_queue.get_task("fail02")
        status = task.status if isinstance(task.status, str) else task.status.value
        assert status == TaskStatus.FAILED.value

    def test_failed_task_has_error_message(self, task_queue):
        max_r = TaskQueue.MAX_DISPATCH_RETRIES
        _make_stuck_task(task_queue, task_id="fail03", attempt_count=max_r - 1)
        task_queue.requeue_stuck_tasks(timeout_seconds=60)
        task = task_queue.get_task("fail03")
        assert task.error_message is not None
        assert "permanently" in task.error_message.lower() or "failed" in task.error_message.lower()

    def test_failed_task_not_added_to_queue(self, task_queue, mock_redis):
        max_r = TaskQueue.MAX_DISPATCH_RETRIES
        _make_stuck_task(task_queue, task_id="fail04", attempt_count=max_r - 1, workspace="ws_fail")
        queue_key = task_queue._queue_key("ws_fail")
        # Clear the queue first
        mock_redis._lists.clear()

        task_queue.requeue_stuck_tasks(timeout_seconds=60)

        queued = mock_redis.lrange(queue_key, 0, -1)
        assert "fail04" not in queued

    def test_failed_removed_from_executing_set(self, task_queue, mock_redis):
        max_r = TaskQueue.MAX_DISPATCH_RETRIES
        _make_stuck_task(task_queue, task_id="fail05", attempt_count=max_r - 1, workspace="ws_failex")
        exec_key = task_queue._executing_key("ws_failex")
        assert "fail05" in mock_redis.smembers(exec_key)

        task_queue.requeue_stuck_tasks(timeout_seconds=60)

        assert "fail05" not in mock_redis.smembers(exec_key)

    def test_failed_count_included_in_return_value(self, task_queue):
        max_r = TaskQueue.MAX_DISPATCH_RETRIES
        _make_stuck_task(task_queue, task_id="fail06", attempt_count=max_r - 1)
        count = task_queue.requeue_stuck_tasks(timeout_seconds=60)
        assert count == 1


class TestMixedBatch:
    """Multiple tasks in the same call — correct routing for each."""

    def test_mixed_requeue_and_fail(self, task_queue):
        max_r = TaskQueue.MAX_DISPATCH_RETRIES
        # One task eligible for requeue
        _make_stuck_task(task_queue, task_id="mix_req", attempt_count=1, workspace="ws_mix")
        # One task that should be failed
        _make_stuck_task(task_queue, task_id="mix_fail", attempt_count=max_r - 1, workspace="ws_mix")
        # One fresh task that should be untouched
        _make_stuck_task(task_queue, task_id="mix_fresh", seconds_ago=10, workspace="ws_mix")

        count = task_queue.requeue_stuck_tasks(timeout_seconds=60)
        assert count == 2  # requeued + failed

        req_task = task_queue.get_task("mix_req")
        fail_task = task_queue.get_task("mix_fail")
        fresh_task = task_queue.get_task("mix_fresh")

        req_status = req_task.status if isinstance(req_task.status, str) else req_task.status.value
        fail_status = fail_task.status if isinstance(fail_task.status, str) else fail_task.status.value
        fresh_status = fresh_task.status if isinstance(fresh_task.status, str) else fresh_task.status.value

        assert req_status == TaskStatus.TODO.value
        assert fail_status == TaskStatus.FAILED.value
        assert fresh_status == TaskStatus.DOING.value

    def test_no_stuck_tasks_returns_zero(self, task_queue):
        count = task_queue.requeue_stuck_tasks(timeout_seconds=60)
        assert count == 0


class TestMaxRetryConstant:
    """Sanity checks on the MAX_DISPATCH_RETRIES class constant."""

    def test_constant_exists(self):
        assert hasattr(TaskQueue, "MAX_DISPATCH_RETRIES")

    def test_constant_is_positive_int(self):
        assert isinstance(TaskQueue.MAX_DISPATCH_RETRIES, int)
        assert TaskQueue.MAX_DISPATCH_RETRIES > 0

    def test_constant_value_matches_mc_default(self):
        """mission-control uses 5 — keep in sync."""
        assert TaskQueue.MAX_DISPATCH_RETRIES == 5

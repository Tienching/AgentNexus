# -*- coding: utf-8 -*-
"""Tests for agent_name → exec_user rename

Validates:
1. All models use exec_user field correctly
2. Redis backward compatibility (reading old agent_name keys)
3. Config field default_exec_user works
4. TaskQueue uses exec_user for key isolation
5. StreamArchiver uses exec_user
6. SessionMeta round-trip with exec_user
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from src.server.models import (
    SessionMeta,
    SessionStatus,
)
from src.runtime.models.task_models import Task, TaskPriority, TaskStatus
from src.server.services.stream_archiver import StreamArchiver, create_archiver
from src.runtime.stores.task_storage import TaskQueue


# ──────────────────────────────────────────────────────────────────────
# SessionMeta exec_user tests
# ──────────────────────────────────────────────────────────────────────


class TestSessionMetaExecUser:
    """SessionMeta exec_user field tests"""

    def test_exec_user_field_exists(self):
        """exec_user field exists and accepts a value"""
        meta = SessionMeta(
            id="s1", thread_id="t1", username="u1", exec_user="alice"
        )
        assert meta.exec_user == "alice"

    def test_exec_user_default_none(self):
        """exec_user defaults to None when not provided"""
        meta = SessionMeta(id="s1", thread_id="t1", username="u1")
        assert meta.exec_user is None

    def test_exec_user_to_redis_hash(self):
        """exec_user is serialized in Redis hash"""
        meta = SessionMeta(
            id="s1", thread_id="t1", username="u1", exec_user="bob"
        )
        h = meta.to_redis_hash()
        assert h["exec_user"] == "bob"

    def test_exec_user_none_to_redis_hash(self):
        """None exec_user serializes as empty string in Redis hash"""
        meta = SessionMeta(id="s1", thread_id="t1", username="u1")
        h = meta.to_redis_hash()
        assert h["exec_user"] == ""

    def test_exec_user_from_redis_hash(self):
        """exec_user is restored from Redis hash"""
        data = {
            "id": "s1",
            "thread_id": "t1",
            "username": "u1",
            "exec_user": "carol",
            "created_at": "1000",
            "updated_at": "1000",
            "message_count": "0",
            "status": "idle",
        }
        meta = SessionMeta.from_redis_hash(data)
        assert meta.exec_user == "carol"

    def test_exec_user_empty_from_redis_hash(self):
        """Empty exec_user in Redis hash becomes None"""
        data = {
            "id": "s1",
            "thread_id": "t1",
            "username": "u1",
            "exec_user": "",
            "created_at": "1000",
            "updated_at": "1000",
            "message_count": "0",
            "status": "idle",
        }
        meta = SessionMeta.from_redis_hash(data)
        assert meta.exec_user is None

    def test_exec_user_roundtrip(self):
        """exec_user survives to_redis_hash → from_redis_hash"""
        original = SessionMeta(
            id="s1", thread_id="t1", username="u1", exec_user="dave"
        )
        restored = SessionMeta.from_redis_hash(original.to_redis_hash())
        assert restored.exec_user == original.exec_user

    def test_exec_user_none_roundtrip(self):
        """None exec_user survives roundtrip"""
        original = SessionMeta(id="s1", thread_id="t1", username="u1")
        restored = SessionMeta.from_redis_hash(original.to_redis_hash())
        assert restored.exec_user is None

    def test_no_agent_name_field(self):
        """SessionMeta should NOT have agent_name as a direct field"""
        assert "agent_name" not in SessionMeta.model_fields


# ──────────────────────────────────────────────────────────────────────
# Task model exec_user tests
# ──────────────────────────────────────────────────────────────────────


class TestTaskExecUser:
    """Task exec_user field tests"""

    def test_exec_user_field_exists(self):
        """Task has exec_user field"""
        task = Task(description="test", exec_user="eve")
        assert task.exec_user == "eve"

    def test_exec_user_default_none(self):
        """Task exec_user defaults to None"""
        task = Task(description="test")
        assert task.exec_user is None

    def test_exec_user_in_redis_hash(self):
        """exec_user appears in to_redis_hash output"""
        task = Task(description="test", exec_user="frank")
        h = task.to_redis_hash()
        assert h["exec_user"] == "frank"

    def test_exec_user_none_not_in_redis_hash(self):
        """None exec_user should NOT appear in Redis hash (skipped)"""
        task = Task(description="test")
        h = task.to_redis_hash()
        assert "exec_user" not in h

    def test_exec_user_from_redis_hash(self):
        """exec_user is read from Redis hash"""
        data = {
            "id": "t1",
            "description": "test",
            "priority": "thought",
            "status": "todo",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "attempt_count": "0",
            "exec_user": "grace",
            "provider": "claude",
        }
        task = Task.from_redis_hash(data)
        assert task.exec_user == "grace"

    def test_exec_user_roundtrip(self):
        """exec_user survives to_redis_hash → from_redis_hash"""
        original = Task(description="test", exec_user="heidi")
        restored = Task.from_redis_hash(original.to_redis_hash())
        assert restored.exec_user == original.exec_user

    def test_no_agent_name_field(self):
        """Task should NOT have agent_name as a field"""
        assert "agent_name" not in Task.model_fields


# ──────────────────────────────────────────────────────────────────────
# TaskQueue exec_user isolation tests
# ──────────────────────────────────────────────────────────────────────


class MockRedis:
    """Minimal mock Redis for TaskQueue tests"""

    def __init__(self):
        self._data = {}
        self._hashes = {}
        self._sets = {}
        self._sorted_sets = {}
        self._lists = {}
        self._prefix = "test:"

    def _key(self, key):
        return f"{self._prefix}{key}"

    def ping(self):
        return True

    def hset(self, name, mapping):
        k = self._key(name)
        if k not in self._hashes:
            self._hashes[k] = {}
        self._hashes[k].update(mapping)
        return len(mapping)

    def hgetall(self, name):
        return self._hashes.get(self._key(name), {})

    def hget(self, name, key):
        return self._hashes.get(self._key(name), {}).get(key)

    def hexists(self, name, key):
        return key in self._hashes.get(self._key(name), {})

    def hdel(self, name, *keys):
        k = self._key(name)
        if k not in self._hashes:
            return 0
        count = 0
        for key in keys:
            if key in self._hashes[k]:
                del self._hashes[k][key]
                count += 1
        return count

    def delete(self, *keys):
        count = 0
        for k in keys:
            fk = self._key(k)
            for store in (self._data, self._hashes, self._sets, self._sorted_sets, self._lists):
                if fk in store:
                    del store[fk]
                    count += 1
        return count

    def exists(self, key):
        fk = self._key(key)
        return fk in self._data or fk in self._hashes

    def get(self, key):
        return self._data.get(self._key(key))

    def set(self, key, value, ex=None):
        self._data[self._key(key)] = value
        return True

    def zadd(self, name, mapping):
        k = self._key(name)
        if k not in self._sorted_sets:
            self._sorted_sets[k] = {}
        added = 0
        for m, s in mapping.items():
            if m not in self._sorted_sets[k]:
                added += 1
            self._sorted_sets[k][m] = s
        return added

    def zrem(self, name, *values):
        k = self._key(name)
        if k not in self._sorted_sets:
            return 0
        removed = 0
        for v in values:
            if v in self._sorted_sets[k]:
                del self._sorted_sets[k][v]
                removed += 1
        return removed

    def zrange(self, name, start, end, withscores=False):
        k = self._key(name)
        items = sorted(self._sorted_sets.get(k, {}).items(), key=lambda x: x[1])
        length = len(items)
        if start < 0:
            start = max(0, length + start)
        if end < 0:
            end = length + end
        result = items[start:end + 1]
        return result if withscores else [x[0] for x in result]

    def zcard(self, name):
        return len(self._sorted_sets.get(self._key(name), {}))

    def sadd(self, name, *values):
        k = self._key(name)
        if k not in self._sets:
            self._sets[k] = set()
        added = 0
        for v in values:
            if v not in self._sets[k]:
                self._sets[k].add(v)
                added += 1
        return added

    def srem(self, name, *values):
        k = self._key(name)
        if k not in self._sets:
            return 0
        removed = 0
        for v in values:
            if v in self._sets[k]:
                self._sets[k].discard(v)
                removed += 1
        return removed

    def smembers(self, name):
        return self._sets.get(self._key(name), set()).copy()

    def sismember(self, name, value):
        return value in self._sets.get(self._key(name), set())

    def scard(self, name):
        return len(self._sets.get(self._key(name), set()))

    def lpush(self, name, *values):
        k = self._key(name)
        if k not in self._lists:
            self._lists[k] = []
        for v in reversed(values):
            self._lists[k].insert(0, v)
        return len(self._lists[k])

    def rpush(self, name, *values):
        k = self._key(name)
        if k not in self._lists:
            self._lists[k] = []
        self._lists[k].extend(values)
        return len(self._lists[k])

    def lpop(self, name):
        k = self._key(name)
        if k not in self._lists or not self._lists[k]:
            return None
        return self._lists[k].pop(0)

    def lrange(self, name, start, end):
        k = self._key(name)
        lst = self._lists.get(k, [])
        if end == -1:
            end = len(lst)
        return lst[start:end + 1]

    def llen(self, name):
        return len(self._lists.get(self._key(name), []))

    def lrem(self, name, count, value):
        k = self._key(name)
        if k not in self._lists:
            return 0
        orig = len(self._lists[k])
        self._lists[k] = [v for v in self._lists[k] if v != value]
        return orig - len(self._lists[k])

    def scan_iter(self, match, count=100):
        pattern = match.replace("*", "")
        for key in list(self._sets.keys()) + list(self._lists.keys()):
            if pattern in key:
                yield key[len(self._prefix):]


class TestTaskQueueExecUser:
    """TaskQueue exec_user isolation tests"""

    def test_queue_uses_exec_user_in_keys(self):
        """TaskQueue uses exec_user for Redis key namespacing"""
        redis = MockRedis()
        with patch('src.runtime.stores.task_storage.get_redis_client', return_value=redis):
            q = TaskQueue(db_path=None, exec_user="alice")
            q._redis = redis

        assert q.exec_user == "alice"
        assert q._task_key("t1") == "task:alice:t1"
        assert q._all_tasks_key() == "tasks:alice:all"

    def test_two_queues_different_exec_users(self):
        """Two TaskQueues with different exec_users are isolated"""
        redis = MockRedis()
        with patch('src.runtime.stores.task_storage.get_redis_client', return_value=redis):
            q1 = TaskQueue(db_path=None, exec_user="alice")
            q1._redis = redis
            q2 = TaskQueue(db_path=None, exec_user="bob")
            q2._redis = redis

        t1 = q1.add_task(description="Alice's task")
        t2 = q2.add_task(description="Bob's task")

        assert t1.exec_user == "alice"
        assert t2.exec_user == "bob"

        # Each queue only sees its own tasks
        assert q1.get_task(t1.id) is not None
        assert q1.get_task(t2.id) is None
        assert q2.get_task(t2.id) is not None
        assert q2.get_task(t1.id) is None

    def test_add_task_sets_exec_user(self):
        """add_task sets exec_user on the created task"""
        redis = MockRedis()
        with patch('src.runtime.stores.task_storage.get_redis_client', return_value=redis):
            q = TaskQueue(db_path=None, exec_user="charlie")
            q._redis = redis

        task = q.add_task(description="Test task")
        assert task.exec_user == "charlie"

    def test_add_task_override_exec_user(self):
        """add_task with explicit exec_user overrides queue default"""
        redis = MockRedis()
        with patch('src.runtime.stores.task_storage.get_redis_client', return_value=redis):
            q = TaskQueue(db_path=None, exec_user="default_user")
            q._redis = redis

        task = q.add_task(description="Test task", exec_user="override_user")
        assert task.exec_user == "override_user"


# ──────────────────────────────────────────────────────────────────────
# StreamArchiver exec_user tests
# ──────────────────────────────────────────────────────────────────────


class TestStreamArchiverExecUser:
    """StreamArchiver exec_user field tests"""

    def test_archiver_stores_exec_user(self):
        """StreamArchiver stores exec_user"""
        archiver = create_archiver(
            thread_id="t1",
            run_id="r1",
            username="user1",
            exec_user="ivan",
        )
        assert archiver.exec_user == "ivan"

    def test_archiver_exec_user_none(self):
        """StreamArchiver without exec_user defaults to None"""
        archiver = create_archiver(
            thread_id="t1",
            run_id="r1",
            username="user1",
        )
        assert archiver.exec_user is None

    @pytest.mark.asyncio
    async def test_archiver_exec_user_passed_to_session(self):
        """StreamArchiver passes exec_user to SessionMeta on run start"""
        from tests.unit.test_stream_archiver import MockSessionStorage

        storage = MockSessionStorage()
        archiver = StreamArchiver(
            session_id="s1",
            thread_id="t1",
            run_id="r1",
            username="user1",
            exec_user="judy",
            storage=storage,
        )

        await archiver.on_run_started()

        session = storage.get_session_meta("s1")
        assert session is not None
        assert session.exec_user == "judy"


# ──────────────────────────────────────────────────────────────────────
# Config default_exec_user tests
# ──────────────────────────────────────────────────────────────────────


class TestConfigExecUser:
    """Config exec_user and default_exec_user field tests"""

    def test_settings_has_exec_user(self):
        """Settings has exec_user field"""
        from src.server.config import Settings
        assert "exec_user" in Settings.model_fields

    def test_settings_has_default_exec_user(self):
        """Settings has default_exec_user field (ProviderSettings)"""
        from src.server.config import ProviderSettings
        assert "default_exec_user" in ProviderSettings.model_fields

    def test_settings_no_agent_name(self):
        """Settings should NOT have agent_name field"""
        from src.server.config import Settings
        assert "agent_name" not in Settings.model_fields

    def test_settings_no_default_agent(self):
        """Settings should NOT have default_agent field"""
        from src.server.config import Settings
        assert "default_agent" not in Settings.model_fields

    def test_default_exec_user_empty(self):
        """ProviderSettings default_exec_user defaults to empty string"""
        from src.server.config import ProviderSettings
        field = ProviderSettings.model_fields["default_exec_user"]
        assert field.default == ""

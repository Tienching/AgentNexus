# -*- coding: utf-8 -*-
"""Task Storage Unit Tests with Redis"""

import pytest
from unittest.mock import patch

from src.runtime.stores.task_storage import (
    DuplicatePendingTaskError,
    InvalidTaskTransitionError,
    TaskQueue,
)
from src.server.models import Task, TaskPriority, TaskStatus


class MockRedisClient:
    """Mock Redis client for testing"""
    
    def __init__(self):
        self._data = {}  # key -> value
        self._hashes = {}  # key -> {field: value}
        self._sets = {}  # key -> set
        self._sorted_sets = {}  # key -> {member: score}
        self._lists = {}  # key -> list
        self._prefix = "test:"
    
    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"
    
    def ping(self) -> bool:
        return True
    
    def get(self, key: str):
        return self._data.get(self._key(key))
    
    def set(self, key: str, value: str, ex=None):
        self._data[self._key(key)] = value
        return True
    
    def delete(self, *keys):
        count = 0
        for k in keys:
            full_key = self._key(k)
            if full_key in self._data:
                del self._data[full_key]
                count += 1
            if full_key in self._hashes:
                del self._hashes[full_key]
                count += 1
        return count
    
    def exists(self, key: str) -> bool:
        return self._key(key) in self._data or self._key(key) in self._hashes
    
    # Hash operations
    def hset(self, name: str, mapping: dict):
        full_key = self._key(name)
        if full_key not in self._hashes:
            self._hashes[full_key] = {}
        self._hashes[full_key].update(mapping)
        return len(mapping)
    
    def hget(self, name: str, key: str):
        full_key = self._key(name)
        return self._hashes.get(full_key, {}).get(key)
    
    def hgetall(self, name: str):
        full_key = self._key(name)
        return self._hashes.get(full_key, {})
    
    def hdel(self, name: str, *keys):
        full_key = self._key(name)
        if full_key not in self._hashes:
            return 0
        count = 0
        for k in keys:
            if k in self._hashes[full_key]:
                del self._hashes[full_key][k]
                count += 1
        return count
    
    def hexists(self, name: str, key: str) -> bool:
        full_key = self._key(name)
        return key in self._hashes.get(full_key, {})
    
    # Set operations
    def sadd(self, name: str, *values):
        full_key = self._key(name)
        if full_key not in self._sets:
            self._sets[full_key] = set()
        added = 0
        for v in values:
            if v not in self._sets[full_key]:
                self._sets[full_key].add(v)
                added += 1
        return added
    
    def srem(self, name: str, *values):
        full_key = self._key(name)
        if full_key not in self._sets:
            return 0
        removed = 0
        for v in values:
            if v in self._sets[full_key]:
                self._sets[full_key].discard(v)
                removed += 1
        return removed
    
    def smembers(self, name: str):
        full_key = self._key(name)
        return self._sets.get(full_key, set()).copy()
    
    def sismember(self, name: str, value: str) -> bool:
        full_key = self._key(name)
        return value in self._sets.get(full_key, set())
    
    def scard(self, name: str) -> int:
        full_key = self._key(name)
        return len(self._sets.get(full_key, set()))
    
    # Sorted set operations
    def zadd(self, name: str, mapping: dict):
        full_key = self._key(name)
        if full_key not in self._sorted_sets:
            self._sorted_sets[full_key] = {}
        added = 0
        for member, score in mapping.items():
            if member not in self._sorted_sets[full_key]:
                added += 1
            self._sorted_sets[full_key][member] = score
        return added
    
    def zrem(self, name: str, *values):
        full_key = self._key(name)
        if full_key not in self._sorted_sets:
            return 0
        removed = 0
        for v in values:
            if v in self._sorted_sets[full_key]:
                del self._sorted_sets[full_key][v]
                removed += 1
        return removed
    
    def zrange(self, name: str, start: int, end: int, withscores: bool = False):
        full_key = self._key(name)
        items = self._sorted_sets.get(full_key, {})
        sorted_items = sorted(items.items(), key=lambda x: x[1])
        
        # Handle negative indices
        length = len(sorted_items)
        if start < 0:
            start = max(0, length + start)
        if end < 0:
            end = length + end
        
        result = sorted_items[start:end + 1]
        if withscores:
            return result
        return [item[0] for item in result]
    
    def zcard(self, name: str) -> int:
        full_key = self._key(name)
        return len(self._sorted_sets.get(full_key, {}))
    
    # List operations
    def lpush(self, name: str, *values):
        full_key = self._key(name)
        if full_key not in self._lists:
            self._lists[full_key] = []
        for v in reversed(values):
            self._lists[full_key].insert(0, v)
        return len(self._lists[full_key])
    
    def rpush(self, name: str, *values):
        full_key = self._key(name)
        if full_key not in self._lists:
            self._lists[full_key] = []
        self._lists[full_key].extend(values)
        return len(self._lists[full_key])
    
    def lpop(self, name: str):
        full_key = self._key(name)
        if full_key not in self._lists or not self._lists[full_key]:
            return None
        return self._lists[full_key].pop(0)
    
    def rpop(self, name: str):
        full_key = self._key(name)
        if full_key not in self._lists or not self._lists[full_key]:
            return None
        return self._lists[full_key].pop()
    
    def lrange(self, name: str, start: int, end: int):
        full_key = self._key(name)
        lst = self._lists.get(full_key, [])
        if end == -1:
            end = len(lst)
        return lst[start:end + 1]
    
    def llen(self, name: str) -> int:
        full_key = self._key(name)
        return len(self._lists.get(full_key, []))
    
    def lrem(self, name: str, count: int, value: str) -> int:
        full_key = self._key(name)
        if full_key not in self._lists:
            return 0
        original_len = len(self._lists[full_key])
        self._lists[full_key] = [v for v in self._lists[full_key] if v != value]
        return original_len - len(self._lists[full_key])
    
    # Scan operations
    def scan_iter(self, match: str, count: int = 100):
        pattern = match.replace("*", "")
        for key in list(self._sets.keys()) + list(self._lists.keys()):
            if pattern in key:
                yield key[len(self._prefix):]  # Remove prefix


@pytest.fixture
def mock_redis():
    """Create mock Redis client"""
    return MockRedisClient()


@pytest.fixture
def task_queue(mock_redis, tmp_path, monkeypatch):
    """Create TaskQueue instance with mock Redis"""
    from src.runtime.stores.db import Database

    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "task-storage.db"))
    Database.reset_instances()
    with patch('src.runtime.stores.task_storage.get_redis_client', return_value=mock_redis):
        queue = TaskQueue(db_path=None, exec_user="test_agent")
        queue._redis = mock_redis
        yield queue
    Database.reset_instances()


class TestTaskQueue:
    """TaskQueue tests with Redis backend"""

    def test_add_task(self, task_queue):
        """Test adding a task"""
        task = task_queue.add_task(
            description="Test task",
            priority=TaskPriority.THOUGHT,
        )
        
        assert task.id is not None
        assert task.description == "Test task"
        assert task.priority == TaskPriority.THOUGHT
        assert task.status == TaskStatus.TODO
        assert task.exec_user == "test_agent"
        assert task.provider == "claude"

    def test_add_task_with_provider(self, task_queue):
        task = task_queue.add_task(
            description="Codex task",
            provider="codex",
        )
        assert task.provider == "codex"

        stored = task_queue.get_task(task.id)
        assert stored is not None
        assert stored.provider == "codex"

    def test_add_task_with_project(self, task_queue):
        """Test adding a task with project"""
        task = task_queue.add_task(
            description="Project task",
            priority=TaskPriority.SERIOUS,
            project_id="my-project",
            project_name="My Project",
        )
        
        assert task.project_id == "my-project"
        assert task.project_name == "My Project"
        assert task.priority == TaskPriority.SERIOUS

    def test_get_task(self, task_queue):
        """Test getting a task by ID"""
        task = task_queue.add_task(description="Test task")
        
        retrieved = task_queue.get_task(task.id)
        assert retrieved is not None
        assert retrieved.id == task.id
        assert retrieved.description == "Test task"

    def test_get_task_not_found(self, task_queue):
        """Test getting non-existent task"""
        retrieved = task_queue.get_task("nonexistent")
        assert retrieved is None

    def test_get_pending_tasks(self, task_queue):
        """Test getting TODO tasks"""
        task_queue.add_task(description="Task 1", priority=TaskPriority.THOUGHT)
        task_queue.add_task(description="Task 2", priority=TaskPriority.SERIOUS)
        task_queue.add_task(description="Task 3", priority=TaskPriority.THOUGHT)
        
        pending = task_queue.get_pending_tasks()
        assert len(pending) == 3
        # SERIOUS should come first
        assert pending[0].priority == TaskPriority.SERIOUS

    def test_cancel_task(self, task_queue):
        """Test cancelling a task"""
        task = task_queue.add_task(description="To cancel")
        
        cancelled = task_queue.cancel_task(task.id)
        assert cancelled is not None
        assert cancelled.status == TaskStatus.CANCELLED
        assert cancelled.deleted_at is not None

    def test_cancel_task_not_todo(self, task_queue):
        """Test cancelling non-TODO task"""
        task = task_queue.add_task(description="Test")
        task_queue.cancel_task(task.id)  # First cancel
        
        # Try to cancel again
        result = task_queue.cancel_task(task.id)
        # Should not change status again
        assert result.status == TaskStatus.CANCELLED

    def test_get_queue_status(self, task_queue):
        """Test getting queue status"""
        task_queue.add_task(description="Task 1")
        task_queue.add_task(description="Task 2")
        task = task_queue.add_task(description="Task 3")
        task_queue.cancel_task(task.id)
        
        status = task_queue.get_queue_status()
        assert status["total"] == 3
        assert status["pending"] == 2
        assert status["completed"] == 0

    def test_get_projects(self, task_queue):
        """Test getting projects"""
        task_queue.add_task(
            description="Task 1",
            project_id="proj-a",
            project_name="Project A",
        )
        task_queue.add_task(
            description="Task 2",
            project_id="proj-a",
            project_name="Project A",
        )
        task_queue.add_task(
            description="Task 3",
            project_id="proj-b",
            project_name="Project B",
        )
        
        projects = task_queue.get_projects()
        assert len(projects) == 2
        
        proj_a = next(p for p in projects if p["project_id"] == "proj-a")
        assert proj_a["total_tasks"] == 2
        assert proj_a["project_name"] == "Project A"

    def test_get_project_by_id(self, task_queue):
        """Test getting project by ID"""
        task_queue.add_task(
            description="Task 1",
            project_id="my-proj",
            project_name="My Project",
        )
        
        project = task_queue.get_project_by_id("my-proj")
        assert project is not None
        assert project["project_id"] == "my-proj"
        assert project["total_tasks"] == 1

    def test_get_project_by_id_not_found(self, task_queue):
        """Test getting non-existent project"""
        project = task_queue.get_project_by_id("nonexistent")
        assert project is None

    def test_get_recent_tasks(self, task_queue):
        """Test getting recent tasks"""
        for i in range(5):
            task_queue.add_task(description=f"Task {i}")
        
        recent = task_queue.get_recent_tasks(limit=3)
        assert len(recent) == 3

    def test_list_tasks_basic_pagination(self, task_queue):
        """Test list_tasks pagination"""
        for i in range(5):
            task_queue.add_task(description=f"Task {i}")

        page1, total1 = task_queue.list_tasks(page=1, page_size=2)
        page2, total2 = task_queue.list_tasks(page=2, page_size=2)

        assert total1 == 5
        assert total2 == 5
        assert len(page1) == 2
        assert len(page2) == 2
        # Most recent first
        assert page1[0].created_at >= page1[1].created_at

    def test_list_tasks_filters(self, task_queue):
        """Test list_tasks filtering by status/project/workspace/search"""
        t1 = task_queue.add_task(description="Fix login", project_id="proj-a", project_name="Project A", workspace="/ws/a")
        task_queue.add_task(description="Refactor API", project_id="proj-b", project_name="Project B", workspace="/ws/b")
        t3 = task_queue.add_task(description="Fix checkout", project_id="proj-a", project_name="Project A", workspace="/ws/a")

        # Make one task done
        task_queue.start_task(t1.id)
        task_queue.complete_task(t1.id)

        done_tasks, total_done = task_queue.list_tasks(status="done")
        assert total_done == 1
        assert done_tasks[0].id == t1.id

        proj_a_tasks, total_proj_a = task_queue.list_tasks(project_id="proj-a")
        assert total_proj_a == 2
        assert set([t.id for t in proj_a_tasks]) == {t1.id, t3.id}

        ws_a_tasks, total_ws_a = task_queue.list_tasks(workspace="/ws/a")
        assert total_ws_a == 2

        search_tasks, total_search = task_queue.list_tasks(search="checkout")
        assert total_search == 1
        assert search_tasks[0].id == t3.id

    def test_delete_project(self, task_queue):
        """Test soft deleting a project"""
        task_queue.add_task(
            description="Task 1",
            project_id="to-delete",
            project_name="To Delete",
        )
        task_queue.add_task(
            description="Task 2",
            project_id="to-delete",
            project_name="To Delete",
        )
        
        count = task_queue.delete_project("to-delete")
        assert count == 2
        
        # Verify tasks are cancelled
        project = task_queue.get_project_by_id("to-delete")
        assert project["pending"] == 0

    def test_archive_unarchive_clear_tasks(self, task_queue):
        """Test archive/unarchive/clear batch operations"""
        t = task_queue.add_task(description="To archive")
        task_queue.start_task(t.id)
        task_queue.complete_task(t.id)

        # Archive (DONE -> ARCHIVED)
        before_completed_at = task_queue.get_task(t.id).completed_at
        result = task_queue.archive_tasks([t.id])
        assert result["count"] == 1
        archived = task_queue.get_task(t.id)
        assert archived.status == TaskStatus.ARCHIVED
        assert archived.archived_at is not None
        assert archived.completed_at == before_completed_at

        # Unarchive (ARCHIVED -> DONE) and preserve completed_at
        result2 = task_queue.unarchive_tasks([t.id])
        assert result2["count"] == 1
        unarchived = task_queue.get_task(t.id)
        assert unarchived.status == TaskStatus.COMPLETED
        assert unarchived.completed_at == before_completed_at

        # archived_at should be cleared (hash field removed)
        raw = task_queue._redis.hgetall(task_queue._task_key(t.id))
        assert "archived_at" not in raw

        # Archive again then clear
        task_queue.archive_tasks([t.id])
        result3 = task_queue.clear_tasks([t.id])
        assert result3["count"] == 1
        assert task_queue.get_task(t.id) is None

    def test_archive_skips_non_done(self, task_queue):
        t = task_queue.add_task(description="Not done")
        res = task_queue.archive_tasks([t.id])
        assert res["count"] == 0
        assert t.id in res["skipped"]
        assert task_queue.get_task(t.id).status == TaskStatus.TODO

    def test_start_task(self, task_queue):
        """Test starting a task"""
        task = task_queue.add_task(description="To start")
        
        started = task_queue.start_task(task.id)
        assert started is not None
        assert started.status == TaskStatus.DOING
        assert started.started_at is not None
        assert started.attempt_count == 1

    def test_complete_task_success(self, task_queue):
        """Test completing a task successfully"""
        task = task_queue.add_task(description="To complete")
        task_queue.start_task(task.id)
        
        completed = task_queue.complete_task(task.id)
        assert completed is not None
        assert completed.status == TaskStatus.DONE
        assert completed.completed_at is not None

    def test_complete_task_failure(self, task_queue):
        """Test completing a task with error"""
        task = task_queue.add_task(description="To fail")
        task_queue.start_task(task.id)
        
        failed = task_queue.complete_task(task.id, error_message="Something went wrong")
        assert failed is not None
        assert failed.status == TaskStatus.FAILED
        assert failed.error_message == "Something went wrong"

    def test_requeue_task_moves_doing_task_back_to_todo(self, task_queue):
        task = task_queue.add_task(description="To requeue", workspace="/path/requeue")
        task_queue.start_task(task.id)

        requeued = task_queue.requeue_task(
            task.id,
            attempt_count=2,
            error_message="Retry requested",
        )

        assert requeued is not None
        assert requeued.status == TaskStatus.TODO
        assert requeued.attempt_count == 2
        assert requeued.error_message == "Retry requested"
        assert task.id in task_queue._redis.lrange(task_queue._queue_key("/path/requeue"), 0, -1)
        assert task.id not in task_queue._redis.smembers(task_queue._executing_key("/path/requeue"))

    def test_requeue_clears_started_and_terminal_timestamps(self, task_queue):
        failed = task_queue.add_task(description="Failed task")
        task_queue.start_task(failed.id)
        task_queue.complete_task(failed.id, error_message="failed")

        cancelled = task_queue.add_task(description="Cancelled task")
        task_queue.cancel_task(cancelled.id)

        archived = task_queue.add_task(description="Archived task")
        task_queue.start_task(archived.id)
        task_queue.complete_task(archived.id)
        task_queue.update_task_status(archived.id, TaskStatus.ARCHIVED)

        for task_id in (failed.id, cancelled.id, archived.id):
            pending = task_queue.update_task_status(task_id, TaskStatus.PENDING)
            assert pending is not None
            assert pending.status == TaskStatus.PENDING
            assert pending.started_at is None
            assert pending.completed_at is None
            assert pending.deleted_at is None
            assert pending.archived_at is None

    def test_fail_task_marks_doing_task_failed(self, task_queue):
        task = task_queue.add_task(description="To fail publicly", workspace="/path/fail")
        task_queue.start_task(task.id)

        failed = task_queue.fail_task(
            task.id,
            error_message="Executor disappeared",
            attempt_count=3,
        )

        assert failed is not None
        assert failed.status == TaskStatus.FAILED
        assert failed.attempt_count == 3
        assert failed.error_message == "Executor disappeared"
        assert task.id not in task_queue._redis.smembers(task_queue._executing_key("/path/fail"))

    def test_get_executing_count(self, task_queue):
        """Test getting executing task count"""
        task1 = task_queue.add_task(description="Task 1", workspace="/path/a")
        task_queue.add_task(description="Task 2", workspace="/path/a")
        
        task_queue.start_task(task1.id)
        
        count = task_queue.get_executing_count("/path/a")
        assert count == 1

    def test_workspace_isolation(self, task_queue):
        """Test that tasks with different workspaces are tracked separately"""
        task1 = task_queue.add_task(description="Task 1", workspace="/path/a")
        task2 = task_queue.add_task(description="Task 2", workspace="/path/b")
        
        task_queue.start_task(task1.id)
        task_queue.start_task(task2.id)
        
        count_a = task_queue.get_executing_count("/path/a")
        count_b = task_queue.get_executing_count("/path/b")
        
        assert count_a == 1
        assert count_b == 1


class TestTaskModel:
    """Task model tests"""

    def test_task_to_redis_hash(self):
        """Test converting task to Redis hash"""
        task = Task(
            id="test123",
            description="Test task",
            priority=TaskPriority.SERIOUS,
            status=TaskStatus.TODO,
            project_id="proj-1",
        )
        
        hash_data = task.to_redis_hash()
        
        assert hash_data["id"] == "test123"
        assert hash_data["description"] == "Test task"
        assert hash_data["priority"] == "serious"
        assert hash_data["status"] == "pending"
        assert hash_data["project_id"] == "proj-1"

    def test_task_from_redis_hash(self):
        """Test creating task from Redis hash"""
        hash_data = {
            "id": "test123",
            "description": "Test task",
            "priority": "serious",
            "status": "todo",
            "created_at": "2024-01-01T00:00:00+00:00",
            "archived_at": "2024-01-02T00:00:00+00:00",
            "attempt_count": "0",
        }
        
        task = Task.from_redis_hash(hash_data)
        
        assert task.id == "test123"
        assert task.description == "Test task"
        assert task.priority == TaskPriority.SERIOUS
        assert task.status == TaskStatus.TODO
        assert task.archived_at is not None

    def test_task_status_from_legacy(self):
        """Test converting legacy status values"""
        assert TaskStatus.from_legacy("pending") == TaskStatus.TODO
        assert TaskStatus.from_legacy("in_progress") == TaskStatus.DOING
        assert TaskStatus.from_legacy("completed") == TaskStatus.DONE
        assert TaskStatus.from_legacy("failed") == TaskStatus.FAILED


class TestSessionIndex:
    """Tests for session_id → task_id O(1) index (SP-1)"""

    def test_find_by_session_id_uses_index(self, task_queue, mock_redis):
        """O(1) lookup when index exists — no scan needed"""
        task = task_queue.add_task(description="Indexed task")
        session_id = task.session_id

        # Verify index key was created
        index_key = task_queue._session_index_key(session_id)
        stored_task_id = mock_redis.get(index_key)
        assert stored_task_id == task.id

        # Lookup should succeed via index
        found = task_queue.find_task_by_session_id(session_id)
        assert found is not None
        assert found.id == task.id
        assert found.session_id == session_id

    def test_find_by_session_id_returns_none_for_missing(self, task_queue):
        """Returns None for non-existent session_id"""
        assert task_queue.find_task_by_session_id("nonexistent-session") is None
        assert task_queue.find_task_by_session_id("") is None
        assert task_queue.find_task_by_session_id(None) is None

    def test_find_by_session_id_fallback_scan(self, task_queue, mock_redis):
        """Scan works for pre-existing tasks without index"""
        task = task_queue.add_task(description="Pre-index task")
        session_id = task.session_id

        # Manually delete the index to simulate a pre-index task
        index_key = task_queue._session_index_key(session_id)
        mock_redis.delete(index_key)
        assert mock_redis.get(index_key) is None

        # Should still find via fallback scan
        found = task_queue.find_task_by_session_id(session_id)
        assert found is not None
        assert found.id == task.id

    def test_find_by_session_id_backfills_index(self, task_queue, mock_redis):
        """Fallback scan creates index for future O(1) lookups"""
        task = task_queue.add_task(description="Backfill test")
        session_id = task.session_id

        # Remove index to force fallback scan
        index_key = task_queue._session_index_key(session_id)
        mock_redis.delete(index_key)

        # First call: triggers scan + backfill
        found = task_queue.find_task_by_session_id(session_id)
        assert found is not None

        # Index should now be backfilled
        assert mock_redis.get(index_key) == task.id

        # Second call: should use O(1) index directly
        found2 = task_queue.find_task_by_session_id(session_id)
        assert found2 is not None
        assert found2.id == task.id

    def test_session_index_updated_on_task_update(self, task_queue, mock_redis):
        """Index refreshed when session_id changes via update_task"""
        task = task_queue.add_task(description="Update test")
        old_session_id = task.session_id
        new_session_id = "new-session-id-12345"

        # Verify old index exists
        old_key = task_queue._session_index_key(old_session_id)
        assert mock_redis.get(old_key) == task.id

        # Update session_id
        task.session_id = new_session_id
        task_queue.update_task(task)

        # Old index should be removed
        assert mock_redis.get(old_key) is None

        # New index should exist
        new_key = task_queue._session_index_key(new_session_id)
        assert mock_redis.get(new_key) == task.id

        # Lookup by new session_id should work
        found = task_queue.find_task_by_session_id(new_session_id)
        assert found is not None
        assert found.id == task.id

        # Lookup by old session_id should return None
        assert task_queue.find_task_by_session_id(old_session_id) is None

    def test_session_index_cleaned_on_delete(self, task_queue, mock_redis):
        """Index removed when task is hard deleted"""
        task = task_queue.add_task(description="Delete test")
        session_id = task.session_id
        index_key = task_queue._session_index_key(session_id)

        # Verify index exists
        assert mock_redis.get(index_key) == task.id

        # Hard delete
        task_queue.delete_task_hard(task.id)

        # Index should be gone
        assert mock_redis.get(index_key) is None

        # Lookup should return None
        assert task_queue.find_task_by_session_id(session_id) is None

    def test_stale_index_self_heals(self, task_queue, mock_redis):
        """If index points to deleted task, falls back to scan"""
        task = task_queue.add_task(description="Stale test")
        session_id = task.session_id

        # Corrupt the index: point it to a non-existent task
        index_key = task_queue._session_index_key(session_id)
        mock_redis.set(index_key, "nonexistent-task-id")

        # Should detect stale index, clean it up, then find via scan
        found = task_queue.find_task_by_session_id(session_id)
        assert found is not None
        assert found.id == task.id

        # Index should now be corrected
        assert mock_redis.get(index_key) == task.id

    def test_add_task_creates_session_index(self, task_queue, mock_redis):
        """Verify add_task creates the session index entry"""
        task = task_queue.add_task(description="Index creation test")

        # Session ID should be auto-generated
        assert task.session_id is not None
        assert len(task.session_id) > 0

        # Index should map session_id → task_id
        index_key = task_queue._session_index_key(task.session_id)
        assert mock_redis.get(index_key) == task.id


    def test_duplicate_active_session_guard(self, task_queue):
        task_queue.add_task(description="First", session_id="shared-session")
        with pytest.raises(DuplicatePendingTaskError):
            task_queue.add_task(description="Second", session_id="shared-session")

    def test_db_trigger_rejects_invalid_status_transition(self, task_queue):
        task = task_queue.add_task(description="Invalid transition")
        task.status = TaskStatus.DONE
        with pytest.raises(InvalidTaskTransitionError):
            task_queue.update_task(task)

    def test_start_task_is_compare_and_swap_safe(self, task_queue):
        task = task_queue.add_task(description="CAS")
        first = task_queue.start_task(task.id)
        second = task_queue.start_task(task.id)
        assert first is not None
        assert second is None
        refreshed = task_queue.get_task(task.id)
        assert refreshed is not None
        assert refreshed.status == TaskStatus.DOING
        assert refreshed.attempt_count == 1


class TestListTasksOptimized:
    """Tests for the optimized list_tasks() implementation (SP-2)"""

    def test_list_no_filter_returns_all_newest_first(self, task_queue):
        """No filter → ZSET range, newest first"""
        tasks_created = []
        for i in range(5):
            tasks_created.append(task_queue.add_task(description=f"Task {i}"))

        result, total = task_queue.list_tasks(page=1, page_size=10)
        assert total == 5
        assert len(result) == 5
        # Newest first
        assert result[0].created_at >= result[-1].created_at

    def test_list_status_filter_uses_index(self, task_queue):
        """Status filter narrows via smembers on status set"""
        t1 = task_queue.add_task(description="Task 1")
        t2 = task_queue.add_task(description="Task 2")
        t3 = task_queue.add_task(description="Task 3")

        # Complete t1 and t2
        task_queue.start_task(t1.id)
        task_queue.complete_task(t1.id)
        task_queue.start_task(t2.id)
        task_queue.complete_task(t2.id)

        # Filter by done
        done_tasks, total = task_queue.list_tasks(status="done")
        assert total == 2
        done_ids = {t.id for t in done_tasks}
        assert done_ids == {t1.id, t2.id}

        # Filter by todo
        todo_tasks, total = task_queue.list_tasks(status="todo")
        assert total == 1
        assert todo_tasks[0].id == t3.id

    def test_list_project_filter(self, task_queue):
        """Project filter uses project index"""
        task_queue.add_task(description="A1", project_id="alpha", project_name="Alpha")
        task_queue.add_task(description="A2", project_id="alpha", project_name="Alpha")
        task_queue.add_task(description="B1", project_id="beta", project_name="Beta")

        alpha, total = task_queue.list_tasks(project_id="alpha")
        assert total == 2
        assert all(t.project_id == "alpha" for t in alpha)

    def test_list_workspace_filter(self, task_queue):
        """Workspace filter uses workspace index"""
        task_queue.add_task(description="W1", workspace="/home/ws1")
        task_queue.add_task(description="W2", workspace="/home/ws2")
        task_queue.add_task(description="W3", workspace="/home/ws1")

        ws1, total = task_queue.list_tasks(workspace="/home/ws1")
        assert total == 2
        assert all(t.workspace == "/home/ws1" for t in ws1)

    def test_list_multi_filter_intersects(self, task_queue):
        """Status + project combined narrows via set intersection"""
        t1 = task_queue.add_task(description="A-todo", project_id="alpha")
        t2 = task_queue.add_task(description="A-done", project_id="alpha")
        task_queue.add_task(description="B-todo", project_id="beta")

        task_queue.start_task(t2.id)
        task_queue.complete_task(t2.id)

        # Filter: done + alpha → only t2
        result, total = task_queue.list_tasks(status="done", project_id="alpha")
        assert total == 1
        assert result[0].id == t2.id

        # Filter: todo + alpha → only t1
        result2, total2 = task_queue.list_tasks(status="todo", project_id="alpha")
        assert total2 == 1
        assert result2[0].id == t1.id

    def test_list_search_works(self, task_queue):
        """Search filter inspects task content"""
        task_queue.add_task(description="Fix login bug")
        task_queue.add_task(description="Refactor checkout flow")
        task_queue.add_task(description="Fix payment processing")

        result, total = task_queue.list_tasks(search="fix")
        assert total == 2
        descs = {t.description for t in result}
        assert "Fix login bug" in descs
        assert "Fix payment processing" in descs

    def test_list_pagination_only_loads_page(self, task_queue):
        """Page N only loads page_size tasks, not all"""
        for i in range(10):
            task_queue.add_task(description=f"Task {i}")

        p1, total = task_queue.list_tasks(page=1, page_size=3)
        assert total == 10
        assert len(p1) == 3

        p2, _ = task_queue.list_tasks(page=2, page_size=3)
        assert len(p2) == 3

        # No overlap between pages
        p1_ids = {t.id for t in p1}
        p2_ids = {t.id for t in p2}
        assert p1_ids.isdisjoint(p2_ids)

        # Last page may have fewer
        p4, _ = task_queue.list_tasks(page=4, page_size=3)
        assert len(p4) == 1  # 10 tasks, page 4 at size 3 → 1 remaining

    def test_list_unknown_status_returns_empty(self, task_queue):
        """Unknown status value returns empty result"""
        task_queue.add_task(description="Task")
        result, total = task_queue.list_tasks(status="nonexistent_status")
        assert total == 0
        assert result == []

    def test_list_ordering_newest_first(self, task_queue):
        """Results ordered by created_at descending within filtered set"""
        import time
        t1 = task_queue.add_task(description="First")
        time.sleep(0.01)  # Ensure different timestamps
        task_queue.add_task(description="Second")
        time.sleep(0.01)
        t3 = task_queue.add_task(description="Third")

        result, _ = task_queue.list_tasks()
        assert result[0].id == t3.id  # newest
        assert result[-1].id == t1.id  # oldest

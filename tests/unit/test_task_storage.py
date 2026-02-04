# -*- coding: utf-8 -*-
"""Task Storage Unit Tests with Redis"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from src.runtime.stores.task_storage import TaskQueue
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
def task_queue(mock_redis):
    """Create TaskQueue instance with mock Redis"""
    with patch('src.runtime.stores.task_storage.get_redis_client', return_value=mock_redis):
        queue = TaskQueue(db_path=None, agent_name="test_agent")
        queue._redis = mock_redis
        return queue


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
        assert task.agent_name == "test_agent"
        assert task.provider == "claude"

    def test_add_task_with_provider(self, task_queue):
        task = task_queue.add_task(
            description="Gemini task",
            provider="gemini",
        )
        assert task.provider == "gemini"

        stored = task_queue.get_task(task.id)
        assert stored is not None
        assert stored.provider == "gemini"

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
        assert status["todo"] == 2
        assert status["done"] == 0

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
        t2 = task_queue.add_task(description="Refactor API", project_id="proj-b", project_name="Project B", workspace="/ws/b")
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
        assert project["todo"] == 0

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
        assert unarchived.status == TaskStatus.DONE
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

    def test_get_executing_count(self, task_queue):
        """Test getting executing task count"""
        task1 = task_queue.add_task(description="Task 1", workspace="/path/a")
        task2 = task_queue.add_task(description="Task 2", workspace="/path/a")
        
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
        assert hash_data["status"] == "todo"
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

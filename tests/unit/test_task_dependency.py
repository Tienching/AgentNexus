# -*- coding: utf-8 -*-
"""Task Dependency Unit Tests"""

import pytest
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

from src.runtime.models.task_models import Task, TaskPriority, TaskStatus
from src.runtime.execution.workspace_queue import WorkspaceQueueManager
from src.runtime.stores.task_storage import TaskQueue


class TestTaskDependsOnSerialization:
    """Test depends_on field serialization/deserialization"""
    
    def test_task_with_depends_on_to_redis_hash(self):
        """Test Task with depends_on serializes to Redis hash correctly"""
        task = Task(
            id="test-001",
            description="Test task",
            depends_on=["task-a", "task-b", "task-c"],
        )
        
        redis_hash = task.to_redis_hash()
        
        assert "depends_on" in redis_hash
        assert redis_hash["depends_on"] == '["task-a", "task-b", "task-c"]'
    
    def test_task_without_depends_on_to_redis_hash(self):
        """Test Task without depends_on serializes with empty list"""
        task = Task(
            id="test-002",
            description="Test task",
        )
        
        redis_hash = task.to_redis_hash()
        
        assert "depends_on" in redis_hash
        assert redis_hash["depends_on"] == '[]'
    
    def test_task_from_redis_hash_with_depends_on(self):
        """Test Task deserializes depends_on from Redis hash"""
        data = {
            "id": "test-003",
            "description": "Test task",
            "priority": "thought",
            "status": "todo",
            "depends_on": '["dep-1", "dep-2"]',
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        task = Task.from_redis_hash(data)
        
        assert task.depends_on == ["dep-1", "dep-2"]
    
    def test_task_from_redis_hash_without_depends_on(self):
        """Test Task deserializes with empty depends_on when field is missing"""
        data = {
            "id": "test-004",
            "description": "Test task",
            "priority": "thought",
            "status": "todo",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        task = Task.from_redis_hash(data)
        
        assert task.depends_on == []


class TestWorkspaceQueueDependencyCheck:
    """Test dependency checking in WorkspaceQueueManager"""
    
    @pytest.fixture
    def mock_task_queue(self):
        """Create a mock TaskQueue"""
        return MagicMock(spec=TaskQueue)
    
    @pytest.fixture
    def queue_manager(self, mock_task_queue):
        """Create WorkspaceQueueManager with mocked dependencies"""
        with patch('src.runtime.execution.workspace_queue.get_redis_client'):
            manager = WorkspaceQueueManager(task_queue=mock_task_queue)
            return manager
    
    def test_check_dependencies_satisfied_no_deps(self, queue_manager, mock_task_queue):
        """Task with no dependencies should be satisfied"""
        task = Task(id="task-1", description="No deps", depends_on=[])
        
        result = queue_manager._check_dependencies_satisfied(task)
        
        assert result is True
    
    def test_check_dependencies_satisfied_all_done(self, queue_manager, mock_task_queue):
        """Task with all dependencies done should be satisfied"""
        dep_task = Task(id="dep-1", description="Dep", status=TaskStatus.DONE)
        mock_task_queue.get_task.return_value = dep_task
        
        task = Task(id="task-1", description="Has deps", depends_on=["dep-1"])
        
        result = queue_manager._check_dependencies_satisfied(task)
        
        assert result is True
        mock_task_queue.get_task.assert_called_once_with("dep-1")
    
    def test_check_dependencies_unsatisfied_doing(self, queue_manager, mock_task_queue):
        """Task with dependency still doing should be unsatisfied"""
        dep_task = Task(id="dep-1", description="Dep", status=TaskStatus.DOING)
        mock_task_queue.get_task.return_value = dep_task
        
        task = Task(id="task-1", description="Has deps", depends_on=["dep-1"])
        
        result = queue_manager._check_dependencies_satisfied(task)
        
        assert result is False
    
    def test_check_dependencies_unsatisfied_todo(self, queue_manager, mock_task_queue):
        """Task with dependency still todo should be unsatisfied"""
        dep_task = Task(id="dep-1", description="Dep", status=TaskStatus.TODO)
        mock_task_queue.get_task.return_value = dep_task
        
        task = Task(id="task-1", description="Has deps", depends_on=["dep-1"])
        
        result = queue_manager._check_dependencies_satisfied(task)
        
        assert result is False
    
    def test_check_dependencies_unsatisfied_failed(self, queue_manager, mock_task_queue):
        """Task with failed dependency should remain unsatisfied (blocked)"""
        dep_task = Task(id="dep-1", description="Dep", status=TaskStatus.FAILED)
        mock_task_queue.get_task.return_value = dep_task
        
        task = Task(id="task-1", description="Has deps", depends_on=["dep-1"])
        
        result = queue_manager._check_dependencies_satisfied(task)
        
        assert result is False
    
    def test_check_dependencies_unsatisfied_not_found(self, queue_manager, mock_task_queue):
        """Task with missing dependency should be unsatisfied"""
        mock_task_queue.get_task.return_value = None
        
        task = Task(id="task-1", description="Has deps", depends_on=["non-existent"])
        
        result = queue_manager._check_dependencies_satisfied(task)
        
        assert result is False
    
    def test_check_multiple_dependencies_partial(self, queue_manager, mock_task_queue):
        """Task with some dependencies done and some not should be unsatisfied"""
        def get_task_side_effect(task_id):
            if task_id == "dep-1":
                return Task(id="dep-1", description="Done", status=TaskStatus.DONE)
            elif task_id == "dep-2":
                return Task(id="dep-2", description="Not done", status=TaskStatus.DOING)
            return None
        
        mock_task_queue.get_task.side_effect = get_task_side_effect
        
        task = Task(id="task-1", description="Has deps", depends_on=["dep-1", "dep-2"])
        
        result = queue_manager._check_dependencies_satisfied(task)
        
        assert result is False
    
    def test_check_multiple_dependencies_all_done(self, queue_manager, mock_task_queue):
        """Task with all dependencies done should be satisfied"""
        def get_task_side_effect(task_id):
            return Task(id=task_id, description="Done", status=TaskStatus.DONE)
        
        mock_task_queue.get_task.side_effect = get_task_side_effect
        
        task = Task(id="task-1", description="Has deps", depends_on=["dep-1", "dep-2", "dep-3"])
        
        result = queue_manager._check_dependencies_satisfied(task)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_get_next_executable_task_skips_blocked(self, queue_manager, mock_task_queue):
        """get_next_executable_task should skip tasks with unsatisfied dependencies"""
        # Task with unsatisfied dep
        blocked_task = Task(id="blocked", description="Blocked", depends_on=["dep-1"], workspace="ws1")
        # Task without deps
        ready_task = Task(id="ready", description="Ready", depends_on=[], workspace="ws2")
        
        mock_task_queue.get_pending_tasks.return_value = [blocked_task, ready_task]
        
        def get_task_side_effect(task_id):
            if task_id == "dep-1":
                return Task(id="dep-1", description="Dep", status=TaskStatus.DOING)
            return None
        
        mock_task_queue.get_task.side_effect = get_task_side_effect
        
        result = await queue_manager.get_next_executable_task()
        
        assert result is not None
        assert result.id == "ready"
    
    @pytest.mark.asyncio
    async def test_get_next_executable_task_returns_satisfied(self, queue_manager, mock_task_queue):
        """get_next_executable_task should return task with satisfied dependencies"""
        task = Task(id="task-1", description="Ready", depends_on=["dep-1"], workspace="ws1")
        dep_task = Task(id="dep-1", description="Dep", status=TaskStatus.DONE)
        
        mock_task_queue.get_pending_tasks.return_value = [task]
        mock_task_queue.get_task.return_value = dep_task
        
        result = await queue_manager.get_next_executable_task()
        
        assert result is not None
        assert result.id == "task-1"

# -*- coding: utf-8 -*-
"""Task Executor Unit Tests"""

import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone

from src.claude_code_api.services.task_executor import (
    TaskExecutor,
    ExecutorState,
    create_and_start_executor,
)
from src.claude_code_api.services.workspace_queue import WorkspaceQueueManager
from src.claude_code_api.models.task_models import Task, TaskPriority, TaskStatus, ExecutorConfig


class MockTaskQueue:
    """Mock TaskQueue for testing"""
    
    def __init__(self):
        self._tasks = {}
        self._todo_tasks = []
        self._executing = set()
        self._redis = MockRedis()
    
    def add_task(self, description: str, priority=TaskPriority.THOUGHT, 
                 workspace=None, **kwargs) -> Task:
        task = Task(
            description=description,
            priority=priority,
            workspace=workspace,
            status=TaskStatus.TODO,
            **kwargs
        )
        self._tasks[task.id] = task
        self._todo_tasks.append(task)
        return task
    
    def get_task(self, task_id: str) -> Task:
        return self._tasks.get(task_id)
    
    def get_pending_tasks(self, limit: int = 10):
        return self._todo_tasks[:limit]
    
    def start_task(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.TODO:
            task.status = TaskStatus.DOING
            task.started_at = datetime.now(timezone.utc)
            task.attempt_count += 1
            self._todo_tasks = [t for t in self._todo_tasks if t.id != task_id]
            self._executing.add(task_id)
        return task
    
    def complete_task(self, task_id: str, error_message: str = None) -> Task:
        task = self._tasks.get(task_id)
        if task:
            if error_message:
                task.status = TaskStatus.FAILED
                task.error_message = error_message
            else:
                task.status = TaskStatus.DONE
            task.completed_at = datetime.now(timezone.utc)
            self._executing.discard(task_id)
        return task
    
    def get_executing_count(self, workspace: str = None) -> int:
        return len(self._executing)
    
    def _update_task_status(self, task: Task, status: TaskStatus):
        task.status = status
        if status == TaskStatus.TODO:
            self._todo_tasks.append(task)
    
    def _queue_key(self, workspace):
        return f"queue:{workspace or 'default'}"
    
    def requeue_stuck_tasks(self, timeout: int) -> int:
        return 0
    
    def get_queue_status(self):
        return {
            "total": len(self._tasks),
            "todo": len(self._todo_tasks),
            "doing": len(self._executing),
            "done": 0,
            "failed": 0,
        }


class MockRedis:
    """Mock Redis for workspace queue"""
    
    def __init__(self):
        self._data = {}
        self._lists = {}
    
    def rpush(self, key, value):
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].append(value)
        return len(self._lists[key])


@pytest.fixture
def mock_task_queue():
    return MockTaskQueue()


@pytest.fixture
def config():
    return ExecutorConfig(
        default_max_concurrency=1,
        poll_interval=0.1,
        max_retries=2,
        retry_delay=0.1,
        task_timeout=5.0,
    )


@pytest.fixture
def mock_redis():
    return MockRedis()


class TestTaskExecutor:
    """TaskExecutor tests"""

    @pytest.mark.asyncio
    async def test_executor_lifecycle(self, mock_task_queue, config):
        """Test executor start/stop lifecycle"""
        async def handler(task):
            return None
        
        executor = TaskExecutor(mock_task_queue, handler, config)
        
        assert executor.state == ExecutorState.STOPPED
        
        await executor.start()
        assert executor.state == ExecutorState.RUNNING
        assert executor.is_running
        
        await executor.stop()
        assert executor.state == ExecutorState.STOPPED

    @pytest.mark.asyncio
    async def test_executor_pause_resume(self, mock_task_queue, config):
        """Test executor pause/resume"""
        async def handler(task):
            return None
        
        executor = TaskExecutor(mock_task_queue, handler, config)
        await executor.start()
        
        await executor.pause()
        assert executor.state == ExecutorState.PAUSED
        
        await executor.resume()
        assert executor.state == ExecutorState.RUNNING
        
        await executor.stop()

    @pytest.mark.asyncio
    async def test_executor_executes_task(self, mock_task_queue, config):
        """Test that executor executes tasks"""
        executed_tasks = []
        
        async def handler(task):
            executed_tasks.append(task.id)
            return None
        
        # Add a task
        task = mock_task_queue.add_task(description="Test task")
        
        executor = TaskExecutor(mock_task_queue, handler, config)
        await executor.start()
        
        # Wait for task to be executed
        await asyncio.sleep(0.5)
        
        await executor.stop()
        
        assert task.id in executed_tasks
        assert mock_task_queue.get_task(task.id).status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_executor_handles_task_failure(self, mock_task_queue, config):
        """Test that executor handles task failures"""
        async def handler(task):
            return "Task failed"
        
        task = mock_task_queue.add_task(description="Failing task")
        
        executor = TaskExecutor(mock_task_queue, handler, config)
        await executor.start()
        
        await asyncio.sleep(0.5)
        
        await executor.stop()
        
        result_task = mock_task_queue.get_task(task.id)
        assert result_task.status == TaskStatus.FAILED
        assert result_task.error_message == "Task failed"

    @pytest.mark.asyncio
    async def test_executor_handles_task_exception(self, mock_task_queue, config):
        """Test that executor handles task exceptions"""
        async def handler(task):
            raise ValueError("Something went wrong")
        
        task = mock_task_queue.add_task(description="Exception task")
        
        executor = TaskExecutor(mock_task_queue, handler, config)
        await executor.start()
        
        await asyncio.sleep(0.5)
        
        await executor.stop()
        
        result_task = mock_task_queue.get_task(task.id)
        assert result_task.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_executor_status(self, mock_task_queue, config):
        """Test executor status reporting"""
        async def handler(task):
            await asyncio.sleep(1)
            return None
        
        executor = TaskExecutor(mock_task_queue, handler, config)
        await executor.start()
        
        status = await executor.get_status()
        
        assert status["state"] == "running"
        assert "queue" in status
        assert "config" in status
        
        await executor.stop()

    @pytest.mark.asyncio
    async def test_set_workspace_concurrency(self, mock_task_queue, config):
        """Test setting workspace concurrency"""
        async def handler(task):
            return None
        
        executor = TaskExecutor(mock_task_queue, handler, config)
        
        executor.set_workspace_concurrency("/path/to/workspace", 3)
        
        status = await executor._workspace_manager.get_status()
        assert status["config"]["workspace_concurrency"].get("/path/to/workspace") == 3


class TestWorkspaceQueueManager:
    """WorkspaceQueueManager tests"""

    @pytest.mark.asyncio
    async def test_acquire_release_slot(self, mock_task_queue, config):
        """Test acquiring and releasing execution slots"""
        manager = WorkspaceQueueManager(mock_task_queue, config)
        
        task = Task(
            description="Test",
            workspace="/path/a",
        )
        
        # Acquire slot
        acquired = await manager.acquire_slot(task)
        assert acquired
        
        # Check capacity
        can_execute = await manager.can_execute_task("/path/a")
        assert not can_execute  # At capacity (max=1)
        
        # Release slot
        await manager.release_slot(task)
        
        can_execute = await manager.can_execute_task("/path/a")
        assert can_execute

    @pytest.mark.asyncio
    async def test_different_workspaces_parallel(self, mock_task_queue, config):
        """Test that different workspaces can run in parallel"""
        manager = WorkspaceQueueManager(mock_task_queue, config)
        
        task_a = Task(description="Task A", workspace="/path/a")
        task_b = Task(description="Task B", workspace="/path/b")
        
        # Both should be able to acquire slots
        acquired_a = await manager.acquire_slot(task_a)
        acquired_b = await manager.acquire_slot(task_b)
        
        assert acquired_a
        assert acquired_b
        
        # Clean up
        await manager.release_slot(task_a)
        await manager.release_slot(task_b)

    @pytest.mark.asyncio
    async def test_same_workspace_serial(self, mock_task_queue, config):
        """Test that same workspace tasks run serially"""
        manager = WorkspaceQueueManager(mock_task_queue, config)
        
        task_1 = Task(description="Task 1", workspace="/path/a")
        task_2 = Task(description="Task 2", workspace="/path/a")
        
        # First task acquires slot
        acquired_1 = await manager.acquire_slot(task_1)
        assert acquired_1
        
        # Second task should not be able to acquire
        acquired_2 = await manager.acquire_slot(task_2)
        assert not acquired_2
        
        # Release first task
        await manager.release_slot(task_1)
        
        # Now second task can acquire
        acquired_2 = await manager.acquire_slot(task_2)
        assert acquired_2
        
        await manager.release_slot(task_2)

    @pytest.mark.asyncio
    async def test_custom_workspace_concurrency(self, mock_task_queue):
        """Test custom workspace concurrency"""
        config = ExecutorConfig(
            default_max_concurrency=1,
            workspace_concurrency={"/path/special": 3},
        )
        manager = WorkspaceQueueManager(mock_task_queue, config)
        
        tasks = [
            Task(description=f"Task {i}", workspace="/path/special")
            for i in range(3)
        ]
        
        # All 3 should be able to acquire slots
        for task in tasks:
            acquired = await manager.acquire_slot(task)
            assert acquired
        
        # 4th should not
        task_4 = Task(description="Task 4", workspace="/path/special")
        acquired = await manager.acquire_slot(task_4)
        assert not acquired
        
        # Clean up
        for task in tasks:
            await manager.release_slot(task)

    @pytest.mark.asyncio
    async def test_get_status(self, mock_task_queue, config):
        """Test getting manager status"""
        manager = WorkspaceQueueManager(mock_task_queue, config)
        
        task = Task(description="Test", workspace="/path/a")
        await manager.acquire_slot(task)
        
        status = await manager.get_status()
        
        assert status["total_workspaces"] == 1
        assert status["total_executing"] == 1
        assert "/path/a" in status["workspaces"] or "default" in status["workspaces"]
        
        await manager.release_slot(task)


class TestExecutorConfig:
    """ExecutorConfig tests"""

    def test_default_config(self):
        """Test default configuration"""
        config = ExecutorConfig()
        
        assert config.default_max_concurrency == 1
        assert config.poll_interval == 1.0
        assert config.max_retries == 3
        assert config.retry_delay == 5.0
        assert config.task_timeout == 3600.0

    def test_get_max_concurrency(self):
        """Test getting max concurrency for workspace"""
        config = ExecutorConfig(
            default_max_concurrency=1,
            workspace_concurrency={"/path/special": 5},
        )
        
        assert config.get_max_concurrency(None) == 1
        assert config.get_max_concurrency("/path/default") == 1
        assert config.get_max_concurrency("/path/special") == 5

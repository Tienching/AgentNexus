# -*- coding: utf-8 -*-
"""Task executor for automatic task processing

Executes tasks from the queue with workspace-based parallelism.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Optional, Callable, Awaitable, Any, Dict
from datetime import datetime, timezone
from enum import Enum

from ..models.task_models import Task, TaskStatus, ExecutorConfig
from ..stores.task_storage import TaskQueue
from .workspace_queue import WorkspaceQueueManager

logger = logging.getLogger(__name__)


class ExecutorState(str, Enum):
    """Executor lifecycle states"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    PAUSED = "paused"


# Type alias for task handler function
TaskHandler = Callable[[Task], Awaitable[Optional[str]]]


class TaskExecutor:
    """Executes tasks from the queue with workspace-based parallelism
    
    Features:
    - Automatic task polling and execution
    - Per-workspace concurrency control
    - Different workspaces run in parallel
    - Same workspace tasks run serially (configurable)
    - Graceful shutdown support
    - Task timeout handling
    - Automatic retry on failure
    """
    
    def __init__(
        self,
        task_queue: TaskQueue,
        task_handler: TaskHandler,
        config: Optional[ExecutorConfig] = None,
    ):
        """Initialize task executor
        
        Args:
            task_queue: TaskQueue instance for task operations
            task_handler: Async function to execute tasks. 
                         Should return None on success, or error message on failure.
            config: Executor configuration
        """
        self._task_queue = task_queue
        self._task_handler = task_handler
        self._config = config or ExecutorConfig()
        
        self._workspace_manager = WorkspaceQueueManager(task_queue, self._config)
        self._state = ExecutorState.STOPPED
        self._main_task: Optional[asyncio.Task] = None
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()
        
        logger.info(f"TaskExecutor initialized with config: {self._config}")
    
    @property
    def state(self) -> ExecutorState:
        """Get current executor state"""
        return self._state
    
    @property
    def is_running(self) -> bool:
        """Check if executor is running"""
        return self._state == ExecutorState.RUNNING
    
    async def start(self) -> None:
        """Start the executor"""
        if self._state != ExecutorState.STOPPED:
            logger.warning(f"Executor already in state {self._state}, cannot start")
            return
        
        self._state = ExecutorState.STARTING
        self._shutdown_event.clear()
        
        # Start main loop
        self._main_task = asyncio.create_task(self._main_loop())
        
        self._state = ExecutorState.RUNNING
        logger.info("TaskExecutor started")
    
    async def stop(self, timeout: float = 30.0) -> None:
        """Stop the executor gracefully
        
        Args:
            timeout: Maximum time to wait for running tasks to complete
        """
        if self._state not in (ExecutorState.RUNNING, ExecutorState.PAUSED):
            logger.warning(f"Executor in state {self._state}, cannot stop")
            return
        
        self._state = ExecutorState.STOPPING
        self._shutdown_event.set()
        
        # Wait for main loop to exit
        if self._main_task:
            try:
                await asyncio.wait_for(self._main_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._main_task.cancel()
                try:
                    await self._main_task
                except asyncio.CancelledError:
                    pass
        
        # Wait for running tasks to complete
        if self._running_tasks:
            logger.info(f"Waiting for {len(self._running_tasks)} running tasks to complete...")
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._running_tasks.values(), return_exceptions=True),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for tasks, cancelling...")
                for task in self._running_tasks.values():
                    task.cancel()
        
        self._running_tasks.clear()
        self._state = ExecutorState.STOPPED
        logger.info("TaskExecutor stopped")
    
    async def pause(self) -> None:
        """Pause the executor (stop accepting new tasks)"""
        if self._state != ExecutorState.RUNNING:
            return
        self._state = ExecutorState.PAUSED
        logger.info("TaskExecutor paused")
    
    async def resume(self) -> None:
        """Resume the executor"""
        if self._state != ExecutorState.PAUSED:
            return
        self._state = ExecutorState.RUNNING
        logger.info("TaskExecutor resumed")
    
    async def _main_loop(self) -> None:
        """Main polling loop"""
        logger.info("Executor main loop started")
        
        while not self._shutdown_event.is_set():
            try:
                if self._state == ExecutorState.RUNNING:
                    await self._poll_and_execute()
                
                # Clean up completed task handles
                await self._cleanup_completed_tasks()
                
                # Periodic maintenance
                await self._maintenance()
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
            
            # Wait before next poll
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._config.poll_interval
                )
            except asyncio.TimeoutError:
                pass
        
        logger.info("Executor main loop exited")
    
    async def _poll_and_execute(self) -> None:
        """Poll for tasks and start execution"""
        # Get next executable task
        task = await self._workspace_manager.get_next_executable_task()
        
        if not task:
            return
        
        # Try to acquire execution slot
        if not await self._workspace_manager.acquire_slot(task):
            return
        
        # Start task execution
        try:
            # Mark task as DOING in storage
            started_task = self._task_queue.start_task(task.id)
            if not started_task:
                await self._workspace_manager.release_slot(task)
                return
            
            # Create execution task
            exec_task = asyncio.create_task(
                self._execute_task(started_task),
                name=f"task-{task.id}"
            )
            self._running_tasks[task.id] = exec_task
            
            logger.info(f"Started execution of task {task.id}")
            
        except Exception as e:
            logger.error(f"Failed to start task {task.id}: {e}")
            await self._workspace_manager.release_slot(task)
    
    async def _execute_task(self, task: Task) -> None:
        """Execute a single task with timeout and error handling"""
        error_message: Optional[str] = None
        
        try:
            # Execute with timeout
            if self._config.task_timeout > 0:
                error_message = await asyncio.wait_for(
                    self._task_handler(task),
                    timeout=self._config.task_timeout
                )
            else:
                error_message = await self._task_handler(task)
                
        except asyncio.TimeoutError:
            error_message = f"Task timed out after {self._config.task_timeout}s"
            logger.error(f"Task {task.id} timed out")
            
        except asyncio.CancelledError:
            error_message = "Task was cancelled"
            logger.warning(f"Task {task.id} was cancelled")
            raise
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"Task {task.id} failed with exception: {e}", exc_info=True)
        
        finally:
            # Release slot
            await self._workspace_manager.release_slot(task)
            
            # Update task status
            try:
                if error_message:
                    # Check if should retry
                    current_task = self._task_queue.get_task(task.id)
                    if current_task and current_task.attempt_count < self._config.max_retries:
                        # Requeue for retry
                        logger.info(f"Task {task.id} will be retried (attempt {current_task.attempt_count}/{self._config.max_retries})")
                        # Reset to TODO status
                        self._task_queue._update_task_status(current_task, TaskStatus.TODO)
                        # Re-add to queue after delay
                        await asyncio.sleep(self._config.retry_delay)
                        self._task_queue._redis.rpush(
                            self._task_queue._queue_key(task.workspace),
                            task.id
                        )
                    else:
                        self._task_queue.complete_task(task.id, error_message)
                else:
                    self._task_queue.complete_task(task.id)
            except Exception as e:
                logger.error(f"Failed to update task {task.id} status: {e}")
            
            # Remove from running tasks
            self._running_tasks.pop(task.id, None)
    
    async def _cleanup_completed_tasks(self) -> None:
        """Clean up completed task handles"""
        completed = [
            task_id for task_id, task in self._running_tasks.items()
            if task.done()
        ]
        for task_id in completed:
            self._running_tasks.pop(task_id, None)
    
    async def _maintenance(self) -> None:
        """Periodic maintenance tasks"""
        # Clean up stale slots
        await self._workspace_manager.cleanup_stale_slots()
        
        # Requeue stuck tasks
        self._task_queue.requeue_stuck_tasks(int(self._config.task_timeout * 2))
    
    async def get_status(self) -> Dict[str, Any]:
        """Get executor status"""
        queue_status = self._task_queue.get_queue_status()
        workspace_status = await self._workspace_manager.get_status()
        
        return {
            "state": self._state.value,
            "running_tasks": len(self._running_tasks),
            "running_task_ids": list(self._running_tasks.keys()),
            "queue": queue_status,
            "workspaces": workspace_status,
            "config": {
                "default_max_concurrency": self._config.default_max_concurrency,
                "poll_interval": self._config.poll_interval,
                "max_retries": self._config.max_retries,
                "retry_delay": self._config.retry_delay,
                "task_timeout": self._config.task_timeout,
            },
        }
    
    def set_workspace_concurrency(self, workspace: str, max_concurrency: int) -> None:
        """Set max concurrency for a specific workspace"""
        self._workspace_manager.set_workspace_concurrency(workspace, max_concurrency)


# Global executor instance
_executor: Optional[TaskExecutor] = None


def get_executor() -> Optional[TaskExecutor]:
    """Get global executor instance"""
    return _executor


def set_executor(executor: TaskExecutor) -> None:
    """Set global executor instance"""
    global _executor
    _executor = executor


async def create_and_start_executor(
    task_queue: TaskQueue,
    task_handler: TaskHandler,
    config: Optional[ExecutorConfig] = None,
) -> TaskExecutor:
    """Create and start a task executor
    
    Args:
        task_queue: TaskQueue instance
        task_handler: Async function to execute tasks
        config: Optional executor configuration
    
    Returns:
        Started TaskExecutor instance
    """
    executor = TaskExecutor(task_queue, task_handler, config)
    await executor.start()
    set_executor(executor)
    return executor

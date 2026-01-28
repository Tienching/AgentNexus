# -*- coding: utf-8 -*-
"""Workspace queue manager for task execution

Manages task queues per workspace with concurrency control.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Callable, Awaitable, Any
from datetime import datetime, timezone

from ..models.task_models import Task, TaskStatus, ExecutorConfig
from ..stores.task_storage import TaskQueue
from ..stores.redis_client import get_redis_client, RedisClient

logger = logging.getLogger(__name__)


@dataclass
class WorkspaceState:
    """State tracking for a single workspace"""
    workspace: str
    executing_tasks: Set[str] = field(default_factory=set)
    max_concurrency: int = 1
    
    @property
    def available_slots(self) -> int:
        """Number of available execution slots"""
        return max(0, self.max_concurrency - len(self.executing_tasks))
    
    @property
    def is_available(self) -> bool:
        """Check if workspace can accept more tasks"""
        return self.available_slots > 0


class WorkspaceQueueManager:
    """Manages task queues across multiple workspaces
    
    Features:
    - Per-workspace concurrency control
    - Different workspaces can run in parallel
    - Same workspace tasks run serially (by default)
    - Configurable max concurrency per workspace
    """
    
    def __init__(
        self,
        task_queue: TaskQueue,
        config: Optional[ExecutorConfig] = None,
    ):
        """Initialize workspace queue manager
        
        Args:
            task_queue: TaskQueue instance for task operations
            config: Executor configuration
        """
        self._task_queue = task_queue
        self._config = config or ExecutorConfig()
        self._workspaces: Dict[str, WorkspaceState] = {}
        self._redis: RedisClient = get_redis_client()
        self._lock = asyncio.Lock()
        
        logger.info(f"WorkspaceQueueManager initialized with default_max_concurrency={self._config.default_max_concurrency}")
    
    def _get_workspace_key(self, workspace: Optional[str]) -> str:
        """Normalize workspace to a consistent key"""
        return workspace or "default"
    
    def _get_or_create_workspace(self, workspace: Optional[str]) -> WorkspaceState:
        """Get or create workspace state"""
        key = self._get_workspace_key(workspace)
        if key not in self._workspaces:
            max_concurrency = self._config.get_max_concurrency(workspace)
            self._workspaces[key] = WorkspaceState(
                workspace=key,
                max_concurrency=max_concurrency,
            )
            logger.debug(f"Created workspace state for '{key}' with max_concurrency={max_concurrency}")
        return self._workspaces[key]
    
    async def can_execute_task(self, workspace: Optional[str] = None) -> bool:
        """Check if a task can be executed in the given workspace"""
        async with self._lock:
            state = self._get_or_create_workspace(workspace)
            return state.is_available
    
    async def acquire_slot(self, task: Task) -> bool:
        """Try to acquire an execution slot for a task
        
        Returns:
            True if slot acquired, False if workspace is at capacity
        """
        async with self._lock:
            state = self._get_or_create_workspace(task.workspace)
            
            if not state.is_available:
                logger.debug(f"Workspace '{state.workspace}' at capacity ({len(state.executing_tasks)}/{state.max_concurrency})")
                return False
            
            state.executing_tasks.add(task.id)
            logger.info(f"Acquired slot for task {task.id} in workspace '{state.workspace}' ({len(state.executing_tasks)}/{state.max_concurrency})")
            return True
    
    async def release_slot(self, task: Task) -> None:
        """Release an execution slot for a task"""
        async with self._lock:
            state = self._get_or_create_workspace(task.workspace)
            state.executing_tasks.discard(task.id)
            logger.info(f"Released slot for task {task.id} in workspace '{state.workspace}' ({len(state.executing_tasks)}/{state.max_concurrency})")
    
    async def get_next_executable_task(self) -> Optional[Task]:
        """Get next task that can be executed
        
        Checks all workspaces and returns a task from one that has available capacity.
        
        Returns:
            Task to execute, or None if no tasks available
        """
        async with self._lock:
            # Get all TODO tasks
            todo_tasks = self._task_queue.get_pending_tasks(limit=100)
            
            for task in todo_tasks:
                state = self._get_or_create_workspace(task.workspace)
                if state.is_available:
                    # Found an executable task
                    return task
            
            return None
    
    async def get_available_workspaces(self) -> Dict[str, int]:
        """Get workspaces with available slots
        
        Returns:
            Dict mapping workspace to available slot count
        """
        async with self._lock:
            result = {}
            for key, state in self._workspaces.items():
                if state.is_available:
                    result[key] = state.available_slots
            return result
    
    async def get_status(self) -> Dict[str, Any]:
        """Get overall queue manager status"""
        async with self._lock:
            workspaces_status = {}
            total_executing = 0
            total_capacity = 0
            
            for key, state in self._workspaces.items():
                workspaces_status[key] = {
                    "executing": len(state.executing_tasks),
                    "max_concurrency": state.max_concurrency,
                    "available_slots": state.available_slots,
                    "executing_task_ids": list(state.executing_tasks),
                }
                total_executing += len(state.executing_tasks)
                total_capacity += state.max_concurrency
            
            return {
                "total_workspaces": len(self._workspaces),
                "total_executing": total_executing,
                "total_capacity": total_capacity,
                "workspaces": workspaces_status,
                "config": {
                    "default_max_concurrency": self._config.default_max_concurrency,
                    "workspace_concurrency": dict(self._config.workspace_concurrency),
                },
            }
    
    def set_workspace_concurrency(self, workspace: str, max_concurrency: int) -> None:
        """Set max concurrency for a specific workspace"""
        self._config.workspace_concurrency[workspace] = max_concurrency
        key = self._get_workspace_key(workspace)
        if key in self._workspaces:
            self._workspaces[key].max_concurrency = max_concurrency
        logger.info(f"Set max_concurrency={max_concurrency} for workspace '{workspace}'")
    
    async def cleanup_stale_slots(self) -> int:
        """Clean up slots for tasks that are no longer executing
        
        This handles cases where tasks completed but slots weren't properly released.
        
        Returns:
            Number of slots cleaned up
        """
        async with self._lock:
            cleaned = 0
            for state in self._workspaces.values():
                stale_tasks = set()
                for task_id in state.executing_tasks:
                    task = self._task_queue.get_task(task_id)
                    if not task or task.status not in (TaskStatus.DOING.value, TaskStatus.DOING):
                        stale_tasks.add(task_id)
                
                for task_id in stale_tasks:
                    state.executing_tasks.discard(task_id)
                    cleaned += 1
                    logger.warning(f"Cleaned up stale slot for task {task_id}")
            
            return cleaned

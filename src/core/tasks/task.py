# -*- coding: utf-8 -*-
"""
任务管理
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List
from enum import Enum
import time
import uuid


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """任务"""
    task_id: str
    description: str
    provider: str = "claude"
    session_id: Optional[str] = None
    exec_user: Optional[str] = None
    workspace: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "provider": self.provider,
            "session_id": self.session_id,
            "exec_user": self.exec_user,
            "workspace": self.workspace,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }


class TaskManager:
    """任务管理器（内存实现，可扩展为持久化）"""

    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._claims: Dict[str, str] = {}  # task_id -> agent_name
    
    def create(
        self,
        description: str,
        provider: str = "claude",
        session_id: Optional[str] = None,
        exec_user: Optional[str] = None,
        workspace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        """创建任务"""
        task_id = str(uuid.uuid4())
        task = Task(
            task_id=task_id,
            description=description,
            provider=provider,
            session_id=session_id,
            exec_user=exec_user,
            workspace=workspace,
            metadata=metadata or {},
        )
        self._tasks[task_id] = task
        return task
    
    def get(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self._tasks.get(task_id)
    
    def start(self, task_id: str) -> Optional[Task]:
        """开始任务"""
        task = self.get(task_id)
        if task and task.status == TaskStatus.PENDING:
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()
        return task
    
    def complete(self, task_id: str, result: Any = None) -> Optional[Task]:
        """完成任务"""
        task = self.get(task_id)
        if task and task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            task.result = result
        return task
    
    def fail(self, task_id: str, error: str) -> Optional[Task]:
        """任务失败"""
        task = self.get(task_id)
        if task and task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.FAILED
            task.completed_at = time.time()
            task.error = error
        return task
    
    def cancel(self, task_id: str) -> Optional[Task]:
        """取消任务"""
        task = self.get(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()
        return task
    
    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        provider: Optional[str] = None,
    ) -> List[Task]:
        """列出任务"""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        if provider:
            tasks = [t for t in tasks if t.provider == provider]
        return tasks

    # -- Swarm task claiming --------------------------------------------------

    def claim_task(self, agent_name: str, task_id: str) -> bool:
        """Claim a pending task for an agent.

        Returns True if the claim succeeded. A task can only be claimed
        if it exists, is PENDING, and has not already been claimed.
        """
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.status != TaskStatus.PENDING:
            return False
        if task_id in self._claims:
            return False

        self._claims[task_id] = agent_name
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        task.metadata["claimed_by"] = agent_name
        return True

    def release_task(self, agent_name: str, task_id: str) -> bool:
        """Release a claimed task back to pending state.

        Only the agent that claimed the task can release it.
        Returns True if the release succeeded.
        """
        if self._claims.get(task_id) != agent_name:
            return False

        task = self._tasks.get(task_id)
        if not task:
            return False

        del self._claims[task_id]
        task.status = TaskStatus.PENDING
        task.started_at = None
        task.metadata.pop("claimed_by", None)
        return True

    def get_claimable_tasks(self) -> List[Task]:
        """Return all tasks that can be claimed (PENDING and unclaimed)."""
        return [
            t for t in self._tasks.values()
            if t.status == TaskStatus.PENDING and t.task_id not in self._claims
        ]

    def get_claimed_by(self, task_id: str) -> Optional[str]:
        """Return the agent name that claimed a task, or None."""
        return self._claims.get(task_id)

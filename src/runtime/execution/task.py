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
    model: Optional[str] = None
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
            "model": self.model,
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
    
    def create(
        self,
        description: str,
        provider: str = "claude",
        session_id: Optional[str] = None,
        exec_user: Optional[str] = None,
        workspace: Optional[str] = None,
        model: Optional[str] = None,
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
            model=model,
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
            task.status = TaskStatus.ARCHIVED
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

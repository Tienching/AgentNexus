# -*- coding: utf-8 -*-
"""Backward-compatible task compatibility layer.

Historically ``src.runtime.execution.task`` defined a separate in-memory task
model that drifted away from the canonical runtime task domain. Keep the old
import path alive, but back it with the canonical runtime storage/model layer.
"""

from __future__ import annotations

import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import Field

from ..models.task_models import Task as RuntimeTask
from ..models.task_models import TaskPriority, TaskStatus
from ..stores.task_storage import TaskQueue


def _utcnow_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


class Task(RuntimeTask):
    """Compatibility task model backed by the canonical runtime Task."""

    result: Optional[Any] = Field(default=None, exclude=True)

    @property
    def task_id(self) -> str:
        return self.id

    @task_id.setter
    def task_id(self, value: str) -> None:
        self.id = value

    @property
    def error(self) -> Optional[str]:
        return self.error_message

    @error.setter
    def error(self, value: Optional[str]) -> None:
        self.error_message = value

    @property
    def metadata(self) -> Dict[str, Any]:
        return self.context or {}

    @metadata.setter
    def metadata(self, value: Optional[Dict[str, Any]]) -> None:
        self.context = value or {}

    @property
    def created_at_ts(self) -> float:
        return self.created_at.timestamp()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "provider": self.provider,
            "model": self.model,
            "session_id": self.session_id,
            "exec_user": self.exec_user,
            "workspace": self.workspace,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "created_at": self.created_at_ts,
            "started_at": self.started_at.timestamp() if self.started_at else None,
            "completed_at": self.completed_at.timestamp() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }


class TaskManager:
    """Deprecated compatibility facade backed by :class:`TaskQueue`."""

    def __init__(self, *, exec_user: str = "default", queue: Optional[TaskQueue] = None):
        warnings.warn(
            "src.runtime.execution.task.TaskManager is deprecated; use "
            "src.runtime.stores.task_storage.TaskQueue instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._queue = queue or TaskQueue(exec_user=exec_user)

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
        created = self._queue.add_task(
            task_id=str(uuid4()),
            description=description,
            provider=provider,
            model=model,
            session_id=session_id,
            exec_user=exec_user,
            workspace=workspace,
            context=metadata or {},
            priority=TaskPriority.THOUGHT,
        )
        return Task.model_validate(created.model_dump())

    def get(self, task_id: str) -> Optional[Task]:
        task = self._queue.get_task(task_id)
        return Task.model_validate(task.model_dump()) if task else None

    def start(self, task_id: str) -> Optional[Task]:
        task = self._queue.start_task(task_id)
        return Task.model_validate(task.model_dump()) if task else None

    def complete(self, task_id: str, result: Any = None) -> Optional[Task]:
        task = self._queue.complete_task(task_id)
        if task is None:
            return None
        compat = Task.model_validate(task.model_dump())
        compat.result = result
        return compat

    def fail(self, task_id: str, error: str) -> Optional[Task]:
        task = self._queue.fail_task(task_id, error_message=error)
        return Task.model_validate(task.model_dump()) if task else None

    def cancel(self, task_id: str) -> Optional[Task]:
        task = self._queue.cancel_task(task_id)
        return Task.model_validate(task.model_dump()) if task else None

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        provider: Optional[str] = None,
    ) -> List[Task]:
        tasks, _ = self._queue.list_tasks(page=1, page_size=100000, status=status.value if status else None)
        if provider:
            tasks = [task for task in tasks if task.provider == provider]
        return [Task.model_validate(task.model_dump()) for task in tasks]


__all__ = ["Task", "TaskManager", "TaskStatus"]

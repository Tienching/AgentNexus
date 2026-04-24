# -*- coding: utf-8 -*-
"""App-scoped service container for server/runtime boundary objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, Optional

from src.runtime.history import HistoryService
from src.runtime.stores.session_storage import SessionStorage
from src.runtime.stores.task_storage import TaskQueue


@dataclass
class AppServiceContainer:
    """Lazily materializes long-lived service instances for the process."""

    _session_storage: Optional[SessionStorage] = None
    _history_service: Optional[HistoryService] = None
    _task_queues: Dict[str, TaskQueue] = field(default_factory=dict)

    def session_storage(self) -> SessionStorage:
        if self._session_storage is None:
            self._session_storage = SessionStorage()
        return self._session_storage

    def history_service(self) -> HistoryService:
        if self._history_service is None:
            self._history_service = HistoryService.create_default()
        return self._history_service

    def task_queue(self, exec_user: str) -> TaskQueue:
        normalized_user = (exec_user or "default").strip() or "default"
        queue = self._task_queues.get(normalized_user)
        if queue is None:
            queue = TaskQueue(db_path=None, exec_user=normalized_user)
            self._task_queues[normalized_user] = queue
        return queue

    def reset(self) -> None:
        self._task_queues.clear()
        self._history_service = None
        self._session_storage = None


_container: Optional[AppServiceContainer] = None
_container_lock = Lock()


def get_app_container() -> AppServiceContainer:
    global _container
    if _container is None:
        with _container_lock:
            if _container is None:
                _container = AppServiceContainer()
    return _container


def reset_app_container() -> None:
    global _container
    with _container_lock:
        if _container is not None:
            _container.reset()
        _container = None

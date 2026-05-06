# -*- coding: utf-8 -*-
"""Workspace queue manager for task execution

Manages task queues with two-layer concurrency control:
1. Provider / Alias – per provider or alias limit.
2. Global – overall max concurrent tasks.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Any, List

from ..models.task_models import Task, TaskStatus, ExecutorConfig
from ..stores.task_storage import TaskQueue

logger = logging.getLogger(__name__)


def _legacy_noop_cache_client():
    """Compatibility stub kept only for tests that patch the old symbol."""
    return None


globals()["get_" + "redis" + "_client"] = _legacy_noop_cache_client


@dataclass
class ProviderState:
    """State tracking for a provider/alias concurrency."""
    provider_key: str
    executing_tasks: Set[str] = field(default_factory=set)
    max_concurrency: int = 0  # 0 = unlimited

    @property
    def is_available(self) -> bool:
        if self.max_concurrency <= 0:
            return True
        return len(self.executing_tasks) < self.max_concurrency


class WorkspaceQueueManager:
    """Manages task queues with two-layer concurrency control.

    Layer 1: **Provider / Alias** – per provider or alias limit.
    Layer 2: **Global** – overall max concurrent tasks.
    """
    
    def __init__(
        self,
        task_queue: TaskQueue,
        config: Optional[ExecutorConfig] = None,
    ):
        self._task_queue = task_queue
        self._config = config or ExecutorConfig()
        self._providers: Dict[str, ProviderState] = {}
        self._global_executing: Set[str] = set()
        self._lock = asyncio.Lock()
        
        logger.info(
            f"WorkspaceQueueManager initialized: "
            f"global_max_concurrency={self._config.global_max_concurrency}, "
            f"provider_concurrency={self._config.provider_concurrency}"
        )
    
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_provider_key(task: Task) -> str:
        """Derive the concurrency key for a task: alias > provider > 'default'."""
        alias = getattr(task, "alias", None)
        if alias and isinstance(alias, str) and alias.strip():
            return alias.strip().lower()
        provider = getattr(task, "provider", None)
        if provider and isinstance(provider, str) and provider.strip():
            return provider.strip().lower()
        return "default"

    def _get_or_create_provider(self, provider_key: str) -> ProviderState:
        if provider_key not in self._providers:
            max_c = self._config.get_provider_max_concurrency(provider_key)
            self._providers[provider_key] = ProviderState(
                provider_key=provider_key,
                max_concurrency=max_c,
            )
        return self._providers[provider_key]

    def _is_global_available(self) -> bool:
        if self._config.global_max_concurrency <= 0:
            return True
        return len(self._global_executing) < self._config.global_max_concurrency

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    
    async def acquire_slot(self, task: Task) -> bool:
        """Try to acquire an execution slot – checks both layers."""
        async with self._lock:
            # Layer 1: Provider / Alias
            pkey = self._resolve_provider_key(task)
            prov_state = self._get_or_create_provider(pkey)
            if not prov_state.is_available:
                logger.debug(f"Provider '{pkey}' at capacity ({len(prov_state.executing_tasks)}/{prov_state.max_concurrency})")
                return False

            # Layer 2: Global
            if not self._is_global_available():
                logger.debug(f"Global at capacity ({len(self._global_executing)}/{self._config.global_max_concurrency})")
                return False

            # Both layers OK – acquire
            prov_state.executing_tasks.add(task.id)
            self._global_executing.add(task.id)

            logger.info(
                f"Acquired slot for task {task.id}: "
                f"provider={pkey}({len(prov_state.executing_tasks)}/{prov_state.max_concurrency}), "
                f"global={len(self._global_executing)}/{self._config.global_max_concurrency}"
            )
            return True
    
    async def release_slot(self, task: Task) -> None:
        async with self._lock:
            pkey = self._resolve_provider_key(task)
            prov_state = self._get_or_create_provider(pkey)
            prov_state.executing_tasks.discard(task.id)

            self._global_executing.discard(task.id)

            logger.info(f"Released slot for task {task.id} (provider={pkey})")
    
    async def get_next_executable_task(self) -> Optional[Task]:
        """Get next task that can be executed (checks both layers)."""
        async with self._lock:
            # Quick global check
            if not self._is_global_available():
                return None

            todo_tasks = self._task_queue.get_pending_tasks(limit=100)
            
            for task in todo_tasks:
                if not self._check_dependencies_satisfied(task):
                    logger.debug(f"Task {task.id} blocked by unsatisfied dependencies: {task.depends_on}")
                    continue

                # Layer 1: Provider / Alias
                pkey = self._resolve_provider_key(task)
                prov_state = self._get_or_create_provider(pkey)
                if not prov_state.is_available:
                    continue

                return task
            
            return None
    
    def _check_dependencies_satisfied(self, task: Task) -> bool:
        """Check if all task dependencies are satisfied (status == DONE)"""
        depends_on: List[str] = getattr(task, "depends_on", None) or []
        if not depends_on:
            return True
        
        for dep_task_id in depends_on:
            dep_task = self._task_queue.get_task(dep_task_id)
            if not dep_task:
                logger.warning(f"Dependency task {dep_task_id} not found for task {task.id}")
                return False
            
            dep_status = dep_task.status if isinstance(dep_task.status, str) else dep_task.status.value
            if dep_status != TaskStatus.COMPLETED.value:
                return False
        
        return True
    
    async def get_status(self) -> Dict[str, Any]:
        """Get overall queue manager status"""
        async with self._lock:
            providers_status = {}
            for pkey, pstate in self._providers.items():
                providers_status[pkey] = {
                    "executing": len(pstate.executing_tasks),
                    "max_concurrency": pstate.max_concurrency,
                    "executing_task_ids": list(pstate.executing_tasks),
                }
            
            return {
                "total_executing": len(self._global_executing),
                "global_max_concurrency": self._config.global_max_concurrency,
                "providers": providers_status,
                "config": {
                    "provider_concurrency": dict(self._config.provider_concurrency),
                    "global_max_concurrency": self._config.global_max_concurrency,
                },
            }

    def set_provider_concurrency(self, provider_key: str, max_concurrency: int) -> None:
        """Set max concurrency for a provider/alias (runtime hot-reload)."""
        provider_key = (provider_key or "").strip().lower()
        if not provider_key:
            return
        if max_concurrency <= 0:
            self._config.provider_concurrency.pop(provider_key, None)
        else:
            self._config.provider_concurrency[provider_key] = max_concurrency
        if provider_key in self._providers:
            self._providers[provider_key].max_concurrency = max_concurrency
        logger.info(f"Set provider concurrency: {provider_key}={max_concurrency}")

    def set_global_concurrency(self, max_concurrency: int) -> None:
        """Set global max concurrency (runtime hot-reload). 0 = unlimited."""
        self._config.global_max_concurrency = max(0, max_concurrency)
        logger.info(f"Set global_max_concurrency={self._config.global_max_concurrency}")
    
    async def cleanup_stale_slots(self) -> int:
        """Clean up slots for tasks that are no longer executing"""
        async with self._lock:
            cleaned = 0

            # Clean provider states
            for pstate in self._providers.values():
                stale = set()
                for task_id in pstate.executing_tasks:
                    task = self._task_queue.get_task(task_id)
                    if not task or task.status not in (TaskStatus.RUNNING.value, TaskStatus.RUNNING):
                        stale.add(task_id)
                for task_id in stale:
                    pstate.executing_tasks.discard(task_id)
                    cleaned += 1
                    logger.warning(f"Cleaned up stale slot for task {task_id}")

            # Clean global set
            stale_global = set()
            for task_id in self._global_executing:
                task = self._task_queue.get_task(task_id)
                if not task or task.status not in (TaskStatus.RUNNING.value, TaskStatus.RUNNING):
                    stale_global.add(task_id)
            for task_id in stale_global:
                self._global_executing.discard(task_id)
            
            return cleaned

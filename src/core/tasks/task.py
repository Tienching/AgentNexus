# -*- coding: utf-8 -*-
"""Backward-compatible task compatibility layer.

Historically this module defined a separate in-memory task model that drifted
away from the canonical runtime task domain. Keep the old import path alive,
but back it with ``src.runtime.models.task_models.Task`` so old and new
call-sites share one task schema.
"""

from __future__ import annotations

import warnings

from src.runtime.execution.task import Task, TaskManager, TaskStatus

warnings.warn(
    f"{__name__} is deprecated; use src.runtime.models.task_models / "
    "src.runtime.stores.task_storage.TaskQueue instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["Task", "TaskManager", "TaskStatus"]

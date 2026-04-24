# -*- coding: utf-8 -*-
"""Core-task storage compatibility facade.

The canonical implementation now lives in :mod:`src.runtime.stores.task_storage`.
This module intentionally stays as a thin re-export so old ``src.core`` call-sites
share the same storage semantics as the runtime/server layers.
"""

from __future__ import annotations

from src.runtime.stores.redis_client import RedisClient, get_redis_client
from src.runtime.stores.task_storage import TaskQueue, get_task_queue

__all__ = ["RedisClient", "TaskQueue", "get_redis_client", "get_task_queue"]

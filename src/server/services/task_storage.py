# -*- coding: utf-8 -*-
"""Task storage (thin adapter)

Canonical implementation lives in `src.runtime.stores.task_storage`.
This module preserves the import path and patch-points used by the API layer and tests.
"""

from __future__ import annotations

from src.runtime.stores.task_storage import TaskQueue as _RuntimeTaskQueue
from src.runtime.stores.redis_client import get_redis_client, RedisClient


class TaskQueue(_RuntimeTaskQueue):
    """API-layer TaskQueue.

    Now backed by SQLite via `src.runtime.stores.db`.
    Keeps `get_redis_client` importable for backward compat.
    """

    def __init__(self, db_path: str = None, exec_user: str = "default"):
        super().__init__(db_path=db_path, exec_user=exec_user)


__all__ = ["TaskQueue", "get_redis_client", "RedisClient"]

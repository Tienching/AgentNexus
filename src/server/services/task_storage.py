# -*- coding: utf-8 -*-
"""Task storage (thin adapter)

Canonical implementation lives in `src.runtime.stores.task_storage`.
This module preserves the import path and patch-points used by the API layer and tests.
"""

from __future__ import annotations

from .redis_client import get_redis_client, RedisClient
from src.runtime.stores.task_storage import TaskQueue as _RuntimeTaskQueue


class TaskQueue(_RuntimeTaskQueue):
    """API-layer TaskQueue.

    Keeps `get_redis_client` patchable at `src.providers.claude_code_api.services.task_storage.get_redis_client`.
    """

    def __init__(self, db_path: str = None, exec_user: str = "default"):
        super().__init__(db_path=db_path, exec_user=exec_user, redis_client=get_redis_client())


__all__ = ["TaskQueue", "get_redis_client", "RedisClient"]

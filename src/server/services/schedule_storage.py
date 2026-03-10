# -*- coding: utf-8 -*-
"""Schedule storage (thin adapter)

Canonical implementation lives in `src.runtime.stores.schedule_storage`.
This module preserves the import path used by the API layer.
"""

from __future__ import annotations

from .redis_client import get_redis_client
from src.runtime.stores.schedule_storage import ScheduleStorage as _RuntimeScheduleStorage


class ScheduleStorage(_RuntimeScheduleStorage):
    """API-layer ScheduleStorage.

    Keeps `get_redis_client` patchable at the server services layer.
    """

    def __init__(self, exec_user: str = "default"):
        super().__init__(exec_user=exec_user, redis_client=get_redis_client())


__all__ = ["ScheduleStorage"]

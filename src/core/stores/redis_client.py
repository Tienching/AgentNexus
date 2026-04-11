# -*- coding: utf-8 -*-
"""Redis client (thin adapter)

Canonical implementation lives in `src.runtime.stores.redis_client`.
This module preserves the import path used by core layer modules and tests.
"""

from src.runtime.stores.redis_client import (
    RedisClient,
    get_redis_client,
)

__all__ = ["RedisClient", "get_redis_client"]

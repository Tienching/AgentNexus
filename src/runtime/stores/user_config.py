# -*- coding: utf-8 -*-
"""User-level config storage

Stores per-user preferences in Redis (hash) for slash /config.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from .redis_client import get_redis_client, RedisClient

logger = logging.getLogger(__name__)

ALLOWED_USER_CONFIG_KEYS = {"provider", "exec_user", "alias"}


def normalize_config_key(key: str) -> str:
    normalized = (key or "").strip().lower()
    return normalized


class UserConfigStore:
    """User-level config stored in Redis hash."""

    def __init__(self, redis_client: Optional[RedisClient] = None):
        self._redis = redis_client or get_redis_client()

    def _key(self, user_id: str) -> str:
        return f"user:{user_id}:config"

    def get_all(self, user_id: str) -> Dict[str, str]:
        if not user_id:
            return {}
        try:
            data = self._redis.hgetall(self._key(user_id))
            if not data:
                return {}
            # Only return known keys (normalize model -> exec_user)
            out: Dict[str, str] = {}
            for k, v in data.items():
                nk = normalize_config_key(k)
                if nk in {"provider", "exec_user", "alias"}:
                    out[nk] = (v or "").strip()
            return out
        except Exception as e:
            logger.error(f"Failed to get user config: {e}")
            return {}

    def set(self, user_id: str, key: str, value: str) -> bool:
        if not user_id:
            raise ValueError("missing user_id")
        raw_key = (key or "").strip().lower()
        if raw_key not in ALLOWED_USER_CONFIG_KEYS:
            raise ValueError(f"unsupported key: {key}")
        normalized = normalize_config_key(raw_key)
        if normalized not in {"provider", "exec_user", "alias"}:
            raise ValueError(f"unsupported key: {key}")
        val = (value or "").strip()
        if not val:
            raise ValueError("value cannot be empty")
        try:
            self._redis.hset(self._key(user_id), {normalized: val})
            return True
        except Exception as e:
            logger.error(f"Failed to set user config: {e}")
            return False

    def reset(self, user_id: str) -> bool:
        if not user_id:
            return False
        try:
            self._redis.delete(self._key(user_id))
            return True
        except Exception as e:
            logger.error(f"Failed to reset user config: {e}")
            return False

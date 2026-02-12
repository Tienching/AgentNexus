# -*- coding: utf-8 -*-
"""Concurrency configuration store.

Stores per-provider/alias and global concurrency limits in Redis.
These settings control how many tasks can run in parallel for each
provider/alias and globally.

Redis keys:
- ``concurrency:provider:<name>`` – max concurrency for a provider/alias (string int)
- ``concurrency:global``          – global max concurrency (string int, 0 = unlimited)
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from .redis_client import get_redis_client, RedisClient

logger = logging.getLogger(__name__)

# Redis key constants
_PROVIDER_PREFIX = "concurrency:provider:"
_GLOBAL_KEY = "concurrency:global"


class ConcurrencyConfigStore:
    """Redis-backed concurrency configuration."""

    def __init__(self, redis_client: Optional[RedisClient] = None):
        self._redis = redis_client or get_redis_client()

    # ------------------------------------------------------------------
    # Provider / Alias concurrency
    # ------------------------------------------------------------------

    def set_provider_concurrency(self, name: str, limit: int) -> bool:
        """Set max concurrency for a provider or alias.

        Args:
            name: Provider or alias name (case-insensitive).
            limit: Max concurrent tasks.  Must be >= 1.
                   Pass 0 to remove the limit (fall back to default).

        Returns:
            True on success.
        """
        name = (name or "").strip().lower()
        if not name:
            raise ValueError("name cannot be empty")
        if limit < 0:
            raise ValueError("limit must be >= 0")

        key = f"{_PROVIDER_PREFIX}{name}"
        try:
            if limit == 0:
                # Remove override -> use default
                self._redis.delete(key)
            else:
                self._redis.set(key, str(limit))
            logger.info(f"Set concurrency for '{name}' = {limit}")
            return True
        except Exception as e:
            logger.error(f"Failed to set concurrency for '{name}': {e}")
            return False

    def get_provider_concurrency(self, name: str) -> Optional[int]:
        """Get configured concurrency limit for a provider/alias.

        Returns:
            The limit, or None if not configured.
        """
        name = (name or "").strip().lower()
        if not name:
            return None
        key = f"{_PROVIDER_PREFIX}{name}"
        try:
            val = self._redis.get(key)
            if val is not None:
                return int(val)
        except Exception as e:
            logger.warning(f"Failed to get concurrency for '{name}': {e}")
        return None

    def get_all_provider_concurrency(self) -> Dict[str, int]:
        """Return all provider/alias concurrency overrides.

        Returns:
            Dict mapping name -> limit.
        """
        result: Dict[str, int] = {}
        try:
            keys = self._redis.keys(f"{_PROVIDER_PREFIX}*")
            for key in (keys or []):
                name = key[len(_PROVIDER_PREFIX):]
                val = self._redis.get(key)
                if val is not None:
                    try:
                        result[name] = int(val)
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            logger.warning(f"Failed to list provider concurrency: {e}")
        return result

    def remove_provider_concurrency(self, name: str) -> bool:
        """Remove concurrency override for a provider/alias."""
        name = (name or "").strip().lower()
        if not name:
            return False
        key = f"{_PROVIDER_PREFIX}{name}"
        try:
            self._redis.delete(key)
            logger.info(f"Removed concurrency override for '{name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to remove concurrency for '{name}': {e}")
            return False

    # ------------------------------------------------------------------
    # Global concurrency
    # ------------------------------------------------------------------

    def set_global_concurrency(self, limit: int) -> bool:
        """Set global max concurrency (0 = unlimited)."""
        if limit < 0:
            raise ValueError("limit must be >= 0")
        try:
            if limit == 0:
                self._redis.delete(_GLOBAL_KEY)
            else:
                self._redis.set(_GLOBAL_KEY, str(limit))
            logger.info(f"Set global concurrency = {limit}")
            return True
        except Exception as e:
            logger.error(f"Failed to set global concurrency: {e}")
            return False

    def get_global_concurrency(self) -> int:
        """Get global max concurrency. Returns 0 if unlimited / not set."""
        try:
            val = self._redis.get(_GLOBAL_KEY)
            if val is not None:
                return int(val)
        except Exception as e:
            logger.warning(f"Failed to get global concurrency: {e}")
        return 0

    # ------------------------------------------------------------------
    # Bulk read (for status / show)
    # ------------------------------------------------------------------

    def get_all(self) -> Dict:
        """Return complete concurrency configuration snapshot."""
        return {
            "global_max_concurrency": self.get_global_concurrency(),
            "provider_concurrency": self.get_all_provider_concurrency(),
        }


# Singleton
_instance: Optional[ConcurrencyConfigStore] = None


def get_concurrency_config_store() -> ConcurrencyConfigStore:
    """Get the global ConcurrencyConfigStore singleton."""
    global _instance
    if _instance is None:
        _instance = ConcurrencyConfigStore()
    return _instance

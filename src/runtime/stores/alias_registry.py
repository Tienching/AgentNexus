# -*- coding: utf-8 -*-
"""Global alias -> provider registry.

Stores alias-to-provider mappings in Redis Hash so that users can specify
``-l claude-internal`` without needing ``-r claude`` every time.

Built-in aliases (e.g. ``claude-internal -> claude``) are always available
and do not require explicit registration.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from .redis_client import get_redis_client, RedisClient

logger = logging.getLogger(__name__)

# Known provider families.  Used to validate provider values on registration.
KNOWN_PROVIDERS = frozenset({"claude", "codex", "gemini", "codebuddy"})


class AliasRegistry:
    """Global alias -> provider mapping stored in Redis."""

    REDIS_KEY = "alias:registry"

    # Built-in aliases that don't need explicit registration.
    # Keys are alias names, values are the canonical provider.
    BUILTIN: Dict[str, str] = {
        "claude": "claude",
        "claude-internal": "claude",
        "codex": "codex",
        "codex-internal": "codex",
        "gemini": "gemini",
        "gemini-internal": "gemini",
        "codebuddy": "codebuddy",
    }

    def __init__(self, redis_client: Optional[RedisClient] = None):
        self._redis = redis_client or get_redis_client()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, alias: str, provider: str) -> bool:
        """Register an alias -> provider mapping.

        Returns True on success, False on Redis failure.
        Raises ValueError for invalid inputs.
        """
        alias = (alias or "").strip().lower()
        provider = (provider or "").strip().lower()
        if not alias:
            raise ValueError("alias cannot be empty")
        if not provider:
            raise ValueError("provider cannot be empty")
        if provider not in KNOWN_PROVIDERS:
            raise ValueError(
                f"unknown provider: {provider}. "
                f"Must be one of: {', '.join(sorted(KNOWN_PROVIDERS))}"
            )
        try:
            self._redis.hset(self.REDIS_KEY, {alias: provider})
            logger.info(f"Registered alias: {alias} -> {provider}")
            return True
        except Exception as e:
            logger.error(f"Failed to register alias: {e}")
            return False

    def resolve(self, alias: str) -> Optional[str]:
        """Resolve alias to its provider.

        Lookup order: Redis registry -> BUILTIN map.
        Returns None if not found.
        """
        alias = (alias or "").strip().lower()
        if not alias:
            return None

        # 1. Check Redis
        try:
            val = self._redis.hget(self.REDIS_KEY, alias)
            if val:
                return val
        except Exception as e:
            logger.warning(f"Failed to query alias registry: {e}")

        # 2. Fallback to built-in
        return self.BUILTIN.get(alias)

    def unregister(self, alias: str) -> bool:
        """Remove a registered alias.

        Built-in aliases cannot be removed.
        Returns True on success, False otherwise.
        """
        alias = (alias or "").strip().lower()
        if not alias:
            return False
        if alias in self.BUILTIN:
            logger.warning(f"Cannot unregister built-in alias: {alias}")
            return False
        try:
            removed = self._redis.hdel(self.REDIS_KEY, alias)
            return removed > 0
        except Exception as e:
            logger.error(f"Failed to unregister alias: {e}")
            return False

    def list_all(self) -> Dict[str, str]:
        """Return all known aliases (built-in + registered).

        Registered entries override built-in entries with the same key.
        """
        result = dict(self.BUILTIN)
        try:
            registered = self._redis.hgetall(self.REDIS_KEY)
            if registered:
                result.update(registered)
        except Exception as e:
            logger.warning(f"Failed to list alias registry: {e}")
        return result


# Singleton accessor
_instance: Optional[AliasRegistry] = None


def get_alias_registry() -> AliasRegistry:
    """Get the global AliasRegistry singleton."""
    global _instance
    if _instance is None:
        _instance = AliasRegistry()
    return _instance

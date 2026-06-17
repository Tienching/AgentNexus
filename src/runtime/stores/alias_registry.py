# -*- coding: utf-8 -*-
"""Global alias -> provider registry.

Stores alias-to-provider mappings in SQLite so that users can specify
``-l claude-internal`` without needing ``-r claude`` every time.

Built-in aliases (e.g. ``claude-internal -> claude``) are always available
and do not require explicit registration.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from src.providers.registry import ALIASES, KNOWN_PROVIDERS
from .db import Database, get_db

logger = logging.getLogger(__name__)

# Known provider families — re-exported from providers.registry (single source).


class AliasRegistry:
    """Global alias -> provider mapping stored in SQLite."""

    REDIS_KEY = "alias_registry"

    # Built-in aliases — sourced from providers.registry.ALIASES (single source).
    BUILTIN: Dict[str, str] = dict(ALIASES)

    def __init__(self, db: Optional[Database] = None, redis_client=None):
        self._db = db or get_db()
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, alias: str, provider: str) -> bool:
        """Register an alias -> provider mapping.

        Returns True on success, False on failure.
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
            if self._redis is not None:
                self._redis.hset(self.REDIS_KEY, {alias: provider})
                logger.info(f"Registered alias: {alias} -> {provider}")
                return True
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO aliases (name, target) VALUES (?, ?)",
                    (alias, provider),
                )
            logger.info(f"Registered alias: {alias} -> {provider}")
            return True
        except Exception as e:
            logger.error(f"Failed to register alias: {e}")
            return False

    def resolve(self, alias: str) -> Optional[str]:
        """Resolve alias to its provider.

        Lookup order: SQLite registry -> BUILTIN map.
        Returns None if not found.
        """
        alias = (alias or "").strip().lower()
        if not alias:
            return None

        # 1. Check legacy Redis compatibility layer
        if self._redis is not None:
            try:
                value = self._redis.hget(self.REDIS_KEY, alias)
                if value:
                    return value
            except Exception as e:
                logger.warning(f"Failed to query alias registry: {e}")

        # 2. Check SQLite
        try:
            row = self._db.execute_fetchone(
                "SELECT target FROM aliases WHERE name = ?", (alias,)
            )
            if row and row.get("target"):
                return row["target"]
        except Exception as e:
            logger.warning(f"Failed to query alias registry: {e}")

        # 3. Fallback to built-in
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
            if self._redis is not None:
                return bool(self._redis.hdel(self.REDIS_KEY, alias))
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    "DELETE FROM aliases WHERE name = ?", (alias,)
                )
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to unregister alias: {e}")
            return False

    def list_all(self) -> Dict[str, str]:
        """Return all known aliases (built-in + registered).

        Registered entries override built-in entries with the same key.
        """
        result = dict(self.BUILTIN)
        try:
            if self._redis is not None:
                rows = self._redis.hgetall(self.REDIS_KEY) or {}
                for name, target in rows.items():
                    result[name] = target
                return result
            rows = self._db.execute_fetchall("SELECT name, target FROM aliases")
            for row in rows:
                result[row["name"]] = row["target"]
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

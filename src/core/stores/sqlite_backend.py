# -*- coding: utf-8 -*-
"""SQLite storage backend - local-first alternative to Redis.

This module provides a unified SQLite-backed storage interface that can serve
as a local-first alternative to Redis for key-value storage, caching, and
pub/sub patterns.

Usage:
    from src.core.stores.sqlite_backend import SQLiteBackend

    backend = SQLiteBackend()
    backend.set("key", {"data": "value"})
    value = backend.get("key")
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from src.runtime.stores.db import get_db


class SQLiteBackend:
    """SQLite-backed storage providing Redis-like interface.

    This is a local-first storage option that doesn't require Redis.
    It provides:
    - Key-value storage
    - List operations (push/pop)
    - Hash operations
    - TTL support
    - Simple pub/sub via polling
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize the SQLite backend.

        Args:
            db_path: Optional path to SQLite database file
        """
        self._db = get_db(db_path) if db_path else get_db()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create the storage tables."""
        # Key-value store
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                ttl REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        # List store
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS list_store (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                score REAL,
                created_at REAL NOT NULL
            )
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_list_key ON list_store (key, score)
        """)
        # Hash store
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS hash_store (
                hash_key TEXT NOT NULL,
                field TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (hash_key, field)
            )
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_hash_key ON hash_store (hash_key)
        """)

    def _is_expired(self, row: dict) -> bool:
        """Check if a TTL row has expired."""
        if row.get("ttl") is None:
            return False
        return time.time() > row["ttl"]

    # ---------------------------------------------------------------------------
    # Key-Value operations
    # ---------------------------------------------------------------------------

    def get(self, key: str) -> Optional[Any]:
        """Get a value by key.

        Args:
            key: The key to look up

        Returns:
            The value if found and not expired, None otherwise
        """
        row = self._db.execute_fetchone(
            "SELECT * FROM kv_store WHERE key = ?", (key,)
        )
        if row is None:
            return None
        if self._is_expired(row):
            self.delete(key)
            return None
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
    ) -> None:
        """Set a key-value pair.

        Args:
            key: The key
            value: The value (will be JSON-serialized)
            ttl: Optional time-to-live in seconds
        """
        now = time.time()
        expires_at = (now + ttl) if ttl else None

        try:
            value_json = json.dumps(value)
        except (TypeError, ValueError):
            value_json = str(value)

        self._db.execute(
            """INSERT OR REPLACE INTO kv_store (key, value, ttl, created_at, updated_at)
               VALUES (?, ?, ?, COALESCE((SELECT created_at FROM kv_store WHERE key = ?), ?), ?)""",
            (key, value_json, expires_at, key, now, now),
        )

    def delete(self, key: str) -> bool:
        """Delete a key.

        Args:
            key: The key to delete

        Returns:
            True if deleted, False if not found
        """
        result = self._db.execute(
            "DELETE FROM kv_store WHERE key = ?", (key,)
        )
        return result.rowcount > 0

    def exists(self, key: str) -> bool:
        """Check if a key exists.

        Args:
            key: The key to check

        Returns:
            True if exists and not expired, False otherwise
        """
        return self.get(key) is not None

    def keys(self, pattern: str = "*") -> List[str]:
        """Get all keys matching a pattern.

        Args:
            pattern: Glob-style pattern (e.g., "user:*")

        Returns:
            List of matching keys
        """
        # Convert glob to SQL LIKE pattern
        sql_pattern = pattern.replace("*", "%").replace("?", "_")
        rows = self._db.execute_fetchall(
            "SELECT key FROM kv_store WHERE key LIKE ?", (sql_pattern,)
        )
        keys = [row["key"] for row in rows]
        # Filter expired
        return [k for k in keys if self.exists(k)]

    # ---------------------------------------------------------------------------
    # List operations
    # ---------------------------------------------------------------------------

    def lpush(self, key: str, value: Any) -> int:
        """Push a value to the left of a list.

        Args:
            key: List key
            value: Value to push

        Returns:
            New list length
        """
        now = time.time()
        try:
            value_json = json.dumps(value)
        except (TypeError, ValueError):
            value_json = str(value)

        self._db.execute(
            "INSERT INTO list_store (key, value, score, created_at) VALUES (?, ?, ?, ?)",
            (key, value_json, now, now),
        )
        return self._list_len(key)

    def rpush(self, key: str, value: Any) -> int:
        """Push a value to the right of a list."""
        return self.lpush(key, value)  # Same for our purposes

    def lpop(self, key: str) -> Optional[Any]:
        """Pop a value from the left of a list."""
        row = self._db.execute_fetchone(
            "SELECT * FROM list_store WHERE key = ? ORDER BY score ASC LIMIT 1",
            (key,)
        )
        if row is None:
            return None
        self._db.execute("DELETE FROM list_store WHERE id = ?", (row["id"],))
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    def rpop(self, key: str) -> Optional[Any]:
        """Pop a value from the right of a list."""
        row = self._db.execute_fetchone(
            "SELECT * FROM list_store WHERE key = ? ORDER BY score DESC LIMIT 1",
            (key,)
        )
        if row is None:
            return None
        self._db.execute("DELETE FROM list_store WHERE id = ?", (row["id"],))
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    def lrange(self, key: str, start: int = 0, stop: int = -1) -> List[Any]:
        """Get a range of elements from a list.

        Args:
            key: List key
            start: Start index
            stop: Stop index (-1 for end)

        Returns:
            List of elements
        """
        if stop == -1:
            stop = 10000  # Large number
        rows = self._db.execute_fetchall(
            "SELECT * FROM list_store WHERE key = ? ORDER BY score ASC LIMIT ? OFFSET ?",
            (key, stop - start, start),
        )
        result = []
        for row in rows:
            try:
                result.append(json.loads(row["value"]))
            except (json.JSONDecodeError, TypeError):
                result.append(row["value"])
        return result

    def _list_len(self, key: str) -> int:
        """Get the length of a list."""
        row = self._db.execute_fetchone(
            "SELECT COUNT(*) as count FROM list_store WHERE key = ?", (key,)
        )
        return row["count"] if row else 0

    # ---------------------------------------------------------------------------
    # Hash operations
    # ---------------------------------------------------------------------------

    def hset(self, hash_key: str, field: str, value: Any) -> None:
        """Set a hash field.

        Args:
            hash_key: Hash key
            field: Field name
            value: Value to set
        """
        now = time.time()
        try:
            value_json = json.dumps(value)
        except (TypeError, ValueError):
            value_json = str(value)

        self._db.execute(
            """INSERT OR REPLACE INTO hash_store (hash_key, field, value, created_at, updated_at)
               VALUES (?, ?, ?, COALESCE((SELECT created_at FROM hash_store WHERE hash_key = ? AND field = ?), ?), ?)""",
            (hash_key, field, value_json, hash_key, field, now, now),
        )

    def hget(self, hash_key: str, field: str) -> Optional[Any]:
        """Get a hash field.

        Args:
            hash_key: Hash key
            field: Field name

        Returns:
            The value if found, None otherwise
        """
        row = self._db.execute_fetchone(
            "SELECT value FROM hash_store WHERE hash_key = ? AND field = ?",
            (hash_key, field),
        )
        if row is None:
            return None
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    def hgetall(self, hash_key: str) -> Dict[str, Any]:
        """Get all fields in a hash.

        Args:
            hash_key: Hash key

        Returns:
            Dict of field to value
        """
        rows = self._db.execute_fetchall(
            "SELECT field, value FROM hash_store WHERE hash_key = ?", (hash_key,)
        )
        result = {}
        for row in rows:
            try:
                result[row["field"]] = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                result[row["field"]] = row["value"]
        return result

    def hdel(self, hash_key: str, field: str) -> bool:
        """Delete a hash field.

        Args:
            hash_key: Hash key
            field: Field to delete

        Returns:
            True if deleted, False if not found
        """
        result = self._db.execute(
            "DELETE FROM hash_store WHERE hash_key = ? AND field = ?",
            (hash_key, field),
        )
        return result.rowcount > 0

    def hkeys(self, hash_key: str) -> List[str]:
        """Get all field names in a hash.

        Args:
            hash_key: Hash key

        Returns:
            List of field names
        """
        rows = self._db.execute_fetchall(
            "SELECT field FROM hash_store WHERE hash_key = ?", (hash_key,)
        )
        return [row["field"] for row in rows]

    # ---------------------------------------------------------------------------
    # Utility methods
    # ---------------------------------------------------------------------------

    def flush(self) -> None:
        """Delete all data (use with caution)."""
        self._db.execute("DELETE FROM kv_store")
        self._db.execute("DELETE FROM list_store")
        self._db.execute("DELETE FROM hash_store")

    def ttl(self, key: str) -> Optional[int]:
        """Get the TTL of a key in seconds.

        Returns:
            TTL in seconds, None if no TTL, -1 if expired/not found
        """
        row = self._db.execute_fetchone(
            "SELECT ttl FROM kv_store WHERE key = ?", (key,)
        )
        if row is None or row["ttl"] is None:
            return None
        remaining = row["ttl"] - time.time()
        return int(remaining) if remaining > 0 else -1


# Global default backend instance
_backend: Optional[SQLiteBackend] = None


def get_backend() -> SQLiteBackend:
    """Get the global SQLiteBackend instance."""
    global _backend
    if _backend is None:
        _backend = SQLiteBackend()
    return _backend

# -*- coding: utf-8 -*-
"""SQLite database connection management and migration framework.

Provides a singleton Database class with WAL mode, thread-safe connections,
and automatic schema migration — inspired by mission-control's better-sqlite3
architecture but adapted for Python's stdlib sqlite3.

Usage:
    from src.runtime.stores.db import get_db

    db = get_db()
    with db.conn() as conn:
        conn.execute("SELECT * FROM aliases")
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default database path — can be overridden via NEXUS_DB_PATH env var
_DEFAULT_DB_DIR = os.path.join(str(Path.home()), ".nexus")
_DEFAULT_DB_NAME = "nexus.db"


class Database:
    """SQLite database manager with WAL mode and automatic migrations.

    Thread safety: each thread gets its own connection via threading.local().
    WAL mode allows concurrent reads while a write is in progress.
    """

    _instance: Optional["Database"] = None
    _instances: dict[str, "Database"] = {}
    _lock = threading.Lock()

    @classmethod
    def _resolve_db_path(cls, db_path: Optional[str] = None) -> str:
        if db_path:
            return db_path
        env_path = os.environ.get("NEXUS_DB_PATH")
        if env_path:
            return env_path
        os.makedirs(_DEFAULT_DB_DIR, exist_ok=True)
        return os.path.join(_DEFAULT_DB_DIR, _DEFAULT_DB_NAME)

    def __new__(cls, db_path: Optional[str] = None, **kwargs) -> "Database":
        resolved_path = cls._resolve_db_path(db_path)
        with cls._lock:
            # Backward-compat: some tests still reset Database._instance directly.
            if cls._instance is None and cls._instances:
                stale_instances = list(cls._instances.values())
                cls._instances.clear()
            else:
                stale_instances = []
            instance = cls._instances.get(resolved_path)
            if instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instances[resolved_path] = instance
            cls._instance = instance
        for stale in stale_instances:
            try:
                stale.close()
            except Exception:
                pass
        return instance

    @classmethod
    def reset_instances(cls) -> None:
        """Drop cached DB instances so the next access gets a fresh DB."""
        with cls._lock:
            instances = list(cls._instances.values())
            cls._instances.clear()
            cls._instance = None
        for instance in instances:
            try:
                instance.close()
            except Exception:
                pass

    def __init__(
        self,
        db_path: Optional[str] = None,
    ):
        if self._initialized:
            return

        # Resolve database path
        self._db_path = self._resolve_db_path(db_path)

        self._local = threading.local()
        self._migration_lock = threading.Lock()
        self._migrations_verified = False
        self._migration_error: Optional[Exception] = None
        self._initialized = True

        logger.info(f"SQLite database initialized: {self._db_path}")

    @property
    def db_path(self) -> str:
        return self._db_path

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a thread-local SQLite connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            # Verify connection is still alive
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                try:
                    conn.close()
                except Exception:
                    pass

        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        self._local.conn = conn
        return conn

    @contextmanager
    def conn(self):
        """Context manager that yields a thread-local SQLite connection.

        The connection is reused within the same thread.  Callers should
        use ``db.conn()`` for read operations and ``db.transaction()``
        for writes that need atomicity.
        """
        connection = self._get_connection()
        try:
            yield connection
        except Exception:
            # Let the caller handle the exception; we just ensure cleanup
            raise

    @contextmanager
    def transaction(self):
        """Context manager for an atomic write transaction.

        Automatically commits on success, rolls back on exception.
        """
        connection = self._get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a single SQL statement on the thread-local connection."""
        with self.conn() as c:
            return c.execute(sql, params)

    def execute_fetchall(self, sql: str, params: tuple = ()) -> List[dict]:
        """Execute and return all rows as list of dicts."""
        with self.conn() as c:
            cursor = c.execute(sql, params)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def execute_fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """Execute and return one row as dict, or None."""
        with self.conn() as c:
            cursor = c.execute(sql, params)
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return dict(zip(columns, row))

    # ============ Migration Framework ============

    def _ensure_meta_table(self, conn: sqlite3.Connection):
        """Create the schema_version tracking table if not exists."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _schema_version (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at REAL NOT NULL
            )
        """)

    def _get_applied_versions(self, conn: sqlite3.Connection) -> List[int]:
        """Get list of already-applied migration versions."""
        self._ensure_meta_table(conn)
        cursor = conn.execute("SELECT version FROM _schema_version ORDER BY version")
        return [row[0] for row in cursor.fetchall()]

    def _mark_applied(self, conn: sqlite3.Connection, version: int, name: str):
        """Mark a migration as applied."""
        import time
        conn.execute(
            "INSERT INTO _schema_version (version, name, applied_at) VALUES (?, ?, ?)",
            (version, name, time.time()),
        )

    def run_migrations(self):
        """Run all pending schema migrations.

        Migrations are defined as module-level functions in the
        ``src/runtime/stores/migrations/`` package.  Each migration
        module must expose:
          - VERSION: int  (sequential, starting at 1)
          - NAME: str     (human-readable description)
          - up(conn): callable  (receives a sqlite3.Connection)
        """
        from .migrations import get_all_migrations

        with self.conn() as c:
            applied = self._get_applied_versions(c)
            migrations = get_all_migrations()

            pending = [m for m in migrations if m["version"] not in applied]
            if not pending:
                logger.debug("No pending SQLite migrations")
                return

            pending.sort(key=lambda m: m["version"])

            for m in pending:
                logger.info(f"Applying migration {m['version']}: {m['name']}")
                try:
                    c.execute("BEGIN IMMEDIATE")
                    m["up"](c)
                    self._mark_applied(c, m["version"], m["name"])
                    c.commit()
                    logger.info(f"Migration {m['version']} applied successfully")
                except Exception as e:
                    c.rollback()
                    logger.error(f"Migration {m['version']} failed: {e}")
                    raise RuntimeError(
                        f"Migration {m['version']} ({m['name']}) failed: {e}"
                    ) from e

    def ensure_migrated(self):
        """Verify schema migrations completed successfully for this process.

        Migration failures are cached and re-raised so callers never continue
        against a partially-upgraded schema after startup.
        """
        if self._migrations_verified:
            return

        if self._migration_error is not None:
            raise self._migration_error

        with self._migration_lock:
            if self._migrations_verified:
                return

            if self._migration_error is not None:
                raise self._migration_error

            try:
                self.run_migrations()
            except Exception as e:
                failure = RuntimeError(
                    f"Database migration check failed for {self._db_path}: {e}"
                )
                self._migration_error = failure
                logger.error(
                    "Database migration check failed for %s; refusing to continue startup",
                    self._db_path,
                    exc_info=True,
                )
                raise failure from e

            self._migrations_verified = True

    def close(self):
        """Close the thread-local connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None
        with self.__class__._lock:
            if self.__class__._instance is self:
                self.__class__._instance = None
            self.__class__._instances.pop(getattr(self, "_db_path", None), None)

    def __del__(self):
        self.close()


def get_db(db_path: Optional[str] = None) -> Database:
    """Get the global Database singleton.

    On first call, initializes the database and verifies pending migrations.
    Migration failures are surfaced to the caller so startup can fail fast.
    """
    db = Database(db_path=db_path)
    db.ensure_migrated()
    return db

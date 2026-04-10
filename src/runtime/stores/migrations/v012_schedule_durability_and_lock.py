# -*- coding: utf-8 -*-
"""Migration v012: Add schedule durability/jitter columns and scheduler lock table."""

from __future__ import annotations

import sqlite3

VERSION = 12
NAME = "schedule_durability_and_lock"


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def up(conn: sqlite3.Connection) -> None:
    if not _has_column(conn, "schedules", "durability_mode"):
        conn.execute("ALTER TABLE schedules ADD COLUMN durability_mode TEXT DEFAULT 'durable'")
    if not _has_column(conn, "schedules", "session_id"):
        conn.execute("ALTER TABLE schedules ADD COLUMN session_id TEXT")
    if not _has_column(conn, "schedules", "expires_at"):
        conn.execute("ALTER TABLE schedules ADD COLUMN expires_at REAL")
    if not _has_column(conn, "schedules", "jitter_seconds"):
        conn.execute("ALTER TABLE schedules ADD COLUMN jitter_seconds INTEGER DEFAULT 0")

    conn.execute("UPDATE schedules SET durability_mode = 'durable' WHERE durability_mode IS NULL OR durability_mode = ''")
    conn.execute("UPDATE schedules SET jitter_seconds = 0 WHERE jitter_seconds IS NULL")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_schedules_durability ON schedules(exec_user, durability_mode)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_schedules_expires_at ON schedules(exec_user, expires_at)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduler_locks (
            lock_name TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            heartbeat_at REAL NOT NULL,
            ttl_seconds INTEGER NOT NULL DEFAULT 90,
            updated_at REAL NOT NULL
        )
        """
    )

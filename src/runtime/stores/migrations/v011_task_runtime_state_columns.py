# -*- coding: utf-8 -*-
"""Migration v011: Add dual-layer runtime task state columns."""

from __future__ import annotations

import sqlite3

VERSION = 11
NAME = "task_runtime_state_columns"


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def up(conn: sqlite3.Connection) -> None:
    if not _has_column(conn, "tasks", "runtime_status"):
        conn.execute("ALTER TABLE tasks ADD COLUMN runtime_status TEXT DEFAULT 'queued'")
    if not _has_column(conn, "tasks", "runtime_orphaned"):
        conn.execute("ALTER TABLE tasks ADD COLUMN runtime_orphaned INTEGER DEFAULT 0")
    if not _has_column(conn, "tasks", "runtime_orphaned_at"):
        conn.execute("ALTER TABLE tasks ADD COLUMN runtime_orphaned_at REAL")
    if not _has_column(conn, "tasks", "runtime_last_heartbeat"):
        conn.execute("ALTER TABLE tasks ADD COLUMN runtime_last_heartbeat REAL")

    conn.execute("UPDATE tasks SET runtime_status = 'queued' WHERE runtime_status IS NULL OR runtime_status = ''")
    conn.execute("UPDATE tasks SET runtime_orphaned = 0 WHERE runtime_orphaned IS NULL")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_runtime_status ON tasks(exec_user, runtime_status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_runtime_orphaned ON tasks(exec_user, runtime_orphaned)"
    )

# -*- coding: utf-8 -*-
"""Migration v007: Task workflow columns and 7-column status normalization."""

from __future__ import annotations

import sqlite3

VERSION = 7
NAME = "task_workflow_columns"


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def up(conn: sqlite3.Connection) -> None:
    # New collaboration / kanban fields
    if not _has_column(conn, "tasks", "assigned_to"):
        conn.execute("ALTER TABLE tasks ADD COLUMN assigned_to TEXT")
    if not _has_column(conn, "tasks", "tags_json"):
        conn.execute("ALTER TABLE tasks ADD COLUMN tags_json TEXT")
    if not _has_column(conn, "tasks", "due_date"):
        conn.execute("ALTER TABLE tasks ADD COLUMN due_date REAL")
    if not _has_column(conn, "tasks", "ticket_ref"):
        conn.execute("ALTER TABLE tasks ADD COLUMN ticket_ref TEXT")

    # Normalize legacy statuses to the new 7-column workflow
    conn.execute("UPDATE tasks SET status = 'inbox' WHERE status IN ('todo', 'pending')")
    conn.execute("UPDATE tasks SET status = 'in_progress' WHERE status IN ('doing')")
    conn.execute("UPDATE tasks SET status = 'done' WHERE status IN ('completed')")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON tasks(exec_user, assigned_to)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(exec_user, due_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_ticket_ref ON tasks(exec_user, ticket_ref)")

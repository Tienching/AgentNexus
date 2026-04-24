# -*- coding: utf-8 -*-
"""Migration v016: task lifecycle guards.

Adds:
- unique partial index preventing duplicate active task session bindings
- trigger rejecting illegal status transitions at the SQLite layer
"""

import sqlite3

VERSION = 16
NAME = "task_lifecycle_guards"


_ALLOWED_TRANSITIONS = {
    "inbox": ("assigned", "in_progress", "cancelled", "archived"),
    "assigned": ("awaiting_owner", "in_progress", "cancelled", "archived"),
    "awaiting_owner": ("assigned", "in_progress", "cancelled", "archived"),
    "in_progress": ("inbox", "review", "awaiting_owner", "done", "failed", "cancelled"),
    "review": ("inbox", "quality_review", "in_progress", "done", "failed", "cancelled"),
    "quality_review": ("inbox", "done", "review", "in_progress", "failed", "cancelled"),
    "done": ("archived",),
    "failed": ("inbox", "assigned", "archived"),
    "cancelled": ("inbox", "archived"),
    "archived": ("inbox", "done"),
}

_ACTIVE_STATUSES = ("inbox", "assigned", "awaiting_owner", "in_progress", "review", "quality_review")


def _transition_sql() -> str:
    clauses = ["OLD.status = NEW.status"]
    for old_status, new_statuses in _ALLOWED_TRANSITIONS.items():
        allowed = ", ".join(repr(status) for status in new_statuses)
        clauses.append(f"(OLD.status = {old_status!r} AND NEW.status IN ({allowed}))")
    return " OR ".join(clauses)


def up(conn: sqlite3.Connection) -> None:
    duplicate_rows = conn.execute(
        f"""
        SELECT exec_user, session_id, GROUP_CONCAT(id) AS ids
        FROM tasks
        WHERE session_id IS NOT NULL
          AND TRIM(session_id) != ''
          AND status IN ({', '.join(repr(s) for s in _ACTIVE_STATUSES)})
          AND deleted_at IS NULL
        GROUP BY exec_user, session_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for exec_user, session_id, ids_csv in duplicate_rows:
        ids = [part for part in str(ids_csv or '').split(',') if part]
        keep_id = ids[-1]
        for task_id in ids[:-1]:
            conn.execute(
                "UPDATE tasks SET session_id = session_id || ':dedup:' || id WHERE exec_user = ? AND id = ?",
                (exec_user, task_id),
            )
    conn.execute("DROP INDEX IF EXISTS ux_tasks_active_session")
    conn.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_tasks_active_session
        ON tasks(exec_user, session_id)
        WHERE session_id IS NOT NULL
          AND TRIM(session_id) != ''
          AND status IN ({', '.join(repr(s) for s in _ACTIVE_STATUSES)})
          AND deleted_at IS NULL
        """
    )
    conn.execute("DROP TRIGGER IF EXISTS invalid_task_status_transition")
    conn.execute(
        f"""
        CREATE TRIGGER invalid_task_status_transition
        BEFORE UPDATE OF status ON tasks
        FOR EACH ROW
        WHEN NOT ({_transition_sql()})
        BEGIN
            SELECT RAISE(ABORT, 'invalid_task_status_transition');
        END;
        """
    )


def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TRIGGER IF EXISTS invalid_task_status_transition")
    conn.execute("DROP INDEX IF EXISTS ux_tasks_active_session")

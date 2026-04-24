# -*- coding: utf-8 -*-
"""Migration v013: Migrate task statuses to new unified model.

Old statuses → New statuses:
  todo          → inbox
  doing         → in_progress
  assigned      → in_progress
  awaiting_owner → in_progress
  review        → in_review
  quality_review → in_review
  cancelled     → archived
"""

import sqlite3

VERSION = 13
NAME = "migrate_task_statuses"


def up(conn: sqlite3.Connection) -> None:
    # Migrate status values
    status_mappings = [
        ("todo", "inbox"),
        ("doing", "in_progress"),
        ("assigned", "in_progress"),
        ("awaiting_owner", "in_progress"),
        ("review", "in_review"),
        ("quality_review", "in_review"),
        ("cancelled", "archived"),
    ]
    for old_status, new_status in status_mappings:
        conn.execute(
            "UPDATE tasks SET status = ? WHERE status = ?",
            (new_status, old_status),
        )
        # Also migrate the legacy core_tasks table when it exists.
        core_tasks_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'core_tasks'"
        ).fetchone()
        if core_tasks_exists:
            conn.execute(
                "UPDATE core_tasks SET status = ? WHERE status = ?",
                (new_status, old_status),
            )


def down(conn: sqlite3.Connection) -> None:
    # Reverse migration (best-effort)
    reverse_mappings = [
        ("inbox", "todo"),
        ("in_progress", "doing"),
        ("in_review", "review"),
    ]
    for new_status, old_status in reverse_mappings:
        conn.execute(
            "UPDATE tasks SET status = ? WHERE status = ?",
            (old_status, new_status),
        )
        core_tasks_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'core_tasks'"
        ).fetchone()
        if core_tasks_exists:
            conn.execute(
                "UPDATE core_tasks SET status = ? WHERE status = ?",
                (old_status, new_status),
            )

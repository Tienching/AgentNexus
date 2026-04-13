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
        # Also try core_tasks table (alternative schema)
        try:
            conn.execute(
                "UPDATE core_tasks SET status = ? WHERE status = ?",
                (new_status, old_status),
            )
        except Exception:
            pass

    conn.commit()


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
        try:
            conn.execute(
                "UPDATE core_tasks SET status = ? WHERE status = ?",
                (old_status, new_status),
            )
        except Exception:
            pass

    conn.commit()

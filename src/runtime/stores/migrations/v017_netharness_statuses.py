# -*- coding: utf-8 -*-
"""Migration v017: netharness 7-status model.

Migrates task statuses from the old 10-value model
(inbox/assigned/awaiting_owner/in_progress/review/quality_review/done/failed/cancelled/archived)
to the netharness-aligned 7-value model
(pending/running/in_review/completed/failed/cancelled/archived).

Also adds review_state column for the netharness review pattern.
"""

import sqlite3

VERSION = 17
NAME = "netharness_statuses"

# Old → New status mapping
_STATUS_MIGRATION = {
    "inbox": "pending",
    "assigned": "pending",
    "awaiting_owner": "pending",
    "todo": "pending",
    "in_progress": "running",
    "doing": "running",
    "review": "in_review",
    "quality_review": "in_review",
    "done": "completed",
    # These pass through unchanged
    "pending": "pending",
    "running": "running",
    "in_review": "in_review",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
    "archived": "archived",
}

# New transition rules (netharness-aligned)
_ALLOWED_TRANSITIONS = {
    "pending": ("running", "cancelled", "archived"),
    "running": ("pending", "in_review", "completed", "failed", "cancelled"),
    "in_review": ("running", "completed", "failed", "cancelled"),
    "completed": ("archived",),
    "failed": ("pending", "archived"),
    "cancelled": ("pending", "archived"),
    "archived": ("pending", "completed"),
}

_ACTIVE_STATUSES = ("pending", "running", "in_review")


def _transition_sql() -> str:
    clauses = ["OLD.status = NEW.status"]
    for old_status, new_statuses in _ALLOWED_TRANSITIONS.items():
        allowed = ", ".join(repr(status) for status in new_statuses)
        clauses.append(f"(OLD.status = {old_status!r} AND NEW.status IN ({allowed}))")
    return " OR ".join(clauses)


def up(conn: sqlite3.Connection) -> None:
    # 1. Drop the old trigger and index (they hardcode old status strings)
    conn.execute("DROP TRIGGER IF EXISTS invalid_task_status_transition")
    conn.execute("DROP INDEX IF EXISTS ux_tasks_active_session")

    # 2. Migrate existing status values
    for old_status, new_status in _STATUS_MIGRATION.items():
        if old_status != new_status:
            conn.execute(
                "UPDATE tasks SET status = ? WHERE status = ?",
                (new_status, old_status),
            )

    # 3. Add review_state column if not exists
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN review_state TEXT DEFAULT 'none'")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # 4. Migrate quality_review tasks to have review_state='requested'
    conn.execute(
        "UPDATE tasks SET review_state = 'requested' WHERE status = 'in_review' AND review_state = 'none'"
    )

    # 5. Deduplicate rows that now collide under the new active-session predicate.
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
        ids = [part for part in str(ids_csv or "").split(",") if part]
        for task_id in ids[:-1]:
            conn.execute(
                "UPDATE tasks SET session_id = session_id || ':dedup:' || id WHERE exec_user = ? AND id = ?",
                (exec_user, task_id),
            )

    # 6. Recreate the partial unique index with new active statuses
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

    # 7. Recreate the trigger with new transition rules
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
    try:
        conn.execute("ALTER TABLE tasks DROP COLUMN review_state")
    except sqlite3.OperationalError:
        pass

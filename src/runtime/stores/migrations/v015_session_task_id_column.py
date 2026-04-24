# -*- coding: utf-8 -*-
"""Migration v015: Add task_id to sessions."""

from __future__ import annotations

import sqlite3

VERSION = 15
NAME = "session_task_id_column"


def up(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE sessions ADD COLUMN task_id TEXT")

    # Backfill from execution bindings when available so task/session joins
    # work immediately after the migration.
    binding_table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'execution_bindings'"
    ).fetchone()
    if not binding_table_exists:
        return

    conn.execute(
        """
        UPDATE sessions
        SET task_id = (
            SELECT eb.task_id
            FROM execution_bindings eb
            WHERE eb.session_id = sessions.id
              AND eb.task_id IS NOT NULL
              AND eb.task_id != ''
            LIMIT 1
        )
        WHERE task_id IS NULL OR task_id = ''
        """
    )


def down(conn: sqlite3.Connection) -> None:
    # SQLite cannot drop columns in older versions without table rebuilds.
    pass

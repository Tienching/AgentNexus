# -*- coding: utf-8 -*-
"""Migration v014: Execution binding control-plane table."""

from __future__ import annotations

import sqlite3

VERSION = 14
NAME = "execution_bindings"


def up(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS execution_bindings (
            session_id        TEXT PRIMARY KEY,
            cli_session_id    TEXT,
            session_kind      TEXT,
            provider          TEXT,
            alias             TEXT,
            exec_user         TEXT,
            work_dir          TEXT,
            source_type       TEXT,
            source_session_id TEXT,
            task_id           TEXT,
            metadata_json     TEXT,
            created_at        REAL,
            updated_at        REAL,
            expires_at        REAL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_execution_bindings_cli_session
        ON execution_bindings(cli_session_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_execution_bindings_exec_user
        ON execution_bindings(exec_user)
    """)

    # Backfill from the existing sessions table so old chat/task sessions can
    # still be resumed immediately after the migration. If the sessions table
    # is malformed, fail the migration rather than silently producing a partial
    # control-plane index.
    sessions_table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sessions'"
    ).fetchone()
    if not sessions_table_exists:
        return

    session_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
    }
    if "id" not in session_columns:
        raise sqlite3.OperationalError("sessions table is missing required id column")

    select_parts = []
    ordered_columns = [
        "id",
        "cli_session_id",
        "claude_session_id",
        "provider",
        "alias",
        "session_exec_user",
        "username",
        "exec_dir",
        "exec_dir_override",
        "inherited_from",
        "created_at",
        "updated_at",
        "expires_at",
    ]
    for column in ordered_columns:
        if column in session_columns:
            select_parts.append(column)
        else:
            select_parts.append(f"NULL AS {column}")

    rows = conn.execute(
        f"SELECT {', '.join(select_parts)} FROM sessions"
    ).fetchall()

    for row in rows:
        session_id = row[0]
        cli_session_id = row[1] or row[2] or ""
        provider = row[3] or ""
        alias = row[4] or ""
        exec_user = row[5] or row[6] or ""
        work_dir = row[7] or row[8] or ""
        inherited_from = row[9] or ""
        created_at = row[10] or 0.0
        updated_at = row[11] or created_at or 0.0
        expires_at = row[12]

        session_kind = "task" if str(session_id).startswith("task_") else "chat"
        source_type = None
        source_session_id = None
        if inherited_from.startswith("history:"):
            session_kind = "chat"
            source_type = "history"
            parts = inherited_from.split(":", 2)
            if len(parts) >= 3:
                source_session_id = parts[2]

        conn.execute(
            """
            INSERT OR REPLACE INTO execution_bindings (
                session_id, cli_session_id, session_kind, provider, alias,
                exec_user, work_dir, source_type, source_session_id, task_id,
                metadata_json, created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                cli_session_id,
                session_kind,
                provider,
                alias,
                exec_user,
                work_dir,
                source_type or "",
                source_session_id or "",
                session_id.split("task_", 1)[1] if str(session_id).startswith("task_") else "",
                "{}",
                created_at if isinstance(created_at, (int, float)) else 0.0,
                updated_at if isinstance(updated_at, (int, float)) else 0.0,
                expires_at,
            ),
        )


def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS execution_bindings")

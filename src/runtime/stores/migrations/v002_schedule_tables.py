# -*- coding: utf-8 -*-
"""Migration v002: Schedule tables.

Replaces the Redis structure:
  schedule:{exec_user}:{id}                → schedules row
  schedules:{exec_user}:all                → index via exec_user column
  schedules:{exec_user}:by_status:{status} → index via status column
  schedules:{exec_user}:active_next_runs   → partial index
  schedule:{exec_user}:{id}:history        → schedule_history rows
"""

import sqlite3

VERSION = 2
NAME = "schedule_tables"


def up(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id              TEXT NOT NULL,
            exec_user       TEXT NOT NULL,
            name            TEXT,
            description     TEXT,
            cron_expression TEXT,
            run_at          REAL,
            timezone_str    TEXT DEFAULT 'UTC',
            status          TEXT DEFAULT 'active',
            schedule_kind   TEXT DEFAULT 'task',
            evolution_phase TEXT,
            provider        TEXT DEFAULT 'claude',
            alias           TEXT,
            model           TEXT,
            workspace       TEXT,
            project_id      TEXT,
            project_name    TEXT,
            context_json    TEXT,
            max_runs        INTEGER,
            run_count       INTEGER DEFAULT 0,
            next_run_at     REAL,
            last_run_at     REAL,
            last_task_id    TEXT,
            created_at      REAL NOT NULL,
            updated_at      REAL,
            paused_at       REAL,
            cancelled_at    REAL,
            created_by      TEXT,
            PRIMARY KEY (exec_user, id)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_schedules_status
        ON schedules(exec_user, status)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_schedules_next_run
        ON schedules(exec_user, next_run_at)
        WHERE status = 'active' AND next_run_at IS NOT NULL
    """)

    # ── Schedule run history ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schedule_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id  TEXT NOT NULL,
            exec_user    TEXT NOT NULL,
            task_id      TEXT NOT NULL,
            run_at       REAL,
            FOREIGN KEY (exec_user, schedule_id) REFERENCES schedules(exec_user, id)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_schedule_history_sid
        ON schedule_history(exec_user, schedule_id)
    """)

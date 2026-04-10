# -*- coding: utf-8 -*-
"""Migration v005: Agent Run tables.

Replaces the Redis structure:
  run:{exec_user}:{run_id}         → agent_runs row
  runs:{exec_user}:all             → index via started_at
  runs:{exec_user}:by_agent:{aid}  → index via agent_id
  runs:{exec_user}:by_status:{s}   → index via status
  runs:{exec_user}:by_task:{tid}   → index via task_id
"""

import sqlite3

VERSION = 5
NAME = "run_tables"


def up(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            id               TEXT NOT NULL,
            exec_user        TEXT NOT NULL,
            agent_id         TEXT NOT NULL DEFAULT '',
            agent_name       TEXT,
            model            TEXT,
            provider         TEXT,
            runtime          TEXT DEFAULT 'nexus',
            runtime_version  TEXT,
            trigger          TEXT,
            parent_run_id    TEXT,
            task_id          TEXT,
            status           TEXT DEFAULT 'pending',
            outcome          TEXT,
            started_at       TEXT,
            ended_at         TEXT,
            duration_ms      INTEGER,
            steps_json       TEXT,
            tools_available_json TEXT,
            cost_json        TEXT,
            provenance_json  TEXT,
            eval_json        TEXT,
            error            TEXT,
            git_branch       TEXT,
            git_commit       TEXT,
            workspace_id     TEXT,
            tags_json        TEXT,
            metadata_json    TEXT,
            PRIMARY KEY (exec_user, id)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_runs_agent
        ON agent_runs(exec_user, agent_id, started_at DESC)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_runs_status
        ON agent_runs(exec_user, status, started_at DESC)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_runs_task
        ON agent_runs(exec_user, task_id, started_at DESC)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_runs_started
        ON agent_runs(exec_user, started_at DESC)
    """)

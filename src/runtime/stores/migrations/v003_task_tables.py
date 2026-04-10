# -*- coding: utf-8 -*-
"""Migration v003: Task tables.

Replaces the Redis structure:
  task:{exec_user}:{id}                    → tasks row (data_json for full task blob)
  tasks:{exec_user}:all                    → ordered by created_at
  tasks:{exec_user}:by_status:{status}     → index via status column
  tasks:{exec_user}:by_project:{pid}       → index via project_id column
  tasks:{exec_user}:by_workspace:{hash}    → index via workspace_hash column
  queue:{exec_user}:{hash}:todo            → managed via status+priority+created_at
  executing:{exec_user}:{hash}             → managed via status='doing'
  tasks:{exec_user}:by_session:{sid}       → index via session_id column
"""

import sqlite3

VERSION = 3
NAME = "task_tables"


def up(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id              TEXT NOT NULL,
            exec_user       TEXT NOT NULL,
            description     TEXT,
            priority        TEXT DEFAULT 'thought',
            status          TEXT DEFAULT 'todo',
            project_id      TEXT,
            project_name    TEXT,
            workspace       TEXT,
            workspace_hash  TEXT,
            session_id      TEXT,
            source_session_id TEXT,
            provider        TEXT DEFAULT 'claude',
            alias           TEXT,
            model           TEXT,
            context_json    TEXT,
            attempt_count   INTEGER DEFAULT 0,
            error_message   TEXT,
            outcome         TEXT,
            resolution      TEXT,
            feedback_rating INTEGER,
            feedback_notes  TEXT,
            response_url    TEXT,
            callback_msg_id TEXT,
            callback_user   TEXT,
            notification_sink_type  TEXT,
            notification_channel   TEXT,
            notification_chat_id   TEXT,
            notification_message_id TEXT,
            loop_enabled           INTEGER DEFAULT 0,
            loop_max_iterations    INTEGER DEFAULT 1,
            loop_iteration         INTEGER DEFAULT 0,
            loop_keywords_json     TEXT,
            loop_keyword_found     INTEGER DEFAULT 0,
            schedule_id    TEXT,
            created_at     REAL NOT NULL,
            started_at     REAL,
            completed_at   REAL,
            archived_at    REAL,
            deleted_at     REAL,
            PRIMARY KEY (exec_user, id)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_status
        ON tasks(exec_user, status)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_project
        ON tasks(exec_user, project_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_workspace
        ON tasks(exec_user, workspace_hash)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_session
        ON tasks(exec_user, session_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_queue
        ON tasks(exec_user, workspace_hash, status, priority, created_at)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_created
        ON tasks(exec_user, created_at DESC)
    """)

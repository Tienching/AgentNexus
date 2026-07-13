# -*- coding: utf-8 -*-
"""Migration v021: Persist task comments in SQLite."""

from __future__ import annotations

VERSION = 21
NAME = "add_task_comments_table"


def up(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_comments (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            exec_user TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT 'user',
            content TEXT NOT NULL,
            mentions_json TEXT NOT NULL DEFAULT '[]',
            parent_id TEXT,
            created_at REAL NOT NULL,
            FOREIGN KEY (exec_user, task_id) REFERENCES tasks(exec_user, id) ON DELETE CASCADE,
            FOREIGN KEY (parent_id) REFERENCES task_comments(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_comments_task
        ON task_comments (exec_user, task_id, created_at, id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_comments_parent
        ON task_comments (parent_id)
        """
    )

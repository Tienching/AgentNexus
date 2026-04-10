# -*- coding: utf-8 -*-
"""Migration v010: Add quality_reviews table for Aegis quality gates.

Version: 10
Name: add_quality_reviews_table
"""

from __future__ import annotations

VERSION = 10
NAME = "add_quality_reviews_table"


def up(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quality_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            status TEXT NOT NULL,
            notes TEXT,
            workspace_id INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_quality_reviews_task
        ON quality_reviews (task_id, created_at DESC)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_quality_reviews_workspace
        ON quality_reviews (workspace_id, created_at DESC)
        """
    )

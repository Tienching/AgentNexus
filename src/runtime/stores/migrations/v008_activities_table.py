# -*- coding: utf-8 -*-
"""Migration v008: Add activities table for activity stream system.

Adds the activities table for centralized activity logging, replacing
scattered event logging across the application.

Version: 8
Name: add_activities_table
"""

from __future__ import annotations

VERSION = 8
NAME = "add_activities_table"


def up(conn) -> None:
    """Create the activities table and indexes."""
    # Main activities table - mirrors Mission Control's activities table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            actor TEXT NOT NULL,
            description TEXT NOT NULL,
            data TEXT,
            created_at REAL NOT NULL DEFAULT (unixepoch())
        )
    """)

    # Indexes for common query patterns
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_activities_entity
        ON activities (entity_type, entity_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_activities_created_at
        ON activities (created_at DESC)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_activities_type
        ON activities (type)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_activities_actor
        ON activities (actor)
    """)

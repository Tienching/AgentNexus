# -*- coding: utf-8 -*-
"""Migration v006: Feature Flag tables.

Stores feature flag overrides in SQLite so they persist across restarts.
Complements the env-var and config-file layers of the flag resolution chain.
"""

import sqlite3

VERSION = 6
NAME = "feature_flag_tables"


def up(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feature_flags (
            name        TEXT PRIMARY KEY,
            value_json  TEXT NOT NULL DEFAULT '"true"',
            updated_by  TEXT NOT NULL DEFAULT '',
            updated_at  REAL NOT NULL DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_feature_flags_name
        ON feature_flags(name)
    """)

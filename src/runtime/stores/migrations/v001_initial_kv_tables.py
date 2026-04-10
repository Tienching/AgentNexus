# -*- coding: utf-8 -*-
"""Migration v001: Initial KV tables (aliases, user_config, concurrency_config).

These are the simplest stores — pure key-value lookups that map 1:1
from Redis hash/string structures to SQLite tables.
"""

import sqlite3

VERSION = 1
NAME = "initial_kv_tables"


def up(conn: sqlite3.Connection) -> None:
    # ── aliases (replaces Redis hash alias:registry) ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS aliases (
            name  TEXT PRIMARY KEY,
            target TEXT NOT NULL
        )
    """)

    # ── user_config (replaces Redis hash user:{id}:config) ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_config (
            user_id TEXT NOT NULL,
            key     TEXT NOT NULL,
            value   TEXT NOT NULL,
            PRIMARY KEY (user_id, key)
        )
    """)

    # ── concurrency_config (replaces Redis strings concurrency:provider:{name} + concurrency:global) ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concurrency_config (
            scope         TEXT PRIMARY KEY,
            max_concurrent INTEGER NOT NULL
        )
    """)

    # ── history_hidden (replaces Redis set history:hidden) ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history_hidden (
            session_id TEXT PRIMARY KEY
        )
    """)

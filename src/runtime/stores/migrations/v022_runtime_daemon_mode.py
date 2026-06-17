# -*- coding: utf-8 -*-
"""Migration v022: Add runtime_mode column to runtime_daemons.

Distinguishes runtimes the server hosts locally ('local') from runtimes a
relay node forwards from a downstream daemon ('relay'). This is the
server/relay mode distinction (Phase 5); multica has no equivalent.

Version: 22
Name: runtime_daemon_mode
"""

from __future__ import annotations

VERSION = 22
NAME = "runtime_daemon_mode"


def up(conn) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runtime_daemons)").fetchall()}
    if "runtime_mode" not in cols:
        conn.execute(
            "ALTER TABLE runtime_daemons ADD COLUMN runtime_mode TEXT NOT NULL DEFAULT 'local'"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_daemons_mode "
        "ON runtime_daemons(runtime_mode, updated_at DESC)"
    )

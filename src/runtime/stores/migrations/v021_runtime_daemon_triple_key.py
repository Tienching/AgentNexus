# -*- coding: utf-8 -*-
"""Migration v021: Rebuild runtime_daemons with a (workspace, daemon_id, provider) key.

The runtime_daemons table was originally keyed by daemon_id alone (one runtime
row per host). The daemon-platform refactor requires one row per
(workspace, daemon_id, provider) so a single host exposing multiple CLI
providers (e.g. claude + hermes) registers as multiple aggregated runtimes,
matching multica's model. This migration rebuilds the table in place: existing
rows are preserved with workspace='default' and provider derived from the
runtime_id suffix when possible.

Version: 21
Name: runtime_daemon_triple_key
"""

from __future__ import annotations

import json
import sqlite3

VERSION = 21
NAME = "runtime_daemon_triple_key"


def _provider_from_runtime_id(runtime_id: str) -> str:
    """Best-effort: a runtime_id like 'daemon-abc/claude' -> 'claude'."""
    if not runtime_id:
        return "unknown"
    if "/" in runtime_id:
        return runtime_id.rsplit("/", 1)[-1] or "unknown"
    return "unknown"


def up(conn) -> None:
    """Rebuild runtime_daemons with the triple-key primary key."""
    cur = conn.cursor()

    # Detect existing table shape (avoid touching if already migrated).
    cols = {row[1] for row in cur.execute("PRAGMA table_info(runtime_daemons)").fetchall()}
    if "workspace" in cols and "provider" in cols:
        # Already migrated; just ensure the composite index exists.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runtime_daemons_triple "
            "ON runtime_daemons(workspace, daemon_id, provider)"
        )
        return

    # Back up existing rows.
    existing = []
    if "runtime_daemons" in {
        row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }:
        existing = cur.execute(
            "SELECT daemon_id, runtime_id, device_name, cli_version, provider_version, "
            "status, health_endpoint, pending_operations, last_heartbeat, last_health_check, "
            "metadata_json, created_at, updated_at FROM runtime_daemons"
        ).fetchall()

    conn.execute("DROP TABLE IF EXISTS runtime_daemons")
    conn.execute(
        """
        CREATE TABLE runtime_daemons (
            workspace TEXT NOT NULL DEFAULT 'default',
            daemon_id TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'unknown',
            runtime_id TEXT NOT NULL,
            device_name TEXT NOT NULL DEFAULT '',
            cli_version TEXT,
            provider_version TEXT,
            status TEXT NOT NULL DEFAULT 'idle',
            health_endpoint TEXT,
            pending_operations INTEGER NOT NULL DEFAULT 0,
            last_heartbeat REAL NOT NULL,
            last_health_check REAL NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (workspace, daemon_id, provider)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_daemons_triple "
        "ON runtime_daemons(workspace, daemon_id, provider)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_daemons_runtime "
        "ON runtime_daemons(runtime_id, updated_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_daemons_status "
        "ON runtime_daemons(status, updated_at DESC)"
    )

    # Restore rows, deriving workspace/provider where possible.
    for row in existing:
        (
            daemon_id, runtime_id, device_name, cli_version, provider_version,
            status, health_endpoint, pending_operations, last_heartbeat,
            last_health_check, metadata_json, created_at, updated_at,
        ) = row
        try:
            meta = json.loads(metadata_json) if metadata_json else {}
        except Exception:
            meta = {}
        workspace = str(meta.get("workspace", "default")) or "default"
        provider = str(meta.get("provider", "")) or _provider_from_runtime_id(runtime_id)
        conn.execute(
            """
            INSERT OR IGNORE INTO runtime_daemons (
                workspace, daemon_id, provider, runtime_id, device_name, cli_version,
                provider_version, status, health_endpoint, pending_operations,
                last_heartbeat, last_health_check, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace, daemon_id, provider, runtime_id, device_name, cli_version,
                provider_version, status or "idle", health_endpoint,
                int(pending_operations or 0), last_heartbeat, last_health_check,
                metadata_json or "{}", created_at, updated_at,
            ),
        )

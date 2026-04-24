# -*- coding: utf-8 -*-
"""Migration v019: control-plane group/workspace normalization.

Adds explicit, normalized group/workspace identifiers to membership rows so
group/workspace-oriented queries can avoid reparsing ``scope_type``/``scope_id``
pairs and introduces a dedicated join-request table for pending access requests.
"""

from __future__ import annotations

import sqlite3

VERSION = 19
NAME = "control_plane_group_workspace"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
    )


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _ensure_control_plane_tables(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "control_plane_tenants"):
        conn.execute("""
            CREATE TABLE control_plane_tenants (
                tenant_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)

    if not _table_exists(conn, "control_plane_workspaces"):
        conn.execute("""
            CREATE TABLE control_plane_workspaces (
                workspace_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                root_path TEXT,
                default_branch TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY(tenant_id) REFERENCES control_plane_tenants(tenant_id) ON DELETE CASCADE
            )
        """)

    if not _table_exists(conn, "control_plane_memberships"):
        conn.execute("""
            CREATE TABLE control_plane_memberships (
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                scopes_json TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (scope_type, scope_id, username)
            )
        """)


def _ensure_membership_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_control_plane_memberships_scope ON control_plane_memberships(scope_type, scope_id, username)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_control_plane_memberships_user ON control_plane_memberships(username, updated_at DESC)"
    )


def up(conn: sqlite3.Connection) -> None:
    _ensure_control_plane_tables(conn)
    _ensure_membership_indexes(conn)

    membership_columns = _column_names(conn, "control_plane_memberships")

    if "group_id" not in membership_columns:
        conn.execute("ALTER TABLE control_plane_memberships ADD COLUMN group_id TEXT")
    if "workspace_id" not in membership_columns:
        conn.execute("ALTER TABLE control_plane_memberships ADD COLUMN workspace_id TEXT")

    # Normalize historical records so downstream code can rely on explicit group /
    # workspace identifiers without reparsing scope identifiers.
    conn.execute(
        """
        UPDATE control_plane_memberships
           SET group_id = CASE
                WHEN lower(trim(scope_type)) = 'tenant' OR lower(trim(scope_type)) = 'group'
                THEN lower(trim(scope_id))
                ELSE group_id
            END
         WHERE lower(trim(scope_type)) IN ('tenant', 'group')
        """
    )
    conn.execute(
        """
        UPDATE control_plane_memberships
           SET workspace_id = CASE
                WHEN lower(trim(scope_type)) = 'workspace'
                THEN lower(trim(scope_id))
                ELSE workspace_id
            END
         WHERE lower(trim(scope_type)) = 'workspace'
        """
    )

    # Ensure scope columns are normalized for legacy mixed-case records.
    conn.execute(
        "UPDATE control_plane_memberships SET scope_type = lower(trim(scope_type)) WHERE scope_type != lower(trim(scope_type))"
    )
    conn.execute(
        "UPDATE control_plane_memberships SET scope_id = trim(scope_id) WHERE scope_id != trim(scope_id)"
    )
    conn.execute(
        "UPDATE control_plane_memberships SET username = trim(username) WHERE username != trim(username)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS control_plane_group_workspace_join_requests (
            request_id TEXT PRIMARY KEY,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            group_id TEXT,
            workspace_id TEXT,
            username TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            scopes_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'pending',
            note TEXT NOT NULL DEFAULT '',
            reviewer TEXT,
            reviewed_at REAL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY(group_id) REFERENCES control_plane_tenants(tenant_id) ON DELETE CASCADE,
            FOREIGN KEY(workspace_id) REFERENCES control_plane_workspaces(workspace_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_control_plane_group_workspace_join_requests_scope
        ON control_plane_group_workspace_join_requests(scope_type, scope_id, username)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_control_plane_group_workspace_join_requests_user
        ON control_plane_group_workspace_join_requests(username, status, updated_at DESC)
        """
    )


def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_control_plane_group_workspace_join_requests_user")
    conn.execute("DROP INDEX IF EXISTS idx_control_plane_group_workspace_join_requests_scope")
    conn.execute("DROP TABLE IF EXISTS control_plane_group_workspace_join_requests")
    # Explicitly keep original tables/columns to avoid destructive rollback behavior.
    # SQLite rollback for dropped columns is unsafe on older runtimes, so no-op columns.

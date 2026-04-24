# -*- coding: utf-8 -*-
"""Migration v020: control-plane group/workspace maintenance.

Fixes follow-up consistency issues in environments that have already applied
v019 (with or without manual schema drift):

- add missing ``review_note`` on join requests;
- backfill membership ``group_id`` / ``workspace_id`` columns when missing;
- enforce at most one pending join request per workspace + user.
"""

from __future__ import annotations

import sqlite3

VERSION = 20
NAME = "control_plane_group_workspace_maintenance"


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


def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,),
        ).fetchone()
    )


def up(conn: sqlite3.Connection) -> None:
    # Ensure partial schema for environments that applied older v019 variants.
    membership_columns = _column_names(conn, "control_plane_memberships")
    if "group_id" not in membership_columns:
        conn.execute("ALTER TABLE control_plane_memberships ADD COLUMN group_id TEXT")
    if "workspace_id" not in membership_columns:
        conn.execute("ALTER TABLE control_plane_memberships ADD COLUMN workspace_id TEXT")
    if not membership_columns.issuperset({"group_id", "workspace_id"}):
        membership_columns = _column_names(conn, "control_plane_memberships")

    join_request_columns = _column_names(conn, "control_plane_group_workspace_join_requests")
    if "review_note" not in join_request_columns:
        conn.execute("ALTER TABLE control_plane_group_workspace_join_requests ADD COLUMN review_note TEXT")

    # Backfill normalized columns for existing memberships.
    if "group_id" in membership_columns:
        conn.execute(
            "UPDATE control_plane_memberships "
            "SET group_id = trim(scope_id) "
            "WHERE group_id IS NULL "
            "  AND lower(trim(scope_type)) = 'tenant'"
        )
    if "workspace_id" in membership_columns and "group_id" in membership_columns:
        conn.execute(
            """
            UPDATE control_plane_memberships
               SET workspace_id = trim(scope_id),
                   group_id = (
                       SELECT tenant_id
                       FROM control_plane_workspaces w
                       WHERE trim(w.workspace_id) = trim(scope_id)
                   )
            WHERE lower(trim(scope_type)) = 'workspace'
              AND workspace_id IS NULL
            """
        )

    # Ensure at most one pending request per workspace-user pair.
    if not _index_exists(
        conn, "uq_control_plane_group_workspace_join_requests_workspace_user_pending"
    ):
        conn.execute(
            """
            CREATE UNIQUE INDEX uq_control_plane_group_workspace_join_requests_workspace_user_pending
            ON control_plane_group_workspace_join_requests (workspace_id, username)
            WHERE status = 'pending'
            """
        )


def down(conn: sqlite3.Connection) -> None:
    # Keep this migration as forward-only repair; do not destroy data.
    if _index_exists(
        conn, "uq_control_plane_group_workspace_join_requests_workspace_user_pending"
    ):
        conn.execute(
            "DROP INDEX IF EXISTS uq_control_plane_group_workspace_join_requests_workspace_user_pending"
        )

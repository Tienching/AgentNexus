# -*- coding: utf-8 -*-
"""Tenant/workspace control-plane service.

Provides first-class tenant, workspace, and membership records plus
access-resolution read models and audit events.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.core.auth.rbac import ROLE_LEVELS, Role
from src.runtime.stores.db import Database, get_db

from .domain_events import query_domain_events, record_domain_event


_VALID_ROLES = {role.value for role in Role}


@dataclass
class TenantRecord:
    tenant_id: str
    name: str
    status: str = "active"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "status": self.status,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class WorkspaceRecord:
    workspace_id: str
    tenant_id: str
    name: str
    root_path: Optional[str] = None
    default_branch: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "root_path": self.root_path,
            "default_branch": self.default_branch,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class MembershipRecord:
    scope_type: str
    scope_id: str
    username: str
    role: str = Role.VIEWER.value
    scopes: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "username": self.username,
            "role": self.role,
            "scopes": self.scopes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class AccessResolution:
    username: str
    workspace_id: str
    tenant_id: Optional[str]
    allowed: bool
    via: Optional[str] = None
    role: Optional[str] = None
    scopes: List[str] = field(default_factory=list)
    accessible_workspace_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "username": self.username,
            "workspace_id": self.workspace_id,
            "tenant_id": self.tenant_id,
            "allowed": self.allowed,
            "via": self.via,
            "role": self.role,
            "scopes": self.scopes,
            "accessible_workspace_ids": self.accessible_workspace_ids,
        }


class ControlPlaneService:
    """SQLite-backed tenant/workspace control-plane."""

    def __init__(self, db: Optional[Database] = None):
        self._db = db or get_db()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS control_plane_tenants (
                tenant_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS control_plane_workspaces (
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
            """
        )
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS control_plane_memberships (
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                scopes_json TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (scope_type, scope_id, username)
            )
            """
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_control_plane_workspaces_tenant ON control_plane_workspaces(tenant_id, updated_at DESC)"
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_control_plane_memberships_scope ON control_plane_memberships(scope_type, scope_id, username)"
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_control_plane_memberships_user ON control_plane_memberships(username, updated_at DESC)"
        )

    @staticmethod
    def _loads_dict(raw: Any) -> Dict[str, Any]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _loads_list(raw: Any) -> List[str]:
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except Exception:
            return []
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    def _tenant_from_row(self, row: Dict[str, Any]) -> TenantRecord:
        return TenantRecord(
            tenant_id=row["tenant_id"],
            name=row["name"],
            status=row.get("status") or "active",
            metadata=self._loads_dict(row.get("metadata_json")),
            created_at=float(row.get("created_at") or time.time()),
            updated_at=float(row.get("updated_at") or time.time()),
        )

    def _workspace_from_row(self, row: Dict[str, Any]) -> WorkspaceRecord:
        return WorkspaceRecord(
            workspace_id=row["workspace_id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            root_path=row.get("root_path") or None,
            default_branch=row.get("default_branch") or None,
            metadata=self._loads_dict(row.get("metadata_json")),
            created_at=float(row.get("created_at") or time.time()),
            updated_at=float(row.get("updated_at") or time.time()),
        )

    def _membership_from_row(self, row: Dict[str, Any]) -> MembershipRecord:
        return MembershipRecord(
            scope_type=row["scope_type"],
            scope_id=row["scope_id"],
            username=row["username"],
            role=row.get("role") or Role.VIEWER.value,
            scopes=self._loads_list(row.get("scopes_json")),
            created_at=float(row.get("created_at") or time.time()),
            updated_at=float(row.get("updated_at") or time.time()),
        )

    def create_tenant(
        self,
        tenant_id: str,
        name: str,
        *,
        status: str = "active",
        metadata: Optional[Dict[str, Any]] = None,
        actor: str = "system",
    ) -> TenantRecord:
        tenant_id = tenant_id.strip()
        name = name.strip()
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not name:
            raise ValueError("name is required")
        now = time.time()
        record = TenantRecord(
            tenant_id=tenant_id,
            name=name,
            status=(status or "active").strip() or "active",
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO control_plane_tenants (tenant_id, name, status, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (record.tenant_id, record.name, record.status, json.dumps(record.metadata, ensure_ascii=False), now, now),
            )
        record_domain_event(
            "control_plane.tenant.created",
            "tenant",
            record.tenant_id,
            actor=actor,
            payload=record.to_dict(),
            tenant_id=record.tenant_id,
        )
        return record

    def list_tenants(self) -> List[TenantRecord]:
        rows = self._db.execute_fetchall(
            "SELECT * FROM control_plane_tenants ORDER BY updated_at DESC, tenant_id ASC"
        )
        return [self._tenant_from_row(row) for row in rows]

    def get_tenant(self, tenant_id: str) -> Optional[TenantRecord]:
        row = self._db.execute_fetchone(
            "SELECT * FROM control_plane_tenants WHERE tenant_id = ?",
            (tenant_id,),
        )
        return self._tenant_from_row(row) if row else None

    def create_workspace(
        self,
        workspace_id: str,
        tenant_id: str,
        name: str,
        *,
        root_path: Optional[str] = None,
        default_branch: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        actor: str = "system",
    ) -> WorkspaceRecord:
        workspace_id = workspace_id.strip()
        tenant_id = tenant_id.strip()
        name = name.strip()
        if not workspace_id:
            raise ValueError("workspace_id is required")
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not name:
            raise ValueError("name is required")
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"tenant not found: {tenant_id}")
        now = time.time()
        record = WorkspaceRecord(
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            name=name,
            root_path=(root_path or "").strip() or None,
            default_branch=(default_branch or "").strip() or None,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO control_plane_workspaces (
                    workspace_id, tenant_id, name, root_path, default_branch, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.workspace_id,
                    record.tenant_id,
                    record.name,
                    record.root_path,
                    record.default_branch,
                    json.dumps(record.metadata, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        record_domain_event(
            "control_plane.workspace.created",
            "workspace",
            record.workspace_id,
            actor=actor,
            payload=record.to_dict(),
            workspace_id=record.workspace_id,
            tenant_id=record.tenant_id,
        )
        return record

    def get_workspace(self, workspace_id: str) -> Optional[WorkspaceRecord]:
        row = self._db.execute_fetchone(
            "SELECT * FROM control_plane_workspaces WHERE workspace_id = ?",
            (workspace_id,),
        )
        return self._workspace_from_row(row) if row else None

    def list_workspaces(
        self,
        *,
        tenant_id: Optional[str] = None,
        username: Optional[str] = None,
        accessible_only: bool = False,
    ) -> List[WorkspaceRecord]:
        conditions: List[str] = []
        params: List[Any] = []
        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)
        where = " AND ".join(conditions) if conditions else "1=1"
        rows = self._db.execute_fetchall(
            f"SELECT * FROM control_plane_workspaces WHERE {where} ORDER BY updated_at DESC, workspace_id ASC",
            tuple(params),
        )
        workspaces = [self._workspace_from_row(row) for row in rows]
        if username and accessible_only:
            username = username.strip()
            return [
                workspace
                for workspace in workspaces
                if self.resolve_access(username, workspace.workspace_id).allowed
            ]
        return workspaces

    def _validate_role(self, role: str) -> str:
        value = (role or "").strip().lower() or Role.VIEWER.value
        if value not in _VALID_ROLES:
            raise ValueError(f"invalid role: {role}")
        return value

    def upsert_membership(
        self,
        *,
        scope_type: str,
        scope_id: str,
        username: str,
        role: str,
        scopes: Optional[List[str]] = None,
        actor: str = "system",
    ) -> MembershipRecord:
        scope_type = (scope_type or "").strip().lower()
        scope_id = (scope_id or "").strip()
        username = (username or "").strip()
        if scope_type not in {"tenant", "workspace"}:
            raise ValueError("scope_type must be 'tenant' or 'workspace'")
        if not scope_id:
            raise ValueError("scope_id is required")
        if not username:
            raise ValueError("username is required")
        if scope_type == "tenant" and self.get_tenant(scope_id) is None:
            raise ValueError(f"tenant not found: {scope_id}")
        if scope_type == "workspace" and self.get_workspace(scope_id) is None:
            raise ValueError(f"workspace not found: {scope_id}")

        normalized_role = self._validate_role(role)
        normalized_scopes = sorted({str(item).strip() for item in (scopes or []) if str(item).strip()})
        existing = self.get_membership(scope_type=scope_type, scope_id=scope_id, username=username)
        now = time.time()
        created_at = existing.created_at if existing else now
        record = MembershipRecord(
            scope_type=scope_type,
            scope_id=scope_id,
            username=username,
            role=normalized_role,
            scopes=normalized_scopes,
            created_at=created_at,
            updated_at=now,
        )
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO control_plane_memberships (
                    scope_type, scope_id, username, role, scopes_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope_type, scope_id, username) DO UPDATE SET
                    role=excluded.role,
                    scopes_json=excluded.scopes_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record.scope_type,
                    record.scope_id,
                    record.username,
                    record.role,
                    json.dumps(record.scopes, ensure_ascii=False),
                    record.created_at,
                    record.updated_at,
                ),
            )

        workspace = self.get_workspace(scope_id) if scope_type == "workspace" else None
        tenant_ref = scope_id if scope_type == "tenant" else (workspace.tenant_id if workspace else None)
        record_domain_event(
            "control_plane.membership.upserted",
            f"{scope_type}_membership",
            f"{scope_type}:{scope_id}:{username}",
            actor=actor,
            payload=record.to_dict(),
            tenant_id=tenant_ref,
            workspace_id=scope_id if scope_type == "workspace" else None,
        )
        return record

    def get_membership(self, *, scope_type: str, scope_id: str, username: str) -> Optional[MembershipRecord]:
        row = self._db.execute_fetchone(
            "SELECT * FROM control_plane_memberships WHERE scope_type = ? AND scope_id = ? AND username = ?",
            (scope_type, scope_id, username),
        )
        return self._membership_from_row(row) if row else None

    def list_memberships(self, *, scope_type: str, scope_id: str) -> List[MembershipRecord]:
        rows = self._db.execute_fetchall(
            "SELECT * FROM control_plane_memberships WHERE scope_type = ? AND scope_id = ? ORDER BY username ASC",
            (scope_type, scope_id),
        )
        return [self._membership_from_row(row) for row in rows]

    @staticmethod
    def _role_level(role: Optional[str]) -> int:
        if not role:
            return -1
        try:
            return ROLE_LEVELS[Role(role)]
        except Exception:
            return -1

    def list_workspace_audit(self, workspace_id: str, *, limit: int = 100) -> List[Any]:
        workspace_id = (workspace_id or "").strip()
        if not workspace_id:
            return []
        return query_domain_events(workspace_id=workspace_id, limit=limit)

    def resolve_access(self, username: str, workspace_id: str) -> AccessResolution:
        username = (username or "").strip()
        workspace = self.get_workspace(workspace_id)
        if not username or workspace is None:
            return AccessResolution(
                username=username,
                workspace_id=workspace_id,
                tenant_id=workspace.tenant_id if workspace else None,
                allowed=False,
                accessible_workspace_ids=[],
            )

        direct = self.get_membership(scope_type="workspace", scope_id=workspace.workspace_id, username=username)
        inherited = self.get_membership(scope_type="tenant", scope_id=workspace.tenant_id, username=username)

        chosen: Optional[MembershipRecord] = None
        via: Optional[str] = None
        for candidate, candidate_via in ((direct, "workspace"), (inherited, "tenant")):
            if candidate is None:
                continue
            if chosen is None or self._role_level(candidate.role) > self._role_level(chosen.role):
                chosen = candidate
                via = candidate_via

        accessible_workspace_ids: List[str] = []
        if inherited is not None:
            accessible_workspace_ids.extend([
                item.workspace_id for item in self.list_workspaces(tenant_id=workspace.tenant_id)
            ])
        if direct is not None and workspace.workspace_id not in accessible_workspace_ids:
            accessible_workspace_ids.append(workspace.workspace_id)

        return AccessResolution(
            username=username,
            workspace_id=workspace.workspace_id,
            tenant_id=workspace.tenant_id,
            allowed=chosen is not None,
            via=via,
            role=chosen.role if chosen else None,
            scopes=chosen.scopes if chosen else [],
            accessible_workspace_ids=sorted(accessible_workspace_ids),
        )


_control_plane_services: Dict[str, ControlPlaneService] = {}


def get_control_plane_service(db: Optional[Database] = None) -> ControlPlaneService:
    database = db or get_db()
    key = str(getattr(database, "db_path", "default"))
    service = _control_plane_services.get(key)
    if service is None:
        service = ControlPlaneService(database)
        _control_plane_services[key] = service
    return service

# -*- coding: utf-8 -*-
"""Tenant / workspace control-plane APIs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..services.domain_events import query_domain_events
from ..services.control_plane import get_control_plane_service
from .nexus_auth import require_nexus_admin, verify_nexus_auth

router = APIRouter(
    prefix="/api/nexus/control-plane",
    tags=["nexus-control-plane"],
    dependencies=[Depends(verify_nexus_auth)],
)


class TenantItem(BaseModel):
    tenant_id: str
    name: str
    status: str = "active"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: float
    updated_at: float


class WorkspaceItem(BaseModel):
    workspace_id: str
    tenant_id: str
    name: str
    root_path: Optional[str] = None
    default_branch: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: float
    updated_at: float


class MembershipItem(BaseModel):
    scope_type: str
    scope_id: str
    username: str
    role: str
    scopes: List[str] = Field(default_factory=list)
    created_at: float
    updated_at: float


class AccessResolutionItem(BaseModel):
    username: str
    workspace_id: str
    tenant_id: Optional[str] = None
    allowed: bool
    via: Optional[str] = None
    role: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    accessible_workspace_ids: List[str] = Field(default_factory=list)


class CreateTenantRequest(BaseModel):
    tenant_id: str
    name: str
    status: str = "active"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(default_factory=lambda: settings.exec_user)


class CreateWorkspaceRequest(BaseModel):
    workspace_id: str
    tenant_id: str
    name: str
    root_path: Optional[str] = None
    default_branch: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(default_factory=lambda: settings.exec_user)


class UpsertMembershipRequest(BaseModel):
    scope_type: str
    scope_id: str
    username: str
    role: str
    scopes: List[str] = Field(default_factory=list)
    actor: str = Field(default_factory=lambda: settings.exec_user)


class ScopedMembershipRequest(BaseModel):
    role: str
    scopes: List[str] = Field(default_factory=list)
    actor: str = Field(default_factory=lambda: settings.exec_user)


class AuditEventItem(BaseModel):
    event_type: str
    aggregate_type: str
    aggregate_id: str
    actor: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    workspace_id: Optional[str] = None
    tenant_id: Optional[str] = None
    created_at: float


def _actor_name(admin_user: Any) -> str:
    return (getattr(admin_user, "username", None) or settings.exec_user or "system").strip() or "system"


@router.get("/tenants", response_model=List[TenantItem])
async def list_tenants():
    service = get_control_plane_service()
    return [TenantItem(**item.to_dict()) for item in service.list_tenants()]


@router.post("/tenants", response_model=TenantItem, status_code=201)
async def create_tenant(request: CreateTenantRequest, admin_user=Depends(require_nexus_admin)):
    service = get_control_plane_service()
    try:
        item = service.create_tenant(
            tenant_id=request.tenant_id,
            name=request.name,
            status=request.status,
            metadata=request.metadata,
            actor=_actor_name(admin_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TenantItem(**item.to_dict())


@router.get("/workspaces", response_model=List[WorkspaceItem])
async def list_workspaces(
    tenant_id: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    accessible_only: bool = Query(False),
):
    service = get_control_plane_service()
    items = service.list_workspaces(tenant_id=tenant_id)
    if accessible_only and username:
        filtered = []
        for item in items:
            resolution = service.resolve_access(username=username, workspace_id=item.workspace_id)
            if resolution.allowed:
                filtered.append(item)
        items = filtered
    return [WorkspaceItem(**item.to_dict()) for item in items]


@router.post("/workspaces", response_model=WorkspaceItem, status_code=201)
async def create_workspace(request: CreateWorkspaceRequest, admin_user=Depends(require_nexus_admin)):
    service = get_control_plane_service()
    try:
        item = service.create_workspace(
            workspace_id=request.workspace_id,
            tenant_id=request.tenant_id,
            name=request.name,
            root_path=request.root_path,
            default_branch=request.default_branch,
            metadata=request.metadata,
            actor=_actor_name(admin_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WorkspaceItem(**item.to_dict())


@router.get("/memberships", response_model=List[MembershipItem])
async def list_memberships(
    scope_type: Optional[str] = Query(None),
    scope_id: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
):
    service = get_control_plane_service()
    if scope_type and scope_id and username:
        item = service.get_membership(scope_type=scope_type, scope_id=scope_id, username=username)
        return [MembershipItem(**item.to_dict())] if item else []
    if scope_type and scope_id:
        items = service.list_memberships(scope_type=scope_type, scope_id=scope_id)
    elif username:
        items = service.list_user_memberships(username)
    else:
        raise HTTPException(status_code=400, detail="scope_type+scope_id or username is required")
    return [MembershipItem(**item.to_dict()) for item in items]


@router.post("/memberships", response_model=MembershipItem)
async def upsert_membership(request: UpsertMembershipRequest, admin_user=Depends(require_nexus_admin)):
    service = get_control_plane_service()
    try:
        item = service.upsert_membership(
            scope_type=request.scope_type,
            scope_id=request.scope_id,
            username=request.username,
            role=request.role,
            scopes=request.scopes,
            actor=_actor_name(admin_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MembershipItem(**item.to_dict())


@router.put("/tenants/{tenant_id}/memberships/{username}", response_model=MembershipItem)
async def upsert_tenant_membership(
    tenant_id: str,
    username: str,
    request: ScopedMembershipRequest,
    admin_user=Depends(require_nexus_admin),
):
    return await upsert_membership(
        UpsertMembershipRequest(
            scope_type="tenant",
            scope_id=tenant_id,
            username=username,
            role=request.role,
            scopes=request.scopes,
            actor=_actor_name(admin_user),
        ),
        admin_user=admin_user,
    )


@router.put("/workspaces/{workspace_id}/memberships/{username}", response_model=MembershipItem)
async def upsert_workspace_membership(
    workspace_id: str,
    username: str,
    request: ScopedMembershipRequest,
    admin_user=Depends(require_nexus_admin),
):
    return await upsert_membership(
        UpsertMembershipRequest(
            scope_type="workspace",
            scope_id=workspace_id,
            username=username,
            role=request.role,
            scopes=request.scopes,
            actor=_actor_name(admin_user),
        ),
        admin_user=admin_user,
    )


@router.get("/access", response_model=AccessResolutionItem)
async def resolve_access(
    username: str = Query(...),
    workspace_id: str = Query(...),
):
    service = get_control_plane_service()
    resolution = service.resolve_access(username=username, workspace_id=workspace_id)
    return AccessResolutionItem(**resolution.to_dict())


@router.get("/workspaces/{workspace_id}/access", response_model=AccessResolutionItem)
async def resolve_workspace_access(workspace_id: str, username: str = Query(...)):
    return await resolve_access(username=username, workspace_id=workspace_id)


@router.get("/workspaces/{workspace_id}/audit", response_model=List[AuditEventItem])
async def workspace_audit(workspace_id: str, limit: int = Query(100, ge=1, le=500)):
    events = query_domain_events(workspace_id=workspace_id, limit=limit)
    return [
        AuditEventItem(
            event_type=str(getattr(event, "event_type", "") or ""),
            aggregate_type=str(getattr(event, "aggregate_type", "") or ""),
            aggregate_id=str(getattr(event, "aggregate_id", "") or ""),
            actor=str(getattr(event, "actor", "") or ""),
            payload=getattr(event, "payload", {}) if isinstance(getattr(event, "payload", {}), dict) else {},
            workspace_id=str(getattr(event, "workspace_id", "") or "") or None,
            tenant_id=str(getattr(event, "tenant_id", "") or "") or None,
            created_at=float(getattr(event, "created_at", 0.0) or 0.0),
        )
        for event in events
        if str(getattr(event, "workspace_id", "") or "") == workspace_id
    ]

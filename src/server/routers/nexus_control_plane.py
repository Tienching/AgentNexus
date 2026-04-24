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


class GroupItem(BaseModel):
    group_id: str
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


class CreateGroupRequest(BaseModel):
    group_id: str
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


class JoinRequestItem(BaseModel):
    request_id: str
    scope_type: str
    scope_id: str
    workspace_id: str
    group_id: str
    username: str
    role: str
    scopes: List[str] = Field(default_factory=list)
    status: str
    note: str = ""
    reviewer: Optional[str] = None
    review_note: Optional[str] = None
    reviewed_at: Optional[float] = None
    created_at: float
    updated_at: float


class CreateJoinRequest(BaseModel):
    username: str
    role: str = "viewer"
    scopes: List[str] = Field(default_factory=list)
    note: str = ""
    actor: str = Field(default_factory=lambda: settings.exec_user)


class ResolveJoinRequest(BaseModel):
    status: str
    review_note: Optional[str] = None
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


def _to_group_item(item: Any) -> GroupItem:
    return GroupItem(
        group_id=item.tenant_id,
        name=item.name,
        status=item.status,
        metadata=item.metadata,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _to_join_request_item(item: Any) -> JoinRequestItem:
    return JoinRequestItem(
        request_id=item.request_id,
        scope_type=item.scope_type,
        scope_id=item.scope_id,
        workspace_id=item.workspace_id,
        group_id=item.group_id,
        username=item.username,
        role=item.role,
        scopes=item.scopes,
        status=item.status,
        note=item.note,
        reviewer=item.reviewer,
        review_note=item.review_note,
        reviewed_at=item.reviewed_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _normalize_join_request_status(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    normalized = raw.strip().lower()
    if not normalized:
        return None
    if normalized in {"approve", "approved"}:
        return "approved"
    if normalized in {"reject", "rejected"}:
        return "rejected"
    if normalized in {"pending", "approved", "rejected"}:
        return normalized
    raise ValueError(f"invalid status: {raw}")


@router.get("/tenants", response_model=List[TenantItem])
async def list_tenants():
    service = get_control_plane_service()
    return [TenantItem(**item.to_dict()) for item in service.list_tenants()]


@router.get("/groups", response_model=List[GroupItem])
async def list_groups():
    service = get_control_plane_service()
    return [_to_group_item(item) for item in service.list_tenants()]


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


@router.post("/groups", response_model=GroupItem, status_code=201)
async def create_group(request: CreateGroupRequest, admin_user=Depends(require_nexus_admin)):
    service = get_control_plane_service()
    try:
        item = service.create_tenant(
            tenant_id=request.group_id,
            name=request.name,
            status=request.status,
            metadata=request.metadata,
            actor=_actor_name(admin_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_group_item(item)


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


@router.get("/workspaces/{workspace_id}/join-requests", response_model=List[JoinRequestItem])
async def list_workspace_join_requests(
    workspace_id: str,
    status: Optional[str] = Query(None),
    admin_user=Depends(require_nexus_admin),
):
    service = get_control_plane_service()
    try:
        normalized_status = _normalize_join_request_status(status)
        items = service.list_workspace_join_requests(workspace_id=workspace_id, status=normalized_status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_to_join_request_item(item) for item in items]


@router.post(
    "/workspaces/{workspace_id}/join-requests",
    response_model=JoinRequestItem,
    status_code=201,
)
async def create_workspace_join_request(
    workspace_id: str,
    request: CreateJoinRequest,
    admin_user=Depends(require_nexus_admin),
):
    service = get_control_plane_service()
    try:
        item = service.create_workspace_join_request(
            workspace_id=workspace_id,
            username=request.username,
            role=request.role,
            scopes=request.scopes,
            note=request.note,
            actor=_actor_name(admin_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_join_request_item(item)


@router.patch(
    "/workspaces/{workspace_id}/join-requests/{request_id}",
    response_model=JoinRequestItem,
)
async def resolve_workspace_join_request(
    workspace_id: str,
    request_id: str,
    request: ResolveJoinRequest,
    admin_user=Depends(require_nexus_admin),
):
    service = get_control_plane_service()
    try:
        resolved_status = _normalize_join_request_status(request.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if resolved_status is None:
        raise HTTPException(status_code=400, detail="status is required")

    existing = service.get_workspace_join_request(request_id=request_id)
    if existing is None or existing.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"join request not found: {request_id}")

    try:
        item = service.resolve_workspace_join_request(
            request_id=request_id,
            status=resolved_status,
            reviewer=_actor_name(admin_user),
            review_note=request.review_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_join_request_item(item)


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

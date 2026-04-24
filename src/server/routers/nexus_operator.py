# -*- coding: utf-8 -*-
"""Operator automation endpoints for CLI/TUI parity."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..services.agent_runtimes import get_runtime_daemon_registry
from ..services.collaboration_service import CollaborationService
from ..services.control_plane import get_control_plane_service
from ..services.extension_registry import ExtensionRegistryService
from ..services.worktree_registry import get_repo_worktree_registry
from .health import _perform_health_check
from .nexus_auth import verify_nexus_auth

router = APIRouter(
    prefix="/api/nexus/operator",
    tags=["nexus-operator"],
    dependencies=[Depends(verify_nexus_auth)],
)


class OperatorRepoRegistryItem(BaseModel):
    repo_key: str
    repo_url: Optional[str] = None
    repo_root: Optional[str] = None
    worktree_path: Optional[str] = None
    branch_name: Optional[str] = None
    workspace: Optional[str] = None
    task_id: Optional[str] = None
    prior_session_id: Optional[str] = None
    prior_work_dir: Optional[str] = None
    lock_owner: Optional[str] = None
    lock_token: Optional[str] = None
    lock_expires_at: Optional[float] = None
    last_used_at: float
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: float
    updated_at: float


class OperatorRepoCacheItem(BaseModel):
    repo_key: str
    repo_url: Optional[str] = None
    repo_root: Optional[str] = None
    cache_path: Optional[str] = None
    lock_owner: Optional[str] = None
    lock_token: Optional[str] = None
    lock_expires_at: Optional[float] = None
    last_fetched_at: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: float
    updated_at: float


class OperatorRepoRegistryResponse(BaseModel):
    items: List[OperatorRepoRegistryItem] = Field(default_factory=list)
    count: int = 0


class OperatorRepoCacheResponse(BaseModel):
    items: List[OperatorRepoCacheItem] = Field(default_factory=list)
    count: int = 0


class OperatorDashboardCollaboration(BaseModel):
    projects: int = 0
    issues: int = 0
    inbox_tasks: int = 0


class OperatorDashboardExtensions(BaseModel):
    providers: int = 0
    plugins: int = 0
    bundled_skills: int = 0
    panels: int = 0


class OperatorDashboardRepos(BaseModel):
    registry_records: int = 0
    caches: int = 0


class OperatorDashboardRuntimes(BaseModel):
    total_daemons: int = 0
    offline_daemons: int = 0


class OperatorDashboardResponse(BaseModel):
    generated_at: float
    health_status: str
    health_checks: int
    tenants: int = 0
    workspaces: int = 0
    collaboration: OperatorDashboardCollaboration
    extensions: OperatorDashboardExtensions
    repos: OperatorDashboardRepos
    runtimes: OperatorDashboardRuntimes


@router.get("/repos/registry", response_model=OperatorRepoRegistryResponse)
async def list_operator_repo_registry(
    repo_root: Optional[str] = Query(None),
    workspace: Optional[str] = Query(None),
):
    registry = get_repo_worktree_registry()
    items = registry.list_records(repo_root=repo_root, workspace=workspace)
    return OperatorRepoRegistryResponse(
        items=[OperatorRepoRegistryItem(**item.to_dict()) for item in items],
        count=len(items),
    )


@router.get("/repos/caches", response_model=OperatorRepoCacheResponse)
async def list_operator_repo_caches():
    registry = get_repo_worktree_registry()
    items = registry.list_caches()
    return OperatorRepoCacheResponse(
        items=[OperatorRepoCacheItem(**item.to_dict()) for item in items],
        count=len(items),
    )


@router.get("/dashboard", response_model=OperatorDashboardResponse)
async def get_operator_dashboard(exec_user: str = Query(settings.exec_user)):
    control_plane = get_control_plane_service()
    collab = CollaborationService(exec_user=exec_user)
    extensions = await ExtensionRegistryService(exec_user=exec_user).get_catalog()
    registry = get_repo_worktree_registry()
    runtime_registry = get_runtime_daemon_registry()
    health = _perform_health_check()

    tenants = control_plane.list_tenants()
    workspaces = control_plane.list_workspaces()
    projects = collab.list_projects()
    issues = collab.list_issues()
    inbox = collab.get_inbox()
    repo_records = registry.list_records()
    repo_caches = registry.list_caches()
    daemons = runtime_registry.list_daemons()

    return OperatorDashboardResponse(
        generated_at=time.time(),
        health_status=health.status,
        health_checks=len(health.checks),
        tenants=len(tenants),
        workspaces=len(workspaces),
        collaboration=OperatorDashboardCollaboration(
            projects=len(projects),
            issues=len(issues),
            inbox_tasks=int(getattr(inbox, "total_tasks", 0) or 0),
        ),
        extensions=OperatorDashboardExtensions(
            providers=len(extensions.get("providers", [])),
            plugins=len(extensions.get("plugins", [])),
            bundled_skills=len(extensions.get("bundled_skills", [])),
            panels=len(extensions.get("panels", [])),
        ),
        repos=OperatorDashboardRepos(
            registry_records=len(repo_records),
            caches=len(repo_caches),
        ),
        runtimes=OperatorDashboardRuntimes(
            total_daemons=len(daemons),
            offline_daemons=sum(1 for daemon in daemons if getattr(daemon, "status", "") == "offline"),
        ),
    )

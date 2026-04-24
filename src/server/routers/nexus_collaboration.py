# -*- coding: utf-8 -*-
"""Project / issue / inbox collaboration APIs built above raw tasks."""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..services.collaboration_service import CollaborationService
from .nexus_auth import verify_nexus_auth
from .nexus_models import TaskItem, task_to_item

router = APIRouter(
    prefix="/api/nexus/collab",
    tags=["nexus-collaboration"],
    dependencies=[Depends(verify_nexus_auth)],
)


class CollaborationIssueItem(BaseModel):
    issue_key: str
    title: str
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    workspace: Optional[str] = None
    task_ids: List[str] = Field(default_factory=list)
    statuses: Dict[str, int] = Field(default_factory=dict)
    total_tasks: int = 0
    open_tasks: int = 0
    done_tasks: int = 0
    latest_updated_at: float = 0.0
    ticket_ref: Optional[str] = None
    github_issue_number: Optional[int] = None


class CollaborationProjectItem(BaseModel):
    project_id: str
    project_name: str
    total_tasks: int = 0
    active_tasks: int = 0
    done_tasks: int = 0
    inbox_tasks: int = 0
    issue_count: int = 0
    latest_updated_at: float = 0.0
    issues: List[CollaborationIssueItem] = Field(default_factory=list)


class CollaborationInboxResponse(BaseModel):
    total_tasks: int = 0
    statuses: Dict[str, int] = Field(default_factory=dict)
    issues: List[CollaborationIssueItem] = Field(default_factory=list)
    tasks: List[str] = Field(default_factory=list)


class CollaborationIssueDetailResponse(BaseModel):
    issue: CollaborationIssueItem
    tasks: List[TaskItem] = Field(default_factory=list)


class CreateIssueRequest(BaseModel):
    title: str
    description: str = ""
    project_name: Optional[str] = None
    project_id: Optional[str] = None
    workspace: Optional[str] = None
    ticket_ref: Optional[str] = None
    assigned_to: Optional[str] = None
    actor: str = "system"


class CreateIssueResponse(BaseModel):
    issue: CollaborationIssueItem
    task: TaskItem


def _service(exec_user: Optional[str]) -> CollaborationService:
    return CollaborationService(exec_user=exec_user or settings.exec_user)


def _issue_item(issue) -> CollaborationIssueItem:
    return CollaborationIssueItem(**issue.to_dict())


@router.get("/projects", response_model=List[CollaborationProjectItem])
async def list_collaboration_projects(exec_user: str = Query(settings.exec_user)):
    service = _service(exec_user)
    return [
        CollaborationProjectItem(
            **{**project.to_dict(), "issues": [_issue_item(issue) for issue in project.issues]}
        )
        for project in service.list_projects()
    ]


@router.get("/projects/{project_id}", response_model=CollaborationProjectItem)
async def get_collaboration_project(project_id: str, exec_user: str = Query(settings.exec_user)):
    service = _service(exec_user)
    project = service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return CollaborationProjectItem(
        **{**project.to_dict(), "issues": [_issue_item(issue) for issue in project.issues]}
    )


@router.get("/issues", response_model=List[CollaborationIssueItem])
async def list_collaboration_issues(
    exec_user: str = Query(settings.exec_user),
    project_id: Optional[str] = Query(None),
    inbox_only: bool = Query(False),
):
    service = _service(exec_user)
    return [_issue_item(issue) for issue in service.list_issues(project_id=project_id, only_inbox=inbox_only)]


@router.get("/issues/{issue_key}", response_model=CollaborationIssueDetailResponse)
async def get_collaboration_issue(issue_key: str, exec_user: str = Query(settings.exec_user)):
    service = _service(exec_user)
    issue = service.get_issue(issue_key)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue not found: {issue_key}")
    tasks = []
    for task_id in issue.task_ids:
        task = service.queue.get_task(task_id)
        if task is not None:
            tasks.append(task_to_item(task))
    return CollaborationIssueDetailResponse(issue=_issue_item(issue), tasks=tasks)


@router.get("/inbox", response_model=CollaborationInboxResponse)
async def get_collaboration_inbox(exec_user: str = Query(settings.exec_user)):
    service = _service(exec_user)
    inbox = service.get_inbox()
    return CollaborationInboxResponse(**{**inbox.to_dict(), "issues": [_issue_item(issue) for issue in inbox.issues]})


@router.post("/issues", response_model=CreateIssueResponse, status_code=201)
async def create_collaboration_issue(request: CreateIssueRequest, exec_user: str = Query(settings.exec_user)):
    service = _service(exec_user)
    try:
        task = service.create_issue(
            title=request.title,
            description=request.description,
            project_name=request.project_name,
            project_id=request.project_id,
            workspace=request.workspace,
            ticket_ref=request.ticket_ref,
            assigned_to=request.assigned_to,
            actor=request.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    issue = service.get_issue(str(getattr(task, "ticket_ref", "") or getattr(task, "id", "")))
    if issue is None:
        raise HTTPException(status_code=500, detail="Issue materialization failed")
    return CreateIssueResponse(issue=_issue_item(issue), task=task_to_item(task))

# -*- coding: utf-8 -*-
"""Collaboration read-models built on top of raw task records.

Provides project / issue / inbox abstractions without changing the underlying
runtime task storage model.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import re
from src.runtime.models.task_models import TaskPriority, TaskStatus

from .domain_events import record_domain_event
from .task_storage import get_task_queue


def slugify_project(name: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return value or "project"


_ACTIVE_ISSUE_STATUSES = {
    TaskStatus.PENDING.value,
    TaskStatus.RUNNING.value,
    TaskStatus.IN_REVIEW.value,
}

_INBOX_STATUSES = {
    TaskStatus.PENDING.value,
}


@dataclass
class CollaborationIssue:
    issue_key: str
    title: str
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    workspace: Optional[str] = None
    task_ids: List[str] = field(default_factory=list)
    statuses: Dict[str, int] = field(default_factory=dict)
    total_tasks: int = 0
    open_tasks: int = 0
    done_tasks: int = 0
    latest_updated_at: float = 0.0
    ticket_ref: Optional[str] = None
    github_issue_number: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_key": self.issue_key,
            "title": self.title,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "workspace": self.workspace,
            "task_ids": list(self.task_ids),
            "statuses": dict(self.statuses),
            "total_tasks": self.total_tasks,
            "open_tasks": self.open_tasks,
            "done_tasks": self.done_tasks,
            "latest_updated_at": self.latest_updated_at,
            "ticket_ref": self.ticket_ref,
            "github_issue_number": self.github_issue_number,
        }


@dataclass
class CollaborationProject:
    project_id: str
    project_name: str
    total_tasks: int = 0
    active_tasks: int = 0
    done_tasks: int = 0
    inbox_tasks: int = 0
    issue_count: int = 0
    latest_updated_at: float = 0.0
    issues: List[CollaborationIssue] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "total_tasks": self.total_tasks,
            "active_tasks": self.active_tasks,
            "done_tasks": self.done_tasks,
            "inbox_tasks": self.inbox_tasks,
            "issue_count": self.issue_count,
            "latest_updated_at": self.latest_updated_at,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class InboxSummary:
    total_tasks: int
    statuses: Dict[str, int]
    issues: List[CollaborationIssue] = field(default_factory=list)
    tasks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_tasks": self.total_tasks,
            "statuses": dict(self.statuses),
            "issues": [issue.to_dict() for issue in self.issues],
            "tasks": list(self.tasks),
        }


class CollaborationService:
    """Compose collaboration-level read models from task records."""

    def __init__(self, exec_user: str = "default"):
        self.exec_user = exec_user or "default"
        self.queue = get_task_queue(self.exec_user)

    @staticmethod
    def _status_value(task: Any) -> str:
        raw = getattr(task, "status", None)
        return raw if isinstance(raw, str) else getattr(raw, "value", str(raw or ""))

    @staticmethod
    def _task_updated_at(task: Any) -> float:
        for candidate in (
            getattr(task, "updated_at", None),
            getattr(task, "completed_at", None),
            getattr(task, "started_at", None),
            getattr(task, "created_at", None),
        ):
            if candidate is None:
                continue
            try:
                return float(getattr(candidate, "timestamp", lambda: candidate)())
            except Exception:
                try:
                    return float(candidate)
                except Exception:
                    continue
        return 0.0

    @staticmethod
    def _issue_key(task: Any) -> str:
        ticket_ref = str(getattr(task, "ticket_ref", "") or "").strip()
        if ticket_ref:
            return ticket_ref
        github_issue_number = getattr(task, "github_issue_number", None)
        if isinstance(github_issue_number, int):
            repo = str(getattr(task, "github_repo", "") or "").strip()
            return f"{repo}#{github_issue_number}" if repo else f"issue#{github_issue_number}"
        project_id = str(getattr(task, "project_id", "") or "").strip()
        task_id = str(getattr(task, "id", "") or "").strip()
        if project_id and task_id:
            return f"{project_id}:{task_id}"
        return task_id or f"task:{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _issue_title(task: Any) -> str:
        description = str(getattr(task, "description", "") or "").strip()
        if not description:
            return str(getattr(task, "ticket_ref", "") or getattr(task, "id", "Issue"))
        return description.splitlines()[0][:160]

    def _list_tasks(self, *, project_id: Optional[str] = None) -> List[Any]:
        page = 1
        page_size = 500
        tasks, total = self.queue.list_tasks(page=page, page_size=page_size, project_id=project_id)
        if total > len(tasks):
            page_size = min(max(total, page_size), 5000)
            tasks, _ = self.queue.list_tasks(page=1, page_size=page_size, project_id=project_id)
        return list(tasks)

    def list_issues(self, *, project_id: Optional[str] = None, only_inbox: bool = False) -> List[CollaborationIssue]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for task in self._list_tasks(project_id=project_id):
            status = self._status_value(task)
            if only_inbox and status not in _INBOX_STATUSES:
                continue
            key = self._issue_key(task)
            issue = grouped.setdefault(
                key,
                {
                    "issue_key": key,
                    "title": self._issue_title(task),
                    "project_id": getattr(task, "project_id", None),
                    "project_name": getattr(task, "project_name", None),
                    "workspace": getattr(task, "workspace", None),
                    "task_ids": [],
                    "statuses": Counter(),
                    "latest_updated_at": 0.0,
                    "ticket_ref": getattr(task, "ticket_ref", None),
                    "github_issue_number": getattr(task, "github_issue_number", None),
                },
            )
            issue["task_ids"].append(str(getattr(task, "id", "")))
            issue["statuses"][status] += 1
            issue["latest_updated_at"] = max(issue["latest_updated_at"], self._task_updated_at(task))
        issues: List[CollaborationIssue] = []
        for payload in grouped.values():
            statuses = dict(payload["statuses"])
            total_tasks = sum(statuses.values())
            done_tasks = statuses.get(TaskStatus.COMPLETED.value, 0)
            open_tasks = sum(count for state, count in statuses.items() if state in _ACTIVE_ISSUE_STATUSES)
            issues.append(
                CollaborationIssue(
                    issue_key=payload["issue_key"],
                    title=payload["title"],
                    project_id=payload["project_id"],
                    project_name=payload["project_name"],
                    workspace=payload["workspace"],
                    task_ids=sorted(payload["task_ids"]),
                    statuses=statuses,
                    total_tasks=total_tasks,
                    open_tasks=open_tasks,
                    done_tasks=done_tasks,
                    latest_updated_at=payload["latest_updated_at"],
                    ticket_ref=payload["ticket_ref"],
                    github_issue_number=payload["github_issue_number"],
                )
            )
        issues.sort(key=lambda item: (-item.latest_updated_at, item.issue_key))
        return issues

    def get_issue(self, issue_key: str) -> Optional[CollaborationIssue]:
        for issue in self.list_issues():
            if issue.issue_key == issue_key:
                return issue
        return None

    def list_projects(self) -> List[CollaborationProject]:
        issues_by_project: Dict[str, List[CollaborationIssue]] = {}
        for issue in self.list_issues():
            if issue.project_id:
                issues_by_project.setdefault(issue.project_id, []).append(issue)

        projects: List[CollaborationProject] = []
        for item in self.queue.get_projects():
            project_issues = issues_by_project.get(item["project_id"], [])
            projects.append(
                CollaborationProject(
                    project_id=item["project_id"],
                    project_name=item.get("project_name") or item["project_id"],
                    total_tasks=int(item.get("total_tasks", 0) or 0),
                    active_tasks=int(item.get("running", item.get("doing", item.get("in_progress", 0))) or 0)
                    + int(item.get("in_review", item.get("review", 0)) or 0),
                    done_tasks=int(item.get("completed", item.get("done", 0)) or 0),
                    inbox_tasks=int(item.get("pending", item.get("inbox", item.get("todo", 0))) or 0),
                    issue_count=len(project_issues),
                    latest_updated_at=max((issue.latest_updated_at for issue in project_issues), default=0.0),
                    issues=project_issues,
                )
            )
        projects.sort(key=lambda item: (-item.latest_updated_at, item.project_id))
        return projects

    def get_project(self, project_id: str) -> Optional[CollaborationProject]:
        for project in self.list_projects():
            if project.project_id == project_id:
                return project
        return None

    def get_inbox(self) -> InboxSummary:
        issues = self.list_issues(only_inbox=True)
        statuses = Counter()
        task_ids: List[str] = []
        for issue in issues:
            for state, count in issue.statuses.items():
                statuses[state] += count
            task_ids.extend(issue.task_ids)
        return InboxSummary(
            total_tasks=sum(statuses.values()),
            statuses=dict(statuses),
            issues=issues,
            tasks=sorted(task_ids),
        )

    def create_issue(
        self,
        *,
        title: str,
        description: Optional[str] = None,
        project_name: Optional[str] = None,
        project_id: Optional[str] = None,
        workspace: Optional[str] = None,
        ticket_ref: Optional[str] = None,
        assigned_to: Optional[str] = None,
        actor: str = "system",
    ) -> Any:
        normalized_title = (title or "").strip()
        if not normalized_title:
            raise ValueError("title is required")
        normalized_project_name = (project_name or "").strip() or None
        normalized_project_id = (project_id or "").strip() or None
        if normalized_project_name and not normalized_project_id:
            normalized_project_id = slugify_project(normalized_project_name)
        body = (description or "").strip()
        task_description = normalized_title if not body else f"{normalized_title}\n\n{body}"
        task = self.queue.add_task(
            description=task_description,
            workspace=(workspace or "").strip() or None,
            priority=TaskPriority.PROJECT if (normalized_project_name or normalized_project_id) else TaskPriority.THOUGHT,
            project_id=normalized_project_id,
            project_name=normalized_project_name,
            ticket_ref=(ticket_ref or "").strip() or f"ISSUE-{uuid.uuid4().hex[:8]}",
            assigned_to=(assigned_to or "").strip() or None,
        )
        record_domain_event(
            "collaboration.issue.created",
            "issue",
            str(getattr(task, "ticket_ref", "") or getattr(task, "id", "")),
            actor=actor,
            payload={
                "task_id": getattr(task, "id", None),
                "project_id": normalized_project_id,
                "project_name": normalized_project_name,
                "title": normalized_title,
            },
            workspace_id=(workspace or "").strip() or None,
            task_id=getattr(task, "id", None),
        )
        return task


__all__ = [
    "CollaborationIssue",
    "CollaborationProject",
    "InboxSummary",
    "CollaborationService",
]

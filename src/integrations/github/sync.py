# -*- coding: utf-8 -*-
"""GitHub Issues synchronization.

MC-020: Sync GitHub issues with local tasks, including label and assignee mapping.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib import request as urlrequest

from src.runtime.models.task_models import TaskPriority, TaskStatus
from src.runtime.stores.db import get_db
from src.runtime.stores.task_storage import TaskQueue


STATUS_TO_LABEL = {
    TaskStatus.INBOX.value: "mc:inbox",
    TaskStatus.ASSIGNED.value: "mc:assigned",
    TaskStatus.IN_PROGRESS.value: "mc:in-progress",
    TaskStatus.REVIEW.value: "mc:review",
    TaskStatus.QUALITY_REVIEW.value: "mc:quality-review",
    TaskStatus.DONE.value: "mc:done",
}

LABEL_TO_STATUS = {v: k for k, v in STATUS_TO_LABEL.items()}

PRIORITY_TO_LABEL = {
    TaskPriority.PROJECT.value: "priority:critical",
    TaskPriority.SERIOUS.value: "priority:medium",
    TaskPriority.THOUGHT.value: "priority:low",
}


@dataclass
class GitHubSyncResult:
    pulled: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0


class GitHubIssueSync:
    """Bidirectional task/issue synchronization service."""

    def __init__(self, token: Optional[str] = None):
        self._token = token or os.getenv("GITHUB_TOKEN", "")
        self._db = get_db()

    def fetch_issues(
        self,
        repo: str,
        state: str = "all",
        since: Optional[str] = None,
        per_page: int = 100,
    ) -> List[Dict[str, Any]]:
        """Fetch issues from GitHub REST API."""
        query = f"state={state}&per_page={max(1, min(per_page, 100))}"
        if since:
            query += f"&since={since}"

        req = urlrequest.Request(
            f"https://api.github.com/repos/{repo}/issues?{query}",
            headers=self._headers(),
            method="GET",
        )
        with urlrequest.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                # Ignore PRs from issues endpoint
                return [item for item in data if "pull_request" not in item]
            return []

    def sync_repo(
        self,
        repo: str,
        exec_user: str = "default",
        assignee_map: Optional[Dict[str, str]] = None,
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
        since: Optional[str] = None,
    ) -> GitHubSyncResult:
        """Pull issues from a repo and sync to local tasks."""
        issues = self.fetch_issues(repo=repo, state="all", since=since)
        result = GitHubSyncResult(pulled=len(issues))

        for issue in issues:
            action = self.sync_issue_to_task(
                issue=issue,
                repo=repo,
                exec_user=exec_user,
                assignee_map=assignee_map or {},
                project_id=project_id,
                project_name=project_name,
            )
            if action == "created":
                result.created += 1
            elif action == "updated":
                result.updated += 1
            else:
                result.skipped += 1

        return result

    def sync_issue_to_task(
        self,
        issue: Dict[str, Any],
        repo: str,
        exec_user: str = "default",
        assignee_map: Optional[Dict[str, str]] = None,
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
    ) -> str:
        """Sync one GitHub issue into local task storage.

        Returns: "created" | "updated" | "skipped"
        """
        number = issue.get("number")
        if not number:
            return "skipped"

        queue = TaskQueue(exec_user=exec_user)
        existing = self._find_task_by_issue(repo=repo, issue_number=int(number), exec_user=exec_user)

        mapped_status = self._map_issue_status(issue)
        mapped_priority = self._map_issue_priority(issue)
        mapped_assignee = self._map_assignee(issue, assignee_map or {})

        labels = [l.get("name") for l in issue.get("labels", []) if isinstance(l, dict) and l.get("name")]
        non_control_labels = [
            l for l in labels if l not in LABEL_TO_STATUS and not l.startswith("priority:")
        ]

        description = self._issue_to_task_description(issue, repo)
        context = {
            "github_repo": repo,
            "github_issue_number": int(number),
            "github_url": issue.get("html_url"),
            "github_synced_at": datetime.now(timezone.utc).isoformat(),
            "github_state": issue.get("state"),
            "github_assignees": [a.get("login") for a in issue.get("assignees", []) if isinstance(a, dict)],
        }

        if not existing:
            created_task = queue.add_task(
                description=description,
                priority=mapped_priority,
                assigned_to=mapped_assignee,
                tags=non_control_labels,
                ticket_ref=f"{repo}#{number}",
                project_id=project_id,
                project_name=project_name,
                context=context,
                provider="github",
                alias="github-sync",
            )
            if mapped_status != TaskStatus.INBOX.value:
                queue.update_task_status(created_task.id, TaskStatus.from_legacy(mapped_status))
            return "created"

        task = queue.get_task(existing)
        if not task:
            return "skipped"

        # Update mutable fields
        task.description = description
        task.priority = mapped_priority
        task.status = TaskStatus.from_legacy(mapped_status)
        task.assigned_to = mapped_assignee
        task.tags = non_control_labels
        task.ticket_ref = f"{repo}#{number}"

        merged_ctx = dict(task.context or {})
        merged_ctx.update(context)
        task.context = merged_ctx

        ok = queue.update_task(task)
        return "updated" if ok else "skipped"

    def build_issue_update_payload(self, task: Any, assignee_reverse_map: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Build GitHub issue update payload from local task."""
        status_value = task.status.value if hasattr(task.status, "value") else str(task.status)
        priority_value = task.priority.value if hasattr(task.priority, "value") else str(task.priority)

        labels = []
        if status_value in STATUS_TO_LABEL:
            labels.append(STATUS_TO_LABEL[status_value])
        labels.append(PRIORITY_TO_LABEL.get(priority_value, "priority:medium"))
        labels.extend(task.tags or [])

        payload: Dict[str, Any] = {
            "title": self._task_to_issue_title(task),
            "body": self._task_to_issue_body(task),
            "labels": labels,
            "state": "closed" if status_value == TaskStatus.DONE.value else "open",
        }

        if getattr(task, "assigned_to", None) and assignee_reverse_map:
            gh_login = assignee_reverse_map.get(task.assigned_to)
            if gh_login:
                payload["assignees"] = [gh_login]

        return payload

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "agent-nexus-sync",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _find_task_by_issue(self, repo: str, issue_number: int, exec_user: str) -> Optional[str]:
        # context_json stores github_repo/github_issue_number
        row = self._db.execute_fetchone(
            """
            SELECT id FROM tasks
            WHERE exec_user = ?
              AND (
                context_json LIKE ?
                OR context_json LIKE ?
              )
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (
                exec_user,
                f'%"github_repo": "{repo}"%"github_issue_number": {issue_number}%',
                f'%"github_repo": "{repo}"%"github_issue_number":{issue_number}%',
            ),
        )
        return str(row["id"]) if row and row.get("id") else None

    def _map_issue_status(self, issue: Dict[str, Any]) -> str:
        if issue.get("state") == "closed":
            return TaskStatus.DONE.value

        labels = [l.get("name", "") for l in issue.get("labels", []) if isinstance(l, dict)]
        for label in labels:
            if label in LABEL_TO_STATUS:
                return LABEL_TO_STATUS[label]
        return TaskStatus.INBOX.value

    @staticmethod
    def _map_issue_priority(issue: Dict[str, Any]) -> TaskPriority:
        labels = [l.get("name", "") for l in issue.get("labels", []) if isinstance(l, dict)]
        if "priority:critical" in labels or "priority:high" in labels:
            return TaskPriority.PROJECT
        if "priority:medium" in labels:
            return TaskPriority.SERIOUS
        return TaskPriority.THOUGHT

    @staticmethod
    def _map_assignee(issue: Dict[str, Any], assignee_map: Dict[str, str]) -> Optional[str]:
        assignees = issue.get("assignees", []) or []
        for assignee in assignees:
            if not isinstance(assignee, dict):
                continue
            login = assignee.get("login")
            if login and login in assignee_map:
                return assignee_map[login]
        return None

    @staticmethod
    def _issue_to_task_description(issue: Dict[str, Any], repo: str) -> str:
        title = str(issue.get("title") or "(no title)")
        body = str(issue.get("body") or "").strip()
        number = issue.get("number")
        header = f"[GitHub {repo}#{number}] {title}"
        return f"{header}\n\n{body}".strip()

    @staticmethod
    def _task_to_issue_title(task: Any) -> str:
        desc = (getattr(task, "description", "") or "").strip()
        first_line = desc.splitlines()[0] if desc else "Task"
        return first_line[:200]

    @staticmethod
    def _task_to_issue_body(task: Any) -> str:
        desc = (getattr(task, "description", "") or "").strip()
        return desc


_sync_service: Optional[GitHubIssueSync] = None


def get_github_sync() -> GitHubIssueSync:
    global _sync_service
    if _sync_service is None:
        _sync_service = GitHubIssueSync()
    return _sync_service

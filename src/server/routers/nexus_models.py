# -*- coding: utf-8 -*-
"""Shared Pydantic models and helpers for Nexus API routers.

Extracted from nexus.py to avoid duplication across sub-routers.
"""

from __future__ import annotations

import re
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field

from ..models import TaskStatus, TaskPriority


# ============ Response Models ============

class SuccessResponse(BaseModel):
    success: bool = True
    message: Optional[str] = None


class CancelResponse(BaseModel):
    success: bool = True
    cancelled: bool = False


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


class UsernamesResponse(BaseModel):
    usernames: list[str] = []


class AgentInfo(BaseModel):
    id: str
    username: str
    agent_type: str
    display_name: str
    available: bool = True


class AgentsResponse(BaseModel):
    agents: list[AgentInfo] = []


# ============ Session Models ============

class SessionBulkRequest(BaseModel):
    session_ids: List[str] = Field(default_factory=list)


class SessionBulkResponse(SuccessResponse):
    result: Dict[str, Any] = Field(default_factory=dict)


# ============ File Models ============

class FileItem(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: Optional[int] = None
    modified: Optional[str] = None


class SessionFilesResponse(BaseModel):
    session_id: str
    folder_path: str
    files: List[FileItem] = []


# ============ Task Models ============

class TaskItem(BaseModel):
    id: str
    description: str
    status: str
    priority: str
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    workspace: Optional[str] = None
    provider: Optional[str] = None
    alias: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    attempt_count: int = 0
    error_message: Optional[str] = None
    # Outcome tracking — ported from mission-control commit 6cf4256
    outcome: Optional[str] = None
    resolution: Optional[str] = None
    feedback_rating: Optional[int] = None
    feedback_notes: Optional[str] = None
    exec_user: Optional[str] = None
    session_id: Optional[str] = None
    depends_on: List[str] = Field(default_factory=list)
    # Ralph Loop fields
    loop_enabled: bool = False
    loop_iteration: int = 0
    loop_max_iterations: int = 1
    loop_keywords: List[str] = Field(default_factory=list)
    loop_keyword_found: bool = False
    # Derived overlay — not stored; computed from description keywords.
    # "waiting_for_owner" signals that the task is blocked on human action.
    # Ported from mission-control detectAwaitingOwner (commit fc4384b).
    effective_status: Optional[str] = None


class TaskListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    tasks: List[TaskItem] = []


class TaskBulkRequest(BaseModel):
    task_ids: List[str] = Field(default_factory=list)


class TaskBulkResponse(SuccessResponse):
    result: Dict[str, Any] = Field(default_factory=dict)


class ProjectItem(BaseModel):
    project_id: str
    project_name: str
    total_tasks: int
    pending: int = 0
    todo: int = 0
    in_progress: int = 0
    doing: int = 0
    completed: int = 0
    done: int = 0


class CreateTaskRequest(BaseModel):
    model_config = {"populate_by_name": True}

    description: str = Field(..., description="Task description")
    provider: Optional[str] = Field(None, description="Provider name (claude/gemini/codex/codebuddy)")
    alias: Optional[str] = Field(None, description="Alias (defaults to provider)")
    llm_model: Optional[str] = Field(None, alias="model", description="LLM model name (e.g., claude-opus-4.6, gemini-2.5-pro)")
    workspace: Optional[str] = Field(None, description="Execution workspace")
    project_name: Optional[str] = Field(None, description="Optional project name")
    project_id: Optional[str] = Field(None, description="Optional project id (slug)")
    exec_user: Optional[str] = Field(None, description="Execution user (optional)")
    source_session_id: Optional[str] = Field(None, description="Optional source session id")
    depends_on: Optional[List[str]] = Field(None, description="List of task IDs this task depends on")
    # Ralph Loop configuration
    loop_enabled: Optional[bool] = Field(False, description="Enable Ralph Loop mode")
    loop_max_iterations: Optional[int] = Field(None, ge=1, le=100, description="Max loop iterations (1-100)")
    loop_keywords: Optional[List[str]] = Field(None, description="Keywords to match in output (loop stops when found)")


class BulkCreateTaskRequest(BaseModel):
    """Batch create multiple tasks at once."""
    tasks: List[CreateTaskRequest] = Field(..., description="List of tasks to create (max 50)")


class BulkCreateTaskResponse(BaseModel):
    """Response for batch task creation."""
    success: bool = True
    created: List[TaskItem] = Field(default_factory=list)
    errors: List[Dict[str, str]] = Field(default_factory=list)


class UpdateTaskStatusRequest(BaseModel):
    status: str = Field(..., description="New task status (todo/doing/done/failed/cancelled/archived)")


class UpdateTaskOutcomeRequest(BaseModel):
    """Set or update the outcome of a completed task.

    Ported from mission-control commit 6cf4256.
    outcome: success | failed | partial | abandoned
    feedback_rating: 1-5 (optional human rating)
    """
    outcome: str = Field(..., description="Outcome: success | failed | partial | abandoned")
    resolution: Optional[str] = Field(None, description="Free-text resolution notes")
    feedback_rating: Optional[int] = Field(None, ge=1, le=5, description="Human rating 1-5")
    feedback_notes: Optional[str] = Field(None, description="Human feedback text")


class OutcomeBuckets(BaseModel):
    success: int = 0
    failed: int = 0
    partial: int = 0
    abandoned: int = 0
    unknown: int = 0


class OutcomesByDimension(OutcomeBuckets):
    total: int = 0
    success_rate: float = 0.0


class TaskOutcomeSummary(BaseModel):
    total_done: int = 0
    with_outcome: int = 0
    by_outcome: OutcomeBuckets = Field(default_factory=OutcomeBuckets)
    avg_attempt_count: float = 0.0
    avg_time_to_resolution_seconds: float = 0.0
    success_rate: float = 0.0


class TaskOutcomesResponse(BaseModel):
    """Analytics response for GET /api/nexus/tasks/outcomes.

    Ported from mission-control commit 6cf4256.
    """
    timeframe: str = "all"
    summary: TaskOutcomeSummary = Field(default_factory=TaskOutcomeSummary)
    by_provider: Dict[str, Any] = Field(default_factory=dict)
    by_priority: Dict[str, Any] = Field(default_factory=dict)
    common_errors: List[Dict[str, Any]] = Field(default_factory=list)
    record_count: int = 0


class ChatContinueRequest(BaseModel):
    message: str = Field(..., description="Follow-up message to send to the task")
    model: Optional[str] = Field(None, description="Override model for this run (optional)")


# ============ Skills Models ============

class SkillInfo(BaseModel):
    name: str
    description: str = ""
    version: str = ""
    provider: str = ""
    path: str = ""


class SkillsResponse(BaseModel):
    providers: Dict[str, List[SkillInfo]] = Field(default_factory=dict)


class CreateSkillRequest(BaseModel):
    provider: str = Field(..., description="Provider name (e.g. claude, codebuddy)")
    skill_name: str = Field(..., description="Skill directory name")
    description: str = Field("", description="Skill description")
    content: str = Field("", description="SKILL.md body content (markdown)")
    skills_path: Optional[str] = Field(None, description="Custom skills directory path (for aliases)")


# ============ Config Models ============

class ServerDefaultsResponse(BaseModel):
    exec_user: str = ""
    default_provider: str = ""
    default_alias: str = ""
    default_exec_user: str = ""


class ConcurrencyConfigResponse(BaseModel):
    global_max_concurrency: int = 0
    provider_concurrency: Dict[str, int] = Field(default_factory=dict)


class SetProviderConcurrencyRequest(BaseModel):
    name: str = Field(..., description="Provider or alias name")
    limit: int = Field(..., ge=0, description="Max concurrency (0 = remove limit)")


class SetGlobalConcurrencyRequest(BaseModel):
    limit: int = Field(..., ge=0, description="Global max concurrency (0 = unlimited)")


# ============ Shared Helper Functions ============


def get_task_queue(exec_user: str):
    """Create a TaskQueue instance for the given exec_user."""
    from ..services.task_storage import TaskQueue
    return TaskQueue(db_path=None, exec_user=exec_user)


def normalize_task_status(status_str: str) -> str:
    return status_str.strip().lower()


def task_updated_at(task) -> Optional[datetime]:
    """Compute task updated_at for UI.

    Rules:
    - If task is archived: prefer archived_at (so Archived column groups by archive date)
    - Otherwise: completed_at > started_at > created_at
    """
    status_raw = getattr(task, "status", None)
    if isinstance(status_raw, str):
        status_val = status_raw.lower()
    else:
        try:
            status_val = str(getattr(status_raw, "value", "")).lower()
        except Exception:
            status_val = str(status_raw or "").lower()

    if status_val == TaskStatus.ARCHIVED.value:
        candidates = (
            getattr(task, "archived_at", None),
            getattr(task, "completed_at", None),
            getattr(task, "started_at", None),
            getattr(task, "created_at", None),
        )
    else:
        candidates = (
            getattr(task, "completed_at", None),
            getattr(task, "started_at", None),
            getattr(task, "created_at", None),
        )

    for dt in candidates:
        if dt:
            return dt
    return None


# ---------------------------------------------------------------------------
# awaiting-owner detection
# Ported from mission-control task-board-panel.tsx detectAwaitingOwner (commit fc4384b).
# When a TODO or DOING task's description contains any of these phrases, it means
# the agent is blocked waiting for human action — surfaced as effective_status.
# ---------------------------------------------------------------------------

_WAITING_FOR_OWNER_KEYWORDS = [
    "waiting for",
    "waiting on",
    "needs human",
    "manual action",
    "account creation",
    "browser login",
    "approval needed",
    "owner action",
    "human required",
    "blocked on owner",
    "awaiting owner",
    "awaiting human",
    "needs owner",
]

_ACTIVE_STATUSES = {"todo", "doing"}


def detect_waiting_for_owner(task) -> bool:
    """Return True when the task appears to be blocked waiting for human action.

    Only triggers for active tasks (TODO/DOING) — completed/failed/cancelled
    tasks are not flagged regardless of description content.
    """
    raw_status = task.status if isinstance(task.status, str) else task.status.value
    if raw_status not in _ACTIVE_STATUSES:
        return False
    text = (getattr(task, "description", "") or "").lower()
    return any(kw in text for kw in _WAITING_FOR_OWNER_KEYWORDS)


def _str_or_none(val) -> Optional[str]:
    """Return val if it is a str, else None.  Protects TaskItem from MagicMock attrs in tests."""
    return val if isinstance(val, str) else None


def _int_or_none(val) -> Optional[int]:
    """Return val if it is an int, else None.  Protects TaskItem from MagicMock attrs in tests."""
    return val if isinstance(val, int) else None


# ---------------------------------------------------------------------------
# Task comment models
# Ported from mission-control GET/POST /api/tasks/[id]/comments (commit 4ef91d4).
# MC stores comments in SQLite; here we use Redis hashes + sorted sets.
# ---------------------------------------------------------------------------

class TaskComment(BaseModel):
    """A single comment (or reply) on a task."""
    id: str
    task_id: str
    author: str
    content: str
    created_at: float          # POSIX timestamp
    parent_id: Optional[str] = None
    replies: List["TaskComment"] = Field(default_factory=list)


class TaskCommentsResponse(BaseModel):
    task_id: str
    comments: List[TaskComment] = Field(default_factory=list)
    total: int = 0


class CreateCommentRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Comment text")
    author: str = Field(default="user", description="Author identifier")
    parent_id: Optional[str] = Field(None, description="ID of parent comment for replies")


def task_to_item(task) -> TaskItem:
    """Convert a storage Task to a TaskItem response model."""
    status_val = task.status if isinstance(task.status, str) else task.status.value
    priority_val = task.priority if isinstance(task.priority, str) else task.priority.value
    session_id = getattr(task, "session_id", None) or f"task_{task.id}"
    depends_on = getattr(task, "depends_on", None) or []
    effective_status = "waiting_for_owner" if detect_waiting_for_owner(task) else None
    return TaskItem(
        id=str(task.id),
        description=task.description,
        status=status_val,
        priority=priority_val,
        project_id=task.project_id,
        project_name=task.project_name,
        workspace=task.workspace,
        provider=getattr(task, "provider", None) or "claude",
        alias=getattr(task, "alias", None) or getattr(task, "provider", None) or "claude",
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        updated_at=task_updated_at(task),
        attempt_count=int(task.attempt_count or 0),
        error_message=task.error_message,
        outcome=_str_or_none(getattr(task, "outcome", None)),
        resolution=_str_or_none(getattr(task, "resolution", None)),
        feedback_rating=_int_or_none(getattr(task, "feedback_rating", None)),
        feedback_notes=_str_or_none(getattr(task, "feedback_notes", None)),
        exec_user=task.exec_user,
        session_id=session_id,
        depends_on=depends_on,
        loop_enabled=getattr(task, "loop_enabled", False),
        loop_iteration=getattr(task, "loop_iteration", 0),
        loop_max_iterations=getattr(task, "loop_max_iterations", 1),
        loop_keywords=getattr(task, "loop_keywords", []) or [],
        loop_keyword_found=getattr(task, "loop_keyword_found", False),
        effective_status=effective_status,
    )

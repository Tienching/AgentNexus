# -*- coding: utf-8 -*-
"""Shared Pydantic models and helpers for Nexus API routers.

Extracted from nexus.py to avoid duplication across sub-routers.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Iterable

from pydantic import BaseModel, Field

from ..models import TaskStatus
from ..services.history_service import get_history_service
from src.runtime.models.session import SessionListResponse as RuntimeSessionListResponse, SessionMeta, SessionStatus


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
    kind: str = "agent"
    identity: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    activity: dict[str, Any] = Field(default_factory=dict)
    cost: dict[str, Any] = Field(default_factory=dict)


class AgentsResponse(BaseModel):
    agents: list[AgentInfo] = []


class AgentBindingItem(BaseModel):
    agent_id: str
    provider: str
    alias: str
    model: str = ""
    workspace: str = ""
    memory_policy: str = "session"
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: float | None = None
    binding: dict[str, Any] = Field(default_factory=dict)
    identity: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    activity: dict[str, Any] = Field(default_factory=dict)
    cost: dict[str, Any] = Field(default_factory=dict)


class AgentBindingUpdateRequest(BaseModel):
    provider: Optional[str] = None
    alias: Optional[str] = None
    model: Optional[str] = None
    workspace: Optional[str] = None
    memory_policy: Optional[str] = None
    tools: Optional[list[str]] = None
    skills: Optional[list[str]] = None
    permissions: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None
    exec_user: Optional[str] = None
    runtime_profile: Optional[str] = None
    memory_scope: Optional[str] = None
    team_name: Optional[str] = None
    enabled: Optional[bool] = None
    auto_start: Optional[bool] = None
    notes: Optional[str] = None
    capabilities: Optional[list[str]] = None


class TeamConfigItem(BaseModel):
    team_name: str
    runtime: str = "swarm"
    default_provider: str = "claude"
    default_alias: str = "claude"
    memory_policy: str = "shared"
    coordination_mode: str = "mailbox"
    permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: float | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    identity: dict[str, Any] = Field(default_factory=dict)
    runtime_detail: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    activity: dict[str, Any] = Field(default_factory=dict)
    cost: dict[str, Any] = Field(default_factory=dict)
    members: list[dict[str, Any]] = Field(default_factory=list)


class TeamConfigUpdateRequest(BaseModel):
    runtime: Optional[str] = None
    default_provider: Optional[str] = None
    default_alias: Optional[str] = None
    memory_policy: Optional[str] = None
    coordination_mode: Optional[str] = None
    permissions: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None
    display_name: Optional[str] = None
    mission: Optional[str] = None
    workspace: Optional[str] = None
    lead_agent_id: Optional[str] = None
    member_agent_ids: Optional[list[str]] = None
    shared_memory_policy: Optional[str] = None
    auto_balance: Optional[bool] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None


class AgentOverviewSummary(BaseModel):
    total_agents: int = 0
    online_agents: int = 0
    busy_agents: int = 0
    offline_agents: int = 0
    teams_total: int = 0
    active_tasks: int = 0
    queue_depth: int = 0
    recent_failures: int = 0
    total_cost_usd: float = 0.0
    idle_agents: int = 0
    running_agents: int = 0
    error_agents: int = 0
    active_teams: int = 0
    total_tokens: int = 0
    recent_activity_count: int = 0


class AgentOverviewActivityItem(BaseModel):
    id: str
    title: str
    subtitle: str = ""
    timestamp: float | None = None
    level: str = "info"
    entity_type: str = ""
    entity_id: str = ""
    scope: str = "global"
    scope_id: str = ""
    detail: str = ""
    status: str = ""


class AgentOverviewTeamItem(BaseModel):
    team_name: str
    member_count: int = 0
    claimed_tasks: int = 0
    pending_messages: int = 0
    status: str = "idle"
    kind: str = "team"
    identity: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    activity: dict[str, Any] = Field(default_factory=dict)
    cost: dict[str, Any] = Field(default_factory=dict)
    members: list[dict[str, Any]] = Field(default_factory=list)


class AgentsOverviewResponse(BaseModel):
    summary: AgentOverviewSummary = Field(default_factory=AgentOverviewSummary)
    dashboard: AgentOverviewSummary = Field(default_factory=AgentOverviewSummary)
    agents: list[AgentInfo] = Field(default_factory=list)
    teams: list[AgentOverviewTeamItem] = Field(default_factory=list)
    recent_activity: list[AgentOverviewActivityItem] = Field(default_factory=list)
    recent_costs: list[dict[str, Any]] = Field(default_factory=list)
    costs: "CostSummaryResponse" = Field(default_factory=lambda: CostSummaryResponse())


# ============ Session Models ============

class SessionBulkRequest(BaseModel):
    session_ids: List[str] = Field(default_factory=list)


class CreateSessionRequest(BaseModel):
    """Request body for POST /api/nexus/sessions."""
    title: Optional[str] = Field(None, description="Session title")
    username: Optional[str] = Field(None, description="Username")
    exec_user: Optional[str] = Field(None, description="Linux exec user")
    provider: Optional[str] = Field(None, description="Provider (e.g. claude, codex)")
    alias: Optional[str] = Field(None, description="Alias (defaults to provider)")
    exec_dir: Optional[str] = Field(None, description="Working directory")
    prior_session_id: Optional[str] = Field(None, description="Explicit resume source session id")
    prior_work_dir: Optional[str] = Field(None, description="Explicit prior working directory")


class SessionBulkResponse(SuccessResponse):
    result: Dict[str, Any] = Field(default_factory=dict)


class HistorySessionSummary(SessionMeta):
    """Stable History summary DTO used by read-only lists and resume flows."""

    work_dir: Optional[str] = Field(None, description="Working directory for the history session")
    resumable: bool = Field(True, description="Whether the history session can be resumed")
    group_key: Optional[str] = Field(None, description="Normalized provider:alias grouping key")
    provider_rank: Optional[int] = Field(None, description="Provider rank in grouped History results")
    alias_rank: Optional[int] = Field(None, description="Alias rank within the provider group")


class HistoryAliasGroup(BaseModel):
    provider: str
    alias: str
    total_sessions: int = 0
    latest_updated_at: int = 0
    sessions: List[HistorySessionSummary] = Field(default_factory=list)


class HistoryProviderGroup(BaseModel):
    provider: str
    total_sessions: int = 0
    latest_updated_at: int = 0
    aliases: List[HistoryAliasGroup] = Field(default_factory=list)


class HistorySessionListResponse(RuntimeSessionListResponse):
    """History list response with provider/alias grouping metadata."""

    sessions: List[HistorySessionSummary] = Field(default_factory=list)
    groups: List[HistoryProviderGroup] = Field(default_factory=list)


class HistoryProjectProviderSummary(BaseModel):
    provider: str
    alias: str
    session_count: int = 0


class HistoryProjectSummary(BaseModel):
    path: str
    providers: List[HistoryProjectProviderSummary] = Field(default_factory=list)
    total_sessions: int = 0
    last_active: int = 0


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
    position: Optional[float] = None
    assigned_to: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    due_date: Optional[datetime] = None
    ticket_ref: Optional[str] = None
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
    runtime_status: Optional[str] = None
    runtime_orphaned: bool = False
    runtime_orphaned_at: Optional[datetime] = None
    runtime_last_heartbeat: Optional[datetime] = None
    # Outcome tracking — ported from mission-control commit 6cf4256
    outcome: Optional[str] = None
    resolution: Optional[str] = None
    feedback_rating: Optional[int] = None
    feedback_notes: Optional[str] = None
    exec_user: Optional[str] = None
    session_id: Optional[str] = None
    cli_session_id: Optional[str] = None
    source_session_id: Optional[str] = None
    prior_session_id: Optional[str] = None
    prior_work_dir: Optional[str] = None
    session_kind: Optional[str] = None
    depends_on: List[str] = Field(default_factory=list)
    repo_url: Optional[str] = None
    repo_root: Optional[str] = None
    worktree_path: Optional[str] = None
    # GitHub linkage (MC-041)
    github_repo: Optional[str] = None
    github_issue_number: Optional[int] = None
    github_url: Optional[str] = None
    github_state: Optional[str] = None
    # Aegis quality metadata (MC-044/MC-045)
    aegis_approved: bool = False
    aegis_status: Optional[str] = None
    aegis_reviewer: Optional[str] = None
    aegis_notes: Optional[str] = None
    aegis_reviewed_at: Optional[float] = None
    aegis_reason: Optional[str] = None
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
    # Task View Read Model fields (TV-001/TV-019)
    lane_status: Optional[str] = None
    review_state: Optional[str] = "none"
    display_status: Optional[str] = None
    display_group: Optional[str] = None
    is_terminal: bool = False
    is_active: bool = True


class TaskListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    tasks: List[TaskItem] = []

class TaskSummaryMetrics(BaseModel):
    """Summary metrics for the task workbench header strip (TV-019)."""
    total: int = 0
    active: int = 0
    running: int = 0
    reviewing: int = 0
    failed: int = 0
    cancelled: int = 0
    scheduled: int = 0


class TaskBulkRequest(BaseModel):
    task_ids: List[str] = Field(default_factory=list)


class TaskBulkResponse(SuccessResponse):
    result: Dict[str, Any] = Field(default_factory=dict)


class ProjectItem(BaseModel):
    project_id: str
    project_name: str
    total_tasks: int
    pending: int = 0
    running: int = 0
    in_review: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    archived: int = 0


class CreateTaskRequest(BaseModel):
    model_config = {"populate_by_name": True}

    description: str = Field(..., description="Task description")
    provider: Optional[str] = Field(None, description="Provider name (claude/codex/codebuddy/hermes)")
    alias: Optional[str] = Field(None, description="Alias (defaults to provider)")
    llm_model: Optional[str] = Field(None, alias="model", description="LLM model name (e.g., claude-opus-4.6, glm-5v-turbo)")
    workspace: Optional[str] = Field(None, description="Execution workspace")
    project_name: Optional[str] = Field(None, description="Optional project name")
    project_id: Optional[str] = Field(None, description="Optional project id (slug)")
    exec_user: Optional[str] = Field(None, description="Execution user (optional)")
    source_session_id: Optional[str] = Field(None, description="Optional source session id")
    prior_session_id: Optional[str] = Field(None, description="Explicit prior session id")
    prior_work_dir: Optional[str] = Field(None, description="Explicit prior working directory")
    repo_url: Optional[str] = Field(None, description="Repository URL for worktree handoff")
    repo_root: Optional[str] = Field(None, description="Repository root for worktree handoff")
    worktree_path: Optional[str] = Field(None, description="Resolved worktree path")
    session_id: Optional[str] = Field(None, description="Optional target existing session id")
    assigned_to: Optional[str] = Field(None, description="Optional assignee")
    tags: Optional[List[str]] = Field(None, description="Task tags")
    due_date: Optional[datetime] = Field(None, description="Optional due date")
    ticket_ref: Optional[str] = Field(None, description="External ticket reference")
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
    status: str = Field(
        ...,
        description="New task status (pending/running/in_review/completed/failed/cancelled/archived). Use cancelled only for pending/running tasks that should stop before natural completion.",
    )


class RequeueOrphanTaskRequest(BaseModel):
    reason: Optional[str] = Field(None, description="Optional requeue reason")


class UpdateTaskOutcomeRequest(BaseModel):
    """Set or update the outcome of a completed task.

    Ported from mission-control commit 6cf4256.
    outcome: success | failed | partial | abandoned
    feedback_rating: 1-5 (optional human rating)
    """
    outcome: str = Field(..., description="Outcome: success | failed | partial | abandoned")
    resolution: Optional[str] = Field(None, description="Free-text resolution notes")
    feedback_rating: Optional[int] = Field(None, ge=1, le=5, description="Human rating 1-5")
    feedback_notes: Optional[str] = Field(None, description="Optional human feedback notes")


class UpdateTaskRequest(BaseModel):
    """Update arbitrary task fields. Status changes should use UpdateTaskStatusRequest."""
    priority: Optional[str] = Field(None, description="Task priority: thought | serious | project | generated")
    assignee: Optional[str] = Field(None, description="Assignee name or ID")
    position: Optional[float] = Field(None, description="Float position for ordering")
    title: Optional[str] = Field(None, description="Task title")
    description: Optional[str] = Field(None, description="Task description")
    due_date: Optional[str] = Field(None, description="Due date (ISO format)")
    labels: Optional[list] = Field(None, description="Task labels/tags")
    feedback_notes: Optional[str] = Field(None, description="Human feedback text")
    session_id: Optional[str] = Field(None, description="Optional target existing session id")
    source_session_id: Optional[str] = Field(None, description="Optional source session id")
    prior_session_id: Optional[str] = Field(None, description="Explicit prior session id")
    prior_work_dir: Optional[str] = Field(None, description="Explicit prior working directory")
    repo_url: Optional[str] = Field(None, description="Repository URL for handoff")
    repo_root: Optional[str] = Field(None, description="Repository root for handoff")
    worktree_path: Optional[str] = Field(None, description="Worktree path for handoff")


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
    current_workdir: str = ""


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
    from ..services.task_storage import get_task_queue as _get_task_queue

    return _get_task_queue(exec_user)


def normalize_task_status(status_str: str) -> str:
    normalized = status_str.strip().lower()
    legacy_map = {
        # New canonical values pass through
        "pending": "pending",
        "running": "running",
        "in_review": "in_review",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "archived": "archived",
        # Old 10-status model mappings
        "inbox": "pending",
        "assigned": "pending",
        "awaiting_owner": "pending",
        "in_progress": "running",
        "review": "in_review",
        "quality_review": "in_review",
        "done": "completed",
        # Legacy aliases
        "todo": "pending",
        "doing": "running",
        # Runtime-only status
        "orphaned": "pending",
    }
    return legacy_map.get(normalized, normalized)


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

_ACTIVE_STATUSES = {"pending", "running", "in_review", "completed", "failed", "cancelled"}


def detect_waiting_for_owner(task) -> bool:
    """Return True when the task appears to be blocked waiting for human action.

    Only triggers for PENDING and RUNNING tasks — completed/failed/cancelled
    tasks are not flagged regardless of description content.
    """
    raw_status = task.status if isinstance(task.status, str) else task.status.value
    normalized = normalize_task_status(raw_status)
    if normalized not in ("pending", "running"):
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
    mentions: List[str] = Field(default_factory=list)
    replies: List["TaskComment"] = Field(default_factory=list)


class TaskCommentsResponse(BaseModel):
    task_id: str
    comments: List[TaskComment] = Field(default_factory=list)
    total: int = 0


class CreateCommentRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Comment text")
    author: str = Field(default="user", description="Author identifier")
    parent_id: Optional[str] = Field(None, description="ID of parent comment for replies")


class QualityReviewItem(BaseModel):
    id: int
    task_id: str
    reviewer: str
    status: str
    notes: str = ""
    created_at: float


class TaskQualityReviewsResponse(BaseModel):
    task_id: str
    gate_allowed: bool = False
    gate_reason: str = ""
    latest_review: Optional[QualityReviewItem] = None
    reviews: List[QualityReviewItem] = Field(default_factory=list)


class SubmitQualityReviewRequest(BaseModel):
    reviewer: str = Field(default="aegis", description="Reviewer identifier")
    status: str = Field(..., description="approved | rejected | needs_changes")
    notes: Optional[str] = Field(default="", description="Review notes")


class BroadcastTaskRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Broadcast message")
    sender: str = Field(default="user", description="Sender identifier")
    include_assignee: bool = Field(default=True, description="Include task assignee in recipients")


class BroadcastTaskResponse(BaseModel):
    task_id: str
    recipients: List[str] = Field(default_factory=list)
    delivered: int = 0


class TaskTimelineEvent(BaseModel):
    id: Optional[int] = None
    event_type: str
    aggregate_type: str
    aggregate_id: str
    actor: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    workspace_id: Optional[str] = None
    tenant_id: Optional[str] = None
    created_at: float


class TaskTimelineResponse(BaseModel):
    task_id: str
    total: int = 0
    events: List[TaskTimelineEvent] = Field(default_factory=list)


class CostBreakdownItem(BaseModel):
    key: str
    count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0


class CostSummaryResponse(BaseModel):
    total_requests: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    by_workspace: List[CostBreakdownItem] = Field(default_factory=list)
    by_agent: List[CostBreakdownItem] = Field(default_factory=list)
    by_runtime: List[CostBreakdownItem] = Field(default_factory=list)


def extract_mentions(content: str) -> List[str]:
    """Extract @mentions from comment content, preserving order and uniqueness."""
    if not content:
        return []
    hits = re.findall(r"(?:^|[\s\(\[\{])@([A-Za-z0-9_.-]{1,64})", content)
    seen = set()
    ordered: List[str] = []
    for h in hits:
        key = h.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def build_history_session_summary(
    session: SessionMeta,
    *,
    resumable: bool = True,
    group_key: Optional[str] = None,
    provider_rank: Optional[int] = None,
    alias_rank: Optional[int] = None,
) -> HistorySessionSummary:
    """Convert a SessionMeta into a stable HistorySessionSummary DTO."""
    summary_data = get_history_service().summarize_history_session(session, resumable=resumable)
    raw_status = summary_data.get("status")
    if isinstance(raw_status, SessionStatus):
        status = raw_status
    elif isinstance(raw_status, str):
        try:
            status = SessionStatus(raw_status)
        except Exception:
            status = SessionStatus.IDLE
    else:
        status = SessionStatus.IDLE

    return HistorySessionSummary(
        id=str(summary_data.get("id", "")),
        thread_id=_str_or_none(summary_data.get("thread_id")) or str(summary_data.get("id", "")),
        run_id=_str_or_none(summary_data.get("run_id")),
        title=_str_or_none(summary_data.get("title")) or "New Session",
        username=_str_or_none(summary_data.get("username")) or "",
        exec_user=_str_or_none(summary_data.get("exec_user")),
        provider=_str_or_none(summary_data.get("provider")) or "unknown",
        alias=_str_or_none(summary_data.get("alias")) or _str_or_none(summary_data.get("provider")) or "unknown",
        created_at=_int_or_none(summary_data.get("created_at")) or _int_or_none(summary_data.get("updated_at")) or 0,
        updated_at=_int_or_none(summary_data.get("updated_at")) or 0,
        message_count=int(summary_data.get("message_count", 0) or 0),
        status=status,
        source=_str_or_none(summary_data.get("source")),
        exec_dir=_str_or_none(summary_data.get("exec_dir")),
        task_id=_str_or_none(summary_data.get("task_id")),
        source_session_id=_str_or_none(summary_data.get("source_session_id")),
        session_kind=_str_or_none(summary_data.get("session_kind")),
        execution_binding=getattr(session, "execution_binding", None),
        work_dir=_str_or_none(summary_data.get("work_dir")),
        resumable=bool(resumable),
        group_key=group_key or _str_or_none(summary_data.get("group_key")) or "unknown:unknown",
        provider_rank=provider_rank,
        alias_rank=alias_rank,
    )


def group_history_session_summaries(
    sessions: Iterable[HistorySessionSummary],
) -> List[HistoryProviderGroup]:
    """Group history sessions by provider → alias with recency-aware ordering."""
    service = get_history_service()
    session_models: List[SessionMeta] = []
    summary_by_id: Dict[str, HistorySessionSummary] = {}

    for summary in sessions:
        raw_status = summary.status.value if isinstance(summary.status, SessionStatus) else str(summary.status or "idle")
        session_models.append(
            SessionMeta(
                id=summary.id,
                thread_id=summary.thread_id,
                run_id=summary.run_id,
                title=summary.title,
                username=summary.username,
                exec_user=summary.exec_user,
                provider=summary.provider,
                alias=summary.alias,
                created_at=summary.created_at,
                updated_at=summary.updated_at,
                message_count=summary.message_count,
                status=raw_status,
                source=summary.source,
                exec_dir=summary.exec_dir,
                task_id=summary.task_id,
                source_session_id=summary.source_session_id,
                session_kind=summary.session_kind,
                execution_binding=summary.execution_binding,
            )
        )
        summary_by_id[summary.id] = summary

    groups: List[HistoryProviderGroup] = []
    for provider_group in service.group_history_session_summaries(session_models):
        alias_groups: List[HistoryAliasGroup] = []
        for alias_group in provider_group.get("aliases", []):
            alias_sessions: List[HistorySessionSummary] = []
            for payload in alias_group.get("sessions", []):
                summary = summary_by_id.get(str(payload.get("id")))
                if summary is None:
                    continue
                summary.provider_rank = payload.get("provider_rank")
                summary.alias_rank = payload.get("alias_rank")
                alias_sessions.append(summary)
            alias_groups.append(
                HistoryAliasGroup(
                    provider=str(alias_group.get("provider", "unknown")),
                    alias=str(alias_group.get("alias", "unknown")),
                    total_sessions=int(alias_group.get("total_sessions", len(alias_sessions)) or 0),
                    latest_updated_at=int(alias_group.get("latest_updated_at", 0) or 0),
                    sessions=alias_sessions,
                )
            )
        groups.append(
            HistoryProviderGroup(
                provider=str(provider_group.get("provider", "unknown")),
                total_sessions=int(provider_group.get("total_sessions", 0) or 0),
                latest_updated_at=int(provider_group.get("latest_updated_at", 0) or 0),
                aliases=alias_groups,
            )
        )

    return groups


def task_to_item(task, latest_quality_review=None, gate_allowed: Optional[bool] = None, gate_reason: Optional[str] = None) -> TaskItem:
    """Convert a storage Task to a TaskItem response model."""
    binding = None
    try:
        from ..services.session_storage import get_session_storage
        binding = get_session_storage().get_execution_binding(getattr(task, "session_id", None) or f"task_{task.id}")
    except Exception:
        binding = None

    status_val = task.status if isinstance(task.status, str) else task.status.value
    priority_val = task.priority if isinstance(task.priority, str) else task.priority.value
    session_id = getattr(task, "session_id", None) or f"task_{task.id}"
    source_session_id = _str_or_none(getattr(task, "source_session_id", None))
    context = getattr(task, "context", None)
    if not isinstance(context, dict):
        context = {}
    prior_session_id = _str_or_none(
        getattr(task, "prior_session_id", None)
        or (context.get("prior_session_id") if isinstance(context, dict) else None)
        or source_session_id
    )
    prior_work_dir = _str_or_none(
        getattr(task, "prior_work_dir", None)
        or (context.get("prior_work_dir") if isinstance(context, dict) else None)
        or getattr(task, "workspace", None)
    )
    repo_url = _str_or_none(
        getattr(task, "repo_url", None)
        or (context.get("repo_url") if isinstance(context, dict) else None)
        or (context.get("github_repo") if isinstance(context, dict) else None)
    )
    repo_root = _str_or_none(
        getattr(task, "repo_root", None)
        or (context.get("repo_root") if isinstance(context, dict) else None)
    )
    worktree_path = _str_or_none(
        getattr(task, "worktree_path", None)
        or (context.get("worktree_path") if isinstance(context, dict) else None)
        or getattr(task, "workspace", None)
    )
    execution_binding = getattr(task, "execution_binding", None)
    cli_session_id = _str_or_none(
        getattr(task, "cli_session_id", None)
        or getattr(task, "claude_session_id", None)
        or getattr(execution_binding, "cli_session_id", None)
        or getattr(binding, "cli_session_id", None)
    )
    session_kind = (
        _str_or_none(getattr(task, "session_kind", None))
        or _str_or_none(getattr(execution_binding, "session_kind", None))
        or _str_or_none(getattr(binding, "session_kind", None))
        or ("task" if str(session_id).startswith("task_") else None)
    )
    depends_on = getattr(task, "depends_on", None) or []
    effective_status = "waiting_for_owner" if detect_waiting_for_owner(task) else None
    position = context.get("position")
    try:
        position = float(position) if position is not None else None
    except Exception:
        position = None

    github_repo = _str_or_none(context.get("github_repo"))
    github_issue_number = _int_or_none(context.get("github_issue_number"))
    github_url = _str_or_none(context.get("github_url"))
    github_state = _str_or_none(context.get("github_state"))

    aegis_status = None
    aegis_reviewer = None
    aegis_notes = None
    aegis_reviewed_at = None
    aegis_approved = False
    if latest_quality_review is not None:
        status_obj = getattr(latest_quality_review, "status", None)
        aegis_status = status_obj.value if hasattr(status_obj, "value") else _str_or_none(status_obj)
        aegis_reviewer = _str_or_none(getattr(latest_quality_review, "reviewer", None))
        aegis_notes = _str_or_none(getattr(latest_quality_review, "notes", None))
        try:
            created_at_raw = getattr(latest_quality_review, "created_at", None)
            aegis_reviewed_at = float(created_at_raw) if created_at_raw is not None else None
        except Exception:
            aegis_reviewed_at = None

    if gate_allowed is not None:
        aegis_approved = bool(gate_allowed)
    elif aegis_status:
        aegis_approved = aegis_status == "approved"

    # Read-model fields (TV-001/TV-019)
    lane_status = normalize_task_status(status_val)
    review_state = "none"
    if aegis_status:
        if aegis_status in ("approved", "rejected"):
            review_state = aegis_status
        else:
            review_state = "requested"
    elif aegis_approved:
        review_state = "approved"

    # Netharness layout: 6 active columns + archived (toggleable)
    _PRIMARY_STATUSES = {"pending", "running", "in_review", "completed", "failed", "cancelled"}
    _TERMINAL_STATUSES = {"archived"}
    display_group = "terminal" if lane_status in _TERMINAL_STATUSES else "primary"
    is_terminal = lane_status in _TERMINAL_STATUSES
    is_active = lane_status in _PRIMARY_STATUSES

    # Compute display_status: status + review_state overlay
    display_status = lane_status
    if review_state != "none" and lane_status not in _TERMINAL_STATUSES:
        display_status = f"{lane_status}:{review_state}"

    return TaskItem(
        id=str(task.id),
        description=task.description,
        status=status_val,
        priority=priority_val,
        position=position,
        assigned_to=_str_or_none(getattr(task, "assigned_to", None)),
        tags=getattr(task, "tags", []) or [],
        due_date=getattr(task, "due_date", None),
        ticket_ref=_str_or_none(getattr(task, "ticket_ref", None)),
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
        runtime_status=_str_or_none(getattr(task, "runtime_status", None)),
        runtime_orphaned=bool(getattr(task, "runtime_orphaned", False)),
        runtime_orphaned_at=getattr(task, "runtime_orphaned_at", None),
        runtime_last_heartbeat=getattr(task, "runtime_last_heartbeat", None),
        outcome=_str_or_none(getattr(task, "outcome", None)),
        resolution=_str_or_none(getattr(task, "resolution", None)),
        feedback_rating=_int_or_none(getattr(task, "feedback_rating", None)),
        feedback_notes=_str_or_none(getattr(task, "feedback_notes", None)),
        exec_user=task.exec_user,
        session_id=session_id,
        cli_session_id=cli_session_id,
        source_session_id=source_session_id,
        prior_session_id=prior_session_id,
        prior_work_dir=prior_work_dir,
        session_kind=session_kind,
        depends_on=depends_on,
        repo_url=repo_url,
        repo_root=repo_root,
        worktree_path=worktree_path,
        github_repo=github_repo,
        github_issue_number=github_issue_number,
        github_url=github_url,
        github_state=github_state,
        aegis_approved=aegis_approved,
        aegis_status=aegis_status,
        aegis_reviewer=aegis_reviewer,
        aegis_notes=aegis_notes,
        aegis_reviewed_at=aegis_reviewed_at,
        aegis_reason=gate_reason,
        loop_enabled=getattr(task, "loop_enabled", False),
        loop_iteration=getattr(task, "loop_iteration", 0),
        loop_max_iterations=getattr(task, "loop_max_iterations", 1),
        loop_keywords=getattr(task, "loop_keywords", []) or [],
        loop_keyword_found=getattr(task, "loop_keyword_found", False),
        effective_status=effective_status,
        lane_status=lane_status,
        review_state=review_state,
        display_status=display_status,
        display_group=display_group,
        is_terminal=is_terminal,
        is_active=is_active,
    )


def assemble_task_items(
    tasks: Iterable[Any],
    latest_quality_reviews: Optional[Dict[str, Any]] = None,
    gate_allowed_by_task_id: Optional[Dict[str, Optional[bool]]] = None,
    gate_reason_by_task_id: Optional[Dict[str, str]] = None,
) -> List[TaskItem]:
    """Build UI task read models in one place.

    Callers can prefetch reviews and pass them in batches to avoid scattering
    read-model composition logic across routers.
    """
    latest_quality_reviews = latest_quality_reviews or {}
    gate_allowed_by_task_id = gate_allowed_by_task_id or {}
    gate_reason_by_task_id = gate_reason_by_task_id or {}

    items: List[TaskItem] = []
    for task in tasks or []:
        task_id = str(getattr(task, "id", ""))
        latest = latest_quality_reviews.get(task_id)
        gate_allowed = gate_allowed_by_task_id.get(task_id)
        gate_reason = gate_reason_by_task_id.get(task_id)
        items.append(
            task_to_item(
                task,
                latest_quality_review=latest,
                gate_allowed=gate_allowed,
                gate_reason=gate_reason,
            )
        )
    return items

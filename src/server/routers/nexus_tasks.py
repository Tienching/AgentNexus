# -*- coding: utf-8 -*-
"""Nexus Tasks API Router

Provides REST API endpoints for task management:
- List tasks with pagination/filtering
- Create tasks (single and bulk)
- Get task details
- Update task status
- Continue chat on a task
- Bulk archive/unarchive/clear/delete tasks
- Get task AG-UI messages (conversation log)
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from ..config import settings
from src.runtime.events.agui import AGUIMessage, MessageRole, MessagesSnapshotEvent
from ..models import (
    TaskStatus,
    TaskPriority,
)
from ..services.user_directory import UserDirectoryManager
from ..services.workspace_validation import normalize_workspace_path
from src.runtime.commands.slash.handler import slugify_project
from src.core.quality.gates import ReviewStatus, get_quality_gate
from src.core.notifications.broadcast import broadcast_to_recipients, normalize_recipients
from src.core.cost.tracker import get_token_tracker
from ..providers import get_provider_registry
from ..services.schedule_storage import ScheduleStorage
from ..services.session_storage import get_session_storage
from ..services.domain_events import query_domain_events
from ..logger import get_logger
from .nexus_auth import verify_nexus_auth
from .nexus_models import (
    SuccessResponse,
    TaskItem,
    TaskListResponse,
    TaskSummaryMetrics,
    TaskBulkRequest,
    TaskBulkResponse,
    ProjectItem,
    CreateTaskRequest,
    BulkCreateTaskRequest,
    BulkCreateTaskResponse,
    UpdateTaskStatusRequest,
    UpdateTaskRequest,
    RequeueOrphanTaskRequest,
    UpdateTaskOutcomeRequest,
    TaskOutcomesResponse,
    TaskOutcomeSummary,
    ChatContinueRequest,
    TaskComment,
    TaskCommentsResponse,
    CreateCommentRequest,
    QualityReviewItem,
    TaskQualityReviewsResponse,
    SubmitQualityReviewRequest,
    BroadcastTaskRequest,
    BroadcastTaskResponse,
    TaskTimelineEvent,
    TaskTimelineResponse,
    CostSummaryResponse,
    CostBreakdownItem,
    get_task_queue,
    normalize_task_status,
    task_to_item,
    assemble_task_items,
    extract_mentions,
)

logger = get_logger(__name__)
_user_dir_manager = UserDirectoryManager(settings)


def _normalize_workspace_or_400(workspace: Optional[str]) -> Optional[str]:
    try:
        return normalize_workspace_path(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _parse_due_date_or_400(raw_value: Any) -> Optional[datetime]:
    if raw_value in (None, "", []):
        return None
    if isinstance(raw_value, datetime):
        return raw_value
    if isinstance(raw_value, (int, float)):
        return datetime.fromtimestamp(float(raw_value), tz=timezone.utc)
    value = str(raw_value).strip()
    if not value:
        return None
    try:
        if re.fullmatch(r"-?\d+(\.\d+)?", value):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        return datetime.fromisoformat(value)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid due_date: {raw_value}") from exc

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-tasks"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ============ Task Helper Functions ============


def _task_gate_maps(
    tasks: List[Any],
    *,
    workspace_id: int = 1,
) -> tuple[Dict[str, Any], Dict[str, bool], Dict[str, str]]:
    """Prefetch quality-gate read-model inputs for a batch of tasks."""
    quality_gate = get_quality_gate()
    task_ids = [str(getattr(task, "id", "")) for task in tasks if getattr(task, "id", None)]
    latest_reviews = quality_gate.get_latest_by_tasks(task_ids, workspace_id=workspace_id) if task_ids else {}
    gate_allowed_by_task_id: Dict[str, bool] = {}
    gate_reason_by_task_id: Dict[str, str] = {}

    for task_id in task_ids:
        latest = latest_reviews.get(task_id)
        status_obj = getattr(latest, "status", None) if latest is not None else None
        status_value = (
            status_obj.value if hasattr(status_obj, "value") else (str(status_obj) if status_obj else None)
        )
        allowed = status_value == ReviewStatus.APPROVED.value if status_value else False
        reason = (
            "Quality review approved"
            if allowed
            else (f"Latest quality review status: {status_value}" if status_value else "No quality review found")
        )
        gate_allowed_by_task_id[task_id] = allowed
        gate_reason_by_task_id[task_id] = reason

    return latest_reviews, gate_allowed_by_task_id, gate_reason_by_task_id


def _assemble_task_read_models(tasks: List[Any], *, workspace_id: int = 1) -> List[TaskItem]:
    latest_reviews, gate_allowed_by_task_id, gate_reason_by_task_id = _task_gate_maps(
        tasks,
        workspace_id=workspace_id,
    )
    return assemble_task_items(
        tasks,
        latest_quality_reviews=latest_reviews,
        gate_allowed_by_task_id=gate_allowed_by_task_id,
        gate_reason_by_task_id=gate_reason_by_task_id,
    )


def _assemble_task_read_model(task: Any, *, workspace_id: int = 1) -> TaskItem:
    items = _assemble_task_read_models([task], workspace_id=workspace_id)
    if not items:
        return task_to_item(task)
    return items[0]


def _resolve_task_conversation_log_path(exec_user: str, task_id: str, task=None) -> Path:
    """Resolve task conversation log path.

    Prefers the real `session_id` and `exec_user` from task metadata,
    falls back to legacy session naming for old tasks/directory layouts.
    """
    resolved_exec_user = (getattr(task, "exec_user", None) or exec_user or "").strip() or exec_user
    resolved_session_id = (getattr(task, "session_id", None) or "").strip() or None
    session_dir, actual_session_id, used_legacy_fallback = _user_dir_manager.resolve_task_session_directory(
        resolved_exec_user,
        task_id,
        resolved_session_id,
    )
    if used_legacy_fallback:
        logger.info(
            "Resolved task conversation log via legacy session fallback",
            extra={
                "task_id": task_id,
                "exec_user": resolved_exec_user,
                "resolved_session_id": actual_session_id,
            },
        )
    return session_dir / ".claude" / "conversation.json"


def _sanitize_text(text: str) -> str:
    """Best-effort content sanitization.

    Some runs wrap output entirely in `<think>...</think>`.
    If removing think sections results in empty text, fall back to original.
    """
    if not text:
        return ""

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"</?think>", "", cleaned)
    cleaned = cleaned.strip()
    return cleaned if cleaned else text


def _extract_content_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif item.get("type") == "tool_use":
                    parts.append(f"[调用工具: {item.get('name', 'unknown')}]")
                else:
                    # best-effort fallback
                    parts.append(json.dumps(item, ensure_ascii=False))
            elif isinstance(item, str):
                parts.append(item)
            else:
                parts.append(str(item))
        return "\n".join([p for p in parts if p is not None])
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _domain_event_to_timeline_item(event) -> TaskTimelineEvent:
    payload = getattr(event, "payload", None) or {}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    return TaskTimelineEvent(
        id=getattr(event, "id", None),
        event_type=str(getattr(event, "event_type", "") or ""),
        aggregate_type=str(getattr(event, "aggregate_type", "") or ""),
        aggregate_id=str(getattr(event, "aggregate_id", "") or ""),
        actor=str(getattr(event, "actor", "") or "") or None,
        payload=payload,
        workspace_id=str(getattr(event, "workspace_id", "") or "") or None,
        tenant_id=str(getattr(event, "tenant_id", "") or "") or None,
        created_at=float(getattr(event, "created_at", time.time()) or time.time()),
    )


def _parse_task_conversation(conversation_obj) -> List[AGUIMessage]:
    messages_obj = conversation_obj
    if isinstance(conversation_obj, dict):
        messages_obj = conversation_obj.get("messages", [])

    if not isinstance(messages_obj, list):
        return []

    result: List[AGUIMessage] = []
    for idx, msg in enumerate(messages_obj):
        if not isinstance(msg, dict):
            continue
        role_raw = (msg.get("role") or "assistant").lower()
        if role_raw not in ("user", "assistant", "system", "tool"):
            role_raw = "assistant"
        role = MessageRole(role_raw)

        content_text = _sanitize_text(_extract_content_text(msg.get("content")))
        created_at = msg.get("timestamp")
        result.append(
            AGUIMessage(
                id=f"taskmsg_{idx}",
                role=role,
                content=content_text,
                createdAt=created_at if isinstance(created_at, str) else None,
            )
        )

    return result


# ============ Projects API ============


@router.get("/projects", response_model=List[ProjectItem])
async def list_projects(exec_user: str = Query(settings.exec_user, description="Exec user for task isolation")):
    """Get all unique projects from existing tasks."""
    queue = get_task_queue(exec_user)
    return queue.get_projects()


# ============ Task CRUD API ============


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=500, description="Page size (max: 500)"),
    status_param: Optional[str] = Query(None, alias="status", description="Filter by status"),
    project_id: Optional[str] = Query(None, description="Filter by project_id"),
    workspace: Optional[str] = Query(None, description="Filter by workspace"),
    search: Optional[str] = Query(None, description="Search term for tasks"),
):
    """List tasks with pagination and filtering."""
    status_filter: Optional[str] = None
    if status_param:
        status_filter = normalize_task_status(status_param)
        allowed = {s.value for s in TaskStatus}
        if status_filter not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status_param}. Must be one of: {', '.join(sorted(allowed))}",
            )

    queue = get_task_queue(exec_user)
    tasks, total = queue.list_tasks(
        page=page,
        page_size=page_size,
        status=status_filter,
        project_id=project_id,
        workspace=workspace,
        search=search,
    )

    enriched_items = _assemble_task_read_models(tasks, workspace_id=1)

    return TaskListResponse(
        total=total,
        page=page,
        page_size=page_size,
        tasks=enriched_items,
    )

@router.get("/tasks/summary", response_model=TaskSummaryMetrics)
async def get_task_summary(exec_user: str = Query(None)):
    """Return summary metrics for the task workbench header strip."""
    effective_exec_user = exec_user or settings.exec_user
    queue = get_task_queue(effective_exec_user)
    try:
        page = 1
        page_size = 500
        all_tasks: list[Any] = []
        total = 0
        while page <= 25:
            batch, total = queue.list_tasks(page=page, page_size=page_size)
            batch = list(batch or [])
            all_tasks.extend(batch)
            if not batch or len(all_tasks) >= total:
                break
            page += 1
    except Exception:
        return TaskSummaryMetrics()

    items = assemble_task_items(all_tasks)
    active = [t for t in items if t.lane_status in {"pending", "running", "in_review"}]
    running = [t for t in items if t.lane_status == "running"]
    reviewing = [t for t in items if t.lane_status == "in_review"]
    failed = [t for t in items if t.lane_status == "failed"]
    cancelled = [t for t in items if t.lane_status == "cancelled"]
    scheduled = 0
    try:
        _, scheduled = ScheduleStorage(exec_user=effective_exec_user).list_schedules(
            page=1,
            page_size=1,
            status="active",
        )
    except Exception:
        scheduled = 0

    return TaskSummaryMetrics(
        total=len(items),
        active=len(active),
        running=len(running),
        reviewing=len(reviewing),
        failed=len(failed),
        cancelled=len(cancelled),
        scheduled=scheduled,
    )


@router.get("/tasks/{task_id}", response_model=TaskItem)
async def get_task(task_id: str, exec_user: str = Query(settings.exec_user, description="Exec user for task isolation")):
    """Get a single task detail."""
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")

    return _assemble_task_read_model(task, workspace_id=1)


@router.post("/tasks", response_model=TaskItem)
async def create_task(
    request: CreateTaskRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Create a task (used by Nexus UI).

    Provider is pinned at creation time and stored in task data.
    """
    desc = (request.description or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="description is required")

    default_provider = (settings.default_provider or "").strip().lower() or "codebuddy"
    default_alias = (settings.default_alias or "").strip().lower()
    allowed = list(get_provider_registry().list_providers())

    if (request.provider or "").strip():
        # Caller explicitly chose a provider — validate and use it
        provider = request.provider.strip().lower()
        if provider not in set(allowed):
            raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}")
    else:
        # Auto-select: score available providers by task keyword affinity.
        # Ported from mission-control autoRouteInboxTasks (commit 1acbf8e).
        from src.server.services.task_execution_service import select_provider_for_task
        auto = select_provider_for_task(desc, allowed) if allowed else None
        provider = auto or default_provider
        if provider not in set(allowed):
            provider = default_provider  # final safety fallback

    alias_value = (request.alias or "").strip() or default_alias or provider

    default_exec_user = (settings.default_exec_user or "").strip() or None
    effective_exec_user = (request.exec_user or "").strip() or default_exec_user

    project_name = (request.project_name or "").strip() or None
    project_id = (request.project_id or "").strip() or None
    if project_name and not project_id:
        project_id = slugify_project(project_name)

    priority = TaskPriority.PROJECT if (project_name or project_id) else TaskPriority.THOUGHT
    normalized_workspace = _normalize_workspace_or_400(request.workspace)

    queue = get_task_queue(exec_user)
    task = queue.add_task(
        description=desc,
        priority=priority,
        project_id=project_id,
        project_name=project_name,
        workspace=normalized_workspace,
        provider=provider,
        alias=alias_value,
        model=(request.llm_model or "").strip() or None,
        source_session_id=(request.source_session_id or "").strip() or None,
        prior_session_id=(request.prior_session_id or "").strip() or None,
        prior_work_dir=(request.prior_work_dir or "").strip() or None,
        repo_url=(request.repo_url or "").strip() or None,
        repo_root=(request.repo_root or "").strip() or None,
        worktree_path=(request.worktree_path or "").strip() or None,
        session_id=(request.session_id or "").strip() or None,
        exec_user=effective_exec_user,
        assigned_to=(request.assigned_to or "").strip() or None,
        tags=request.tags or [],
        due_date=request.due_date,
        ticket_ref=(request.ticket_ref or "").strip() or None,
        depends_on=request.depends_on or [],
        loop_enabled=bool(request.loop_enabled),
        loop_max_iterations=request.loop_max_iterations or 1,
        loop_keywords=request.loop_keywords or [],
    )

    try:
        get_session_storage().upsert_execution_binding(
            session_id=task.session_id or f"task_{task.id}",
            provider=provider,
            alias=alias_value,
            exec_user=effective_exec_user,
            work_dir=normalized_workspace,
            source_type="task",
            source_session_id=((request.prior_session_id or "").strip() or (request.source_session_id or "").strip() or None),
            task_id=task.id,
            session_kind="task",
        )
    except Exception as e:
        logger.debug(f"Failed to seed execution binding for task {task.id}: {e}")

    try:
        from ..services.worktree_registry import get_repo_worktree_registry

        if any([request.repo_url, request.repo_root, request.worktree_path, request.prior_session_id, request.prior_work_dir]):
            get_repo_worktree_registry().register_task_handoff(
                task_id=task.id,
                repo_url=(request.repo_url or "").strip() or None,
                repo_root=(request.repo_root or "").strip() or None,
                worktree_path=(request.worktree_path or "").strip() or None,
                workspace=normalized_workspace,
                prior_session_id=(request.prior_session_id or "").strip() or None,
                prior_work_dir=(request.prior_work_dir or "").strip() or None,
            )
    except Exception as e:
        logger.debug(f"Failed to register task worktree handoff for task {task.id}: {e}")

    return _assemble_task_read_model(task, workspace_id=1)


@router.post("/tasks/bulk", response_model=BulkCreateTaskResponse)
async def bulk_create_tasks(
    request: BulkCreateTaskRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Batch create multiple tasks at once.

    Supports creating independent tasks or task chains with dependencies.
    Maximum 50 tasks per request.
    """
    tasks_data = request.tasks or []
    if not tasks_data:
        raise HTTPException(status_code=400, detail="tasks list is required")
    if len(tasks_data) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 tasks per request")

    queue = get_task_queue(exec_user)
    allowed_providers = set(get_provider_registry().list_providers())
    default_provider = (settings.default_provider or "").strip().lower() or "codebuddy"
    default_alias = (settings.default_alias or "").strip().lower()
    default_exec_user = (settings.default_exec_user or "").strip() or None

    created: List[TaskItem] = []
    errors: List[Dict[str, str]] = []

    # Map temp_id -> real_id for dependency resolution
    temp_id_map: Dict[str, str] = {}

    for idx, task_req in enumerate(tasks_data):
        try:
            desc = (task_req.description or "").strip()
            if not desc:
                errors.append({"index": str(idx), "error": "description is required"})
                continue

            provider = (task_req.provider or "").strip().lower() or default_provider
            if provider not in allowed_providers:
                errors.append({"index": str(idx), "error": f"Invalid provider: {provider}"})
                continue
            alias_value = (getattr(task_req, "alias", None) or "").strip() or default_alias or provider

            effective_exec_user = (task_req.exec_user or "").strip() or default_exec_user

            project_name = (task_req.project_name or "").strip() or None
            project_id = (task_req.project_id or "").strip() or None
            if project_name and not project_id:
                project_id = slugify_project(project_name)

            priority = TaskPriority.PROJECT if (project_name or project_id) else TaskPriority.THOUGHT
            normalized_workspace = _normalize_workspace_or_400(task_req.workspace)

            # Resolve dependencies - convert temp IDs to real IDs
            depends_on = []
            for dep_id in (task_req.depends_on or []):
                if dep_id.startswith("temp_"):
                    # Map temp_id to real task id
                    real_id = temp_id_map.get(dep_id)
                    if real_id:
                        depends_on.append(real_id)
                else:
                    depends_on.append(dep_id)

            task = queue.add_task(
                description=desc,
                priority=priority,
                project_id=project_id,
                project_name=project_name,
                workspace=normalized_workspace,
                provider=provider,
                alias=alias_value,
                source_session_id=(task_req.source_session_id or "").strip() or None,
                prior_session_id=(getattr(task_req, "prior_session_id", None) or "").strip() or None,
                prior_work_dir=(getattr(task_req, "prior_work_dir", None) or "").strip() or None,
                repo_url=(getattr(task_req, "repo_url", None) or "").strip() or None,
                repo_root=(getattr(task_req, "repo_root", None) or "").strip() or None,
                worktree_path=(getattr(task_req, "worktree_path", None) or "").strip() or None,
                session_id=(getattr(task_req, "session_id", None) or "").strip() or None,
                exec_user=effective_exec_user,
                assigned_to=(task_req.assigned_to or "").strip() or None,
                tags=task_req.tags or [],
                due_date=task_req.due_date,
                ticket_ref=(task_req.ticket_ref or "").strip() or None,
                depends_on=depends_on,
            )

            try:
                get_session_storage().upsert_execution_binding(
                    session_id=task.session_id or f"task_{task.id}",
                    provider=provider,
                    alias=alias_value,
                    exec_user=effective_exec_user,
                    work_dir=normalized_workspace,
                    source_type="task",
                    source_session_id=(
                        (getattr(task_req, "prior_session_id", None) or "").strip()
                        or (task_req.source_session_id or "").strip()
                        or None
                    ),
                    task_id=task.id,
                    session_kind="task",
                )
            except Exception as e:
                logger.debug(f"Failed to seed execution binding for task {task.id}: {e}")

            try:
                from ..services.worktree_registry import get_repo_worktree_registry

                if any([
                    getattr(task_req, "repo_url", None),
                    getattr(task_req, "repo_root", None),
                    getattr(task_req, "worktree_path", None),
                    getattr(task_req, "prior_session_id", None),
                    getattr(task_req, "prior_work_dir", None),
                ]):
                    get_repo_worktree_registry().register_task_handoff(
                        task_id=task.id,
                        repo_url=(getattr(task_req, "repo_url", None) or "").strip() or None,
                        repo_root=(getattr(task_req, "repo_root", None) or "").strip() or None,
                        worktree_path=(getattr(task_req, "worktree_path", None) or "").strip() or None,
                        workspace=normalized_workspace,
                        prior_session_id=(getattr(task_req, "prior_session_id", None) or "").strip() or None,
                        prior_work_dir=(getattr(task_req, "prior_work_dir", None) or "").strip() or None,
                    )
            except Exception as e:
                logger.debug(f"Failed to register batch task worktree handoff for task {task.id}: {e}")

            task_item = _assemble_task_read_model(task, workspace_id=1)
            created.append(task_item)

            # Store mapping for dependency resolution
            temp_id_map[f"temp_{idx}"] = task_item.id

        except Exception as e:
            logger.error(f"Failed to create task at index {idx}: {e}", exc_info=True)
            errors.append({"index": str(idx), "error": str(e)})

    return BulkCreateTaskResponse(
        success=len(errors) == 0,
        created=created,
        errors=errors,
    )


@router.delete("/tasks/{task_id}", response_model=SuccessResponse)
async def delete_task(task_id: str, exec_user: str = Query(settings.exec_user, description="Exec user for task isolation")):
    """Hard delete a task and its associated session."""
    queue = get_task_queue(exec_user)

    # Get task first to retrieve session_id
    task = queue.get_task(task_id)
    session_id = (task.session_id if task else None) or f"task_{task_id}"

    # Best-effort hard delete (idempotent)
    try:
        queue.delete_task_hard(task_id)
    except Exception:
        pass

    # Also delete archived session so Chat/Task both disappear
    storage = get_session_storage()
    try:
        storage.delete_session(session_id)
    except Exception:
        pass

    return SuccessResponse(success=True, message=f"Task {task_id} deleted")


# ============ Task Status API ============


@router.patch("/tasks/{task_id}/status", response_model=TaskItem)
async def update_task_status(
    task_id: str,
    request: UpdateTaskStatusRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Manually update task status.

    Used to unblock dependent tasks or cancel blocked tasks.
    """
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")

    new_status = normalize_task_status(request.status)
    try:
        new_status_enum = TaskStatus.from_legacy(new_status)
    except ValueError:
        valid_statuses = [s.value for s in TaskStatus]
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status}. Must be one of: {valid_statuses}")

    current_status = TaskStatus.from_legacy(task.status if isinstance(task.status, str) else task.status.value)
    if not TaskStatus.can_transition(current_status, new_status_enum):
        if new_status_enum == TaskStatus.CANCELLED:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Task {task_id} cannot enter cancelled from {current_status.value}. "
                    "Only pending or running tasks can be cancelled."
                ),
            )
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task status transition: {current_status.value} -> {new_status_enum.value}",
        )

    # Update task status in storage
    updated_task = queue.update_task_status(task_id, new_status_enum)
    if not updated_task:
        raise HTTPException(status_code=500, detail="Failed to update task status")

    return _assemble_task_read_model(updated_task, workspace_id=1)


@router.post("/tasks/{task_id}/requeue-orphan", response_model=TaskItem)
async def requeue_orphan_task(
    task_id: str,
    request: Optional[RequeueOrphanTaskRequest] = None,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Requeue a task that was marked orphaned in runtime layer."""
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")

    updated = queue.requeue_orphan_task(task_id, reason=request.reason if request else None)
    if not updated:
        raise HTTPException(status_code=400, detail=f"Task {task_id} is not marked as orphaned")

    return _assemble_task_read_model(updated, workspace_id=1)


# ============ Task General Update API ============


@router.patch("/tasks/{task_id}", response_model=TaskItem)
async def update_task(
    task_id: str,
    request: UpdateTaskRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Update arbitrary task fields (priority, assignee, position, title, etc).

    For status changes, use PATCH /tasks/{id}/status instead.
    """
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")

    updates = request.model_dump(exclude_unset=True)
    if not updates:
        return _assemble_task_read_model(task, workspace_id=1)

    if "priority" in updates and updates["priority"]:
        try:
            task.priority = TaskPriority(updates["priority"])
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid priority: {updates['priority']}")
    if "assignee" in updates:
        task.assigned_to = (updates["assignee"] or "").strip() or None
    if "position" in updates:
        task.context = {**(task.context or {}), "position": updates["position"]}
    if "title" in updates and updates["title"] is not None:
        task.description = str(updates["title"]).strip() or task.description
    if "description" in updates and updates["description"] is not None:
        task.description = str(updates["description"]).strip() or task.description
    if "due_date" in updates and updates["due_date"]:
        task.due_date = _parse_due_date_or_400(updates["due_date"])
    if "due_date" in updates and updates["due_date"] in (None, "", []):
        task.due_date = None
    if "labels" in updates:
        task.tags = list(updates["labels"] or [])
    if "feedback_notes" in updates:
        task.feedback_notes = updates["feedback_notes"]
    if "session_id" in updates:
        task.session_id = (updates["session_id"] or "").strip() or None
    if "source_session_id" in updates:
        task.source_session_id = (updates["source_session_id"] or "").strip() or None
    if "prior_session_id" in updates:
        task.prior_session_id = (updates["prior_session_id"] or "").strip() or None
    if "prior_work_dir" in updates:
        task.prior_work_dir = (updates["prior_work_dir"] or "").strip() or None
    if "repo_url" in updates:
        task.repo_url = (updates["repo_url"] or "").strip() or None
    if "repo_root" in updates:
        task.repo_root = (updates["repo_root"] or "").strip() or None
    if "worktree_path" in updates:
        task.worktree_path = (updates["worktree_path"] or "").strip() or None
    if any(k in updates for k in ("prior_session_id", "prior_work_dir", "repo_url", "repo_root", "worktree_path", "source_session_id")):
        context = dict(task.context or {})
        for k, v in {
            "source_session_id": task.source_session_id,
            "prior_session_id": task.prior_session_id,
            "prior_work_dir": task.prior_work_dir,
            "repo_url": task.repo_url,
            "repo_root": task.repo_root,
            "worktree_path": task.worktree_path,
        }.items():
            if v in (None, "", [], {}):
                context.pop(k, None)
            else:
                context[k] = v
        task.context = context

    updated = queue.update_task(task)
    if not updated:
        raise HTTPException(status_code=400, detail=f"Failed to update task {task_id}")

    try:
        clear_binding_fields = []
        if updates.get("source_session_id", "__missing__") is None or updates.get("prior_session_id", "__missing__") is None:
            clear_binding_fields.extend(["source_session_id", "source_type"])
        if updates.get("prior_work_dir", "__missing__") is None or updates.get("worktree_path", "__missing__") is None:
            clear_binding_fields.append("work_dir")
        if any(updates.get(k, "__missing__") is None for k in ("repo_url", "repo_root", "worktree_path")):
            clear_binding_fields.append("metadata")
        if clear_binding_fields:
            get_session_storage().clear_execution_binding_fields(
                task.session_id or f"task_{task.id}",
                *clear_binding_fields,
            )

        if updates.get("prior_work_dir", "__missing__") is None or updates.get("worktree_path", "__missing__") is None:
            binding_work_dir = None
        else:
            binding_work_dir = (
                (task.worktree_path or "").strip()
                or (task.prior_work_dir or "").strip()
                or (task.workspace or "").strip()
                or None
            )
        get_session_storage().bind_execution_context(
            task.session_id or f"task_{task.id}",
            provider=(task.provider or "").strip() or None,
            alias=(task.alias or "").strip() or None,
            exec_user=(task.exec_user or exec_user or "").strip() or None,
            work_dir=binding_work_dir,
            source_type="task",
            source_session_id=(task.prior_session_id or task.source_session_id or "").strip() or None,
            task_id=task.id,
            session_kind="task",
            metadata={
                k: v for k, v in {
                    "repo_url": task.repo_url,
                    "repo_root": task.repo_root,
                    "worktree_path": task.worktree_path,
                }.items() if v not in (None, "", [], {})
            } or None,
        )
    except Exception as e:
        logger.debug(f"Failed to sync execution binding for updated task {task.id}: {e}")

    try:
        from ..services.worktree_registry import get_repo_worktree_registry

        if any(getattr(task, field, None) for field in ("repo_url", "repo_root", "worktree_path", "prior_session_id", "prior_work_dir")):
            get_repo_worktree_registry().register_task_handoff(
                task_id=task.id,
                repo_url=(task.repo_url or "").strip() or None,
                repo_root=(task.repo_root or "").strip() or None,
                worktree_path=(task.worktree_path or "").strip() or None,
                workspace=(task.workspace or "").strip() or None,
                prior_session_id=(task.prior_session_id or "").strip() or None,
                prior_work_dir=(task.prior_work_dir or "").strip() or None,
            )
    except Exception as e:
        logger.debug(f"Failed to register updated task worktree handoff for task {task.id}: {e}")

    refreshed = queue.get_task(task_id)
    return _assemble_task_read_model(refreshed or task, workspace_id=1)


# ============ Task Outcome API ============

_VALID_OUTCOMES = {"success", "failed", "partial", "abandoned"}


@router.patch("/tasks/{task_id}/outcome", response_model=TaskItem)
async def update_task_outcome(
    task_id: str,
    request: UpdateTaskOutcomeRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Set or update the outcome of a completed task.

    Ported from mission-control commit 6cf4256.
    Outcome must be one of: success | failed | partial | abandoned.
    """
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")

    outcome_val = (request.outcome or "").strip().lower()
    if outcome_val not in _VALID_OUTCOMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid outcome '{outcome_val}'. Must be one of: {sorted(_VALID_OUTCOMES)}",
        )

    # Persist outcome fields on the task Redis hash
    updates: dict = {"outcome": outcome_val}
    if request.resolution is not None:
        updates["resolution"] = request.resolution
    if request.feedback_rating is not None:
        updates["feedback_rating"] = request.feedback_rating
    if request.feedback_notes is not None:
        updates["feedback_notes"] = request.feedback_notes

    for key, value in updates.items():
        setattr(task, key, value)
    if outcome_val == "success" and not task.completed_at:
        task.completed_at = datetime.now(timezone.utc)
    if outcome_val == "failed" and not task.completed_at:
        task.completed_at = datetime.now(timezone.utc)

    # Compatibility shim for older Redis-backed mocks/tests.
    if hasattr(queue, "_redis") and hasattr(queue, "_task_key"):
        try:
            task_key = queue._task_key(task_id, task.exec_user)
            redis_updates = {k: (str(v) if v is not None else "") for k, v in updates.items()}
            queue._redis.hset(task_key, redis_updates)
        except Exception:
            pass

    queue.update_task(task)

    # Refresh from storage and return
    updated_task = queue.get_task(task_id)
    if not updated_task:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated task")

    return _assemble_task_read_model(updated_task, workspace_id=1)


def _resolve_since(timeframe: str) -> Optional[datetime]:
    """Return a UTC datetime cutoff for the given timeframe string."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    tf = timeframe.strip().lower()
    if tf == "day":
        return now - timedelta(days=1)
    if tf == "week":
        return now - timedelta(weeks=1)
    if tf == "month":
        return now - timedelta(days=30)
    return None  # "all"


@router.get("/tasks/outcomes", response_model=TaskOutcomesResponse)
async def get_task_outcomes(
    timeframe: str = Query("all", description="Timeframe: day | week | month | all"),
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Return outcome analytics for completed tasks.

    Aggregates success/failed/partial/abandoned counts for done tasks, broken
    down by provider and priority.  Ported from mission-control commit 6cf4256.
    """
    queue = get_task_queue(exec_user)

    since = _resolve_since(timeframe)

    # Compatibility shim for legacy Redis-backed mocks/tests.
    if hasattr(queue, "_redis") and hasattr(queue, "_status_key"):
        done_ids = queue._redis.smembers(queue._status_key(TaskStatus.COMPLETED))
        rows = []
        for tid in done_ids:
            t = queue.get_task(tid)
            if not t:
                continue
            if since:
                ts = t.completed_at or t.created_at
                if ts is not None:
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < since:
                        continue
            rows.append(t)
    else:
        listed = queue.list_tasks(page=1, page_size=100000, status=TaskStatus.COMPLETED.value)
        if isinstance(listed, tuple):
            rows = list(listed[0] or [])
        elif isinstance(listed, list):
            rows = list(listed)
        else:
            rows = []
        if since:
            filtered = []
            for t in rows:
                ts = t.completed_at or t.created_at
                if ts is not None:
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < since:
                        continue
                filtered.append(t)
            rows = filtered

    def _empty_dim() -> dict:
        return {"success": 0, "failed": 0, "partial": 0, "abandoned": 0, "unknown": 0, "total": 0, "success_rate": 0.0}

    summary = TaskOutcomeSummary()
    by_provider: Dict[str, Any] = {}
    by_priority: Dict[str, Any] = {}
    error_map: Dict[str, int] = {}
    total_attempts = 0
    total_resolution_secs = 0.0
    resolution_count = 0

    for task in rows:
        outcome = (getattr(task, "outcome", None) or "unknown").lower()
        provider = getattr(task, "provider", None) or "unknown"
        priority = task.priority if isinstance(task.priority, str) else task.priority.value
        attempts = int(task.attempt_count or 0)

        summary.total_done += 1
        if outcome != "unknown":
            summary.with_outcome += 1

        bucket_field = outcome if outcome in ("success", "failed", "partial", "abandoned") else "unknown"
        setattr(summary.by_outcome, bucket_field, getattr(summary.by_outcome, bucket_field) + 1)

        for dim_map, dim_key in ((by_provider, provider), (by_priority, priority)):
            if dim_key not in dim_map:
                dim_map[dim_key] = _empty_dim()
            dim_map[dim_key]["total"] += 1
            dim_map[dim_key][bucket_field] += 1

        total_attempts += attempts

        if task.completed_at and task.created_at:
            ca = task.completed_at
            cr = task.created_at
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=timezone.utc)
            if cr.tzinfo is None:
                cr = cr.replace(tzinfo=timezone.utc)
            secs = (ca - cr).total_seconds()
            if secs >= 0:
                total_resolution_secs += secs
                resolution_count += 1

        err = (task.error_message or "").strip()
        if err:
            error_map[err] = error_map.get(err, 0) + 1

    n = summary.total_done
    summary.avg_attempt_count = total_attempts / n if n else 0.0
    summary.avg_time_to_resolution_seconds = total_resolution_secs / resolution_count if resolution_count else 0.0
    wo = summary.with_outcome
    summary.success_rate = summary.by_outcome.success / wo if wo else 0.0

    for dim_map in (by_provider, by_priority):
        for entry in dim_map.values():
            total = entry["total"]
            with_outcome = total - entry["unknown"]
            entry["success_rate"] = entry["success"] / with_outcome if with_outcome else 0.0

    common_errors = sorted(error_map.items(), key=lambda x: -x[1])[:10]

    return TaskOutcomesResponse(
        timeframe=timeframe,
        summary=summary,
        by_provider=by_provider,
        by_priority=by_priority,
        common_errors=[{"error_message": e, "count": c} for e, c in common_errors],
        record_count=len(rows),
    )


# ============ Chat Continue API ============


@router.post("/tasks/{task_id}/continue", response_model=TaskItem)
async def chat_continue_task(
    task_id: str,
    request: ChatContinueRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Continue chatting on an existing task (like /chat -c).

    Re-enqueues the task with a new user message so the agent picks up
    the conversation where it left off.
    """
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")

    status_val = task.status if isinstance(task.status, str) else task.status.value
    if status_val == TaskStatus.RUNNING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {task_id} is currently running. Wait for it to finish before continuing.",
        )
    if status_val == TaskStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {task_id} is cancelled and cannot be continued.",
        )
    if status_val == TaskStatus.ARCHIVED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {task_id} is archived and cannot be continued.",
        )

    msg = (request.message or "").strip()
    if not msg:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="message is required")

    try:
        updated = queue.enqueue_chat_continue(task_id, msg, model=request.model)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to enqueue: {e}")

    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to enqueue chat continue")

    return _assemble_task_read_model(updated, workspace_id=1)


# ============ Bulk Task Operations API ============


@router.post("/tasks/bulk_archive", response_model=TaskBulkResponse)
async def bulk_archive_tasks(
    request: TaskBulkRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Batch archive tasks (DONE -> ARCHIVED)."""
    task_ids = [str(tid) for tid in (request.task_ids or [])]
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids is required")
    if len(task_ids) > 500:
        raise HTTPException(status_code=400, detail="task_ids too large (max 500)")

    queue = get_task_queue(exec_user)
    result = queue.archive_tasks(task_ids)
    return TaskBulkResponse(success=True, message=f"Archived {result.get('count', 0)} tasks", result=result)


@router.post("/tasks/bulk_unarchive", response_model=TaskBulkResponse)
async def bulk_unarchive_tasks(
    request: TaskBulkRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Batch unarchive tasks (ARCHIVED -> DONE)."""
    task_ids = [str(tid) for tid in (request.task_ids or [])]
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids is required")
    if len(task_ids) > 500:
        raise HTTPException(status_code=400, detail="task_ids too large (max 500)")

    queue = get_task_queue(exec_user)
    result = queue.unarchive_tasks(task_ids)
    return TaskBulkResponse(success=True, message=f"Unarchived {result.get('count', 0)} tasks", result=result)


@router.post("/tasks/bulk_clear", response_model=TaskBulkResponse)
async def bulk_clear_tasks(
    request: TaskBulkRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Batch hard-delete archived tasks and their associated sessions."""
    task_ids = [str(tid) for tid in (request.task_ids or [])]
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids is required")
    if len(task_ids) > 500:
        raise HTTPException(status_code=400, detail="task_ids too large (max 500)")

    queue = get_task_queue(exec_user)

    # Capture session ids before hard delete
    session_id_by_task: Dict[str, str] = {}
    for task_id in task_ids:
        try:
            task = queue.get_task(task_id)
            session_id_by_task[task_id] = (getattr(task, "session_id", None) if task else None) or f"task_{task_id}"
        except Exception:
            session_id_by_task[task_id] = f"task_{task_id}"

    result = queue.clear_tasks(task_ids)

    storage = get_session_storage()
    for task_id in result.get("cleared", []) or []:
        try:
            storage.delete_session(session_id_by_task.get(task_id) or f"task_{task_id}")
        except Exception:
            pass

    return TaskBulkResponse(success=True, message=f"Cleared {result.get('count', 0)} tasks", result=result)


@router.post("/tasks/bulk_delete", response_model=TaskBulkResponse)
async def bulk_delete_tasks(
    request: TaskBulkRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Batch hard-delete tasks of ANY status and their associated sessions.

    Unlike bulk_clear which only deletes ARCHIVED tasks, this endpoint
    deletes tasks regardless of their current status.
    """
    task_ids = [str(tid) for tid in (request.task_ids or [])]
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids is required")
    if len(task_ids) > 500:
        raise HTTPException(status_code=400, detail="task_ids too large (max 500)")

    queue = get_task_queue(exec_user)
    storage = get_session_storage()

    deleted: List[str] = []
    skipped: Dict[str, str] = {}

    for task_id in task_ids:
        try:
            task = queue.get_task(task_id)
            if not task:
                skipped[task_id] = "not_found"
                continue

            # Get session_id before deleting
            session_id = getattr(task, "session_id", None) or f"task_{task_id}"

            # Hard delete the task (no status restriction)
            queue.delete_task_hard(task_id)
            deleted.append(task_id)

            # Also delete associated session
            try:
                storage.delete_session(session_id)
            except Exception:
                pass

        except Exception as e:
            skipped[task_id] = f"error:{e}"

    result = {"count": len(deleted), "deleted": deleted, "skipped": skipped}
    return TaskBulkResponse(success=True, message=f"Deleted {len(deleted)} tasks", result=result)


# ============ Task AG-UI Messages API ============


@router.get("/tasks/{task_id}/agui/messages")
async def get_task_agui_messages(
    task_id: str,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
    limit: Optional[int] = Query(None, ge=1, le=5000, description="Max number of messages"),
    tail: Optional[int] = Query(None, ge=1, le=5000, description="Return only the last N messages"),
):
    """Get task conversation log as an AGUI MessagesSnapshot.

    Prefers Redis session storage (archived AG-UI events from task execution),
    falls back to reading `.claude/conversation.json` if no archived data.
    """

    # Get task to retrieve session_id
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    session_id = (task.session_id if task else None) or f"task_{task_id}"

    # 1) Prefer Redis-archived messages (same storage as Chat)
    try:
        storage = get_session_storage()
        meta = storage.get_session_meta(session_id)
        if meta:
            stored_messages = storage.get_session_messages(session_id)
            messages: List[AGUIMessage] = []
            for idx, m in enumerate(stored_messages or []):
                role_raw = (getattr(m, "role", None) or "assistant").lower()
                if role_raw not in ("user", "assistant", "system", "tool"):
                    role_raw = "assistant"

                created_at = None
                ts = getattr(m, "timestamp", None)
                if isinstance(ts, int):
                    created_at = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")

                messages.append(
                    AGUIMessage(
                        id=getattr(m, "id", None) or f"taskmsg_{idx}",
                        role=MessageRole(role_raw),
                        content=getattr(m, "content", "") or "",
                        createdAt=created_at,
                    )
                )

            if tail:
                messages = messages[-tail:]
            elif limit:
                messages = messages[:limit]

            return MessagesSnapshotEvent(messages=messages).model_dump(exclude_none=True)
    except Exception:
        # fall back to file
        pass

    # 2) Fallback to filesystem conversation log
    log_path = _resolve_task_conversation_log_path(exec_user=exec_user, task_id=task_id, task=task)

    if not log_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task conversation log not found")

    try:
        conversation_obj = json.loads(log_path.read_text(encoding="utf-8"))
        messages = _parse_task_conversation(conversation_obj)
    except Exception as e:
        logger.error(f"Failed to parse conversation log for task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to parse task conversation log")

    if tail:
        messages = messages[-tail:]
    elif limit:
        messages = messages[:limit]

    event = MessagesSnapshotEvent(messages=messages)
    return event.model_dump(exclude_none=True)


@router.get("/tasks/{task_id}/timeline", response_model=TaskTimelineResponse)
async def get_task_timeline(
    task_id: str,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
    include_session_events: bool = Query(True, description="Also include related session events"),
):
    """Return the task's lifecycle/event timeline."""
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")

    events = query_domain_events(
        task_id=str(task_id),
        aggregate_type="task",
        aggregate_id=str(task_id),
        limit=1000,
    )
    if include_session_events:
        session_id = getattr(task, "session_id", None)
        if session_id:
            events.extend(
                query_domain_events(
                    session_id=str(session_id),
                    limit=1000,
                )
            )

    deduped: Dict[tuple, Any] = {}
    for event in events:
        key = (
            getattr(event, "id", None),
            getattr(event, "event_type", None),
            getattr(event, "aggregate_type", None),
            getattr(event, "aggregate_id", None),
            getattr(event, "created_at", None),
        )
        deduped[key] = event

    ordered = sorted(
        deduped.values(),
        key=lambda evt: float(getattr(evt, "created_at", 0) or 0),
    )

    return TaskTimelineResponse(
        task_id=str(task_id),
        total=len(ordered),
        events=[_domain_event_to_timeline_item(evt) for evt in ordered],
    )


def _to_quality_review_item(review) -> QualityReviewItem:
    status_obj = getattr(review, "status", None)
    status_value = status_obj.value if hasattr(status_obj, "value") else str(status_obj or "")
    return QualityReviewItem(
        id=int(getattr(review, "id", 0) or 0),
        task_id=str(getattr(review, "task_id", "") or ""),
        reviewer=str(getattr(review, "reviewer", "") or ""),
        status=status_value,
        notes=str(getattr(review, "notes", "") or ""),
        created_at=float(getattr(review, "created_at", 0) or 0),
    )


@router.get("/tasks/{task_id}/quality-reviews", response_model=TaskQualityReviewsResponse)
async def get_task_quality_reviews(
    task_id: str,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Get Aegis quality review history and current gate result for a task."""
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")

    gate = get_quality_gate()
    reviews = gate.get_reviews(task_id=str(task_id), workspace_id=1, limit=20)
    decision = gate.check_completion_gate(task_id=str(task_id), workspace_id=1)

    return TaskQualityReviewsResponse(
        task_id=str(task_id),
        gate_allowed=bool(decision.allowed),
        gate_reason=decision.reason,
        latest_review=_to_quality_review_item(decision.latest_review) if decision.latest_review else None,
        reviews=[_to_quality_review_item(r) for r in reviews],
    )


@router.post("/tasks/{task_id}/quality-reviews", response_model=TaskQualityReviewsResponse)
async def submit_task_quality_review(
    task_id: str,
    request: SubmitQualityReviewRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Submit Aegis quality review and return updated quality history."""
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")

    reviewer = (request.reviewer or "").strip() or "aegis"
    status_raw = (request.status or "").strip().lower()
    notes = (request.notes or "").strip()

    try:
        review_status = ReviewStatus(status_raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review status. Use approved/rejected/needs_changes")

    gate = get_quality_gate()
    gate.submit_review(
        task_id=str(task_id),
        reviewer=reviewer,
        status=review_status,
        notes=notes,
        workspace_id=1,
    )

    reviews = gate.get_reviews(task_id=str(task_id), workspace_id=1, limit=20)
    decision = gate.check_completion_gate(task_id=str(task_id), workspace_id=1)

    return TaskQualityReviewsResponse(
        task_id=str(task_id),
        gate_allowed=bool(decision.allowed),
        gate_reason=decision.reason,
        latest_review=_to_quality_review_item(decision.latest_review) if decision.latest_review else None,
        reviews=[_to_quality_review_item(r) for r in reviews],
    )


@router.post("/tasks/{task_id}/broadcast", response_model=BroadcastTaskResponse)
async def broadcast_task_message(
    task_id: str,
    request: BroadcastTaskRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Broadcast one message to all detected task subscribers."""
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")

    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    sender = (request.sender or "").strip() or "user"
    recipients_raw: List[str] = []

    if bool(request.include_assignee) and getattr(task, "assigned_to", None):
        recipients_raw.append(str(getattr(task, "assigned_to", "") or ""))

    # Include task owner exec_user as fallback subscriber
    if getattr(task, "exec_user", None):
        recipients_raw.append(str(getattr(task, "exec_user", "") or ""))

    # Collect subscribers from comment authors + mentions
    try:
        redis = queue._redis
        comment_ids = redis.zrange(_comments_index_key(exec_user, task_id), 0, -1)
        for cid in comment_ids:
            comment = _load_comment(redis, exec_user, task_id, cid)
            if not comment:
                continue
            if comment.author:
                recipients_raw.append(str(comment.author))
            for mention in (comment.mentions or []):
                recipients_raw.append(str(mention))
    except Exception:
        pass

    recipients = [r for r in normalize_recipients(recipients_raw) if r and r != sender]
    delivered = broadcast_to_recipients(task_id=str(task_id), sender=sender, message=message, recipients=recipients)

    return BroadcastTaskResponse(task_id=str(task_id), recipients=recipients, delivered=delivered)


def _breakdown_items(rows: List[Dict[str, Any]]) -> List[CostBreakdownItem]:
    items: List[CostBreakdownItem] = []
    for row in rows or []:
        items.append(
            CostBreakdownItem(
                key=str(row.get("key", "unassigned")),
                count=int(row.get("count", 0) or 0),
                prompt_tokens=int(row.get("prompt_tokens", 0) or 0),
                completion_tokens=int(row.get("completion_tokens", 0) or 0),
                total_tokens=int(row.get("total_tokens", 0) or 0),
                total_cost_usd=float(row.get("total_cost_usd", 0.0) or 0.0),
            )
        )
    return items


@router.get("/costs", response_model=CostSummaryResponse)
async def get_cost_summary(
    since: Optional[float] = Query(None, description="Unix timestamp lower bound"),
):
    """Return token cost attribution across workspace, agent, and runtime."""
    tracker = get_token_tracker()
    stats = tracker.get_stats(since=since)
    breakdown = tracker.get_attribution_breakdown(since=since)
    return CostSummaryResponse(
        total_requests=stats.total_requests,
        total_prompt_tokens=stats.total_prompt_tokens,
        total_completion_tokens=stats.total_completion_tokens,
        total_tokens=stats.total_tokens,
        total_cost_usd=stats.total_cost_usd,
        by_workspace=_breakdown_items(breakdown.get("by_workspace", [])),
        by_agent=_breakdown_items(breakdown.get("by_agent", [])),
        by_runtime=_breakdown_items(breakdown.get("by_runtime", [])),
    )


# ---------------------------------------------------------------------------
# Task comments
# Ported from mission-control GET/POST /api/tasks/[id]/comments (commit 4ef91d4).
#
# Redis key layout (mirrors task storage namespace conventions):
#   task_comment:{exec_user}:{task_id}:{comment_id}  → HASH (id, task_id, author,
#                                                        content, created_at, parent_id)
#   task_comments:{exec_user}:{task_id}               → ZSET  score=created_at → comment_id
# ---------------------------------------------------------------------------


def _comment_key(exec_user: str, task_id: str, comment_id: str) -> str:
    return f"task_comment:{exec_user}:{task_id}:{comment_id}"


def _comments_index_key(exec_user: str, task_id: str) -> str:
    return f"task_comments:{exec_user}:{task_id}"


def _load_comment(redis, exec_user: str, task_id: str, comment_id: str) -> Optional[TaskComment]:
    """Load a single TaskComment from Redis. Returns None if missing."""
    data = redis.hgetall(_comment_key(exec_user, task_id, comment_id))
    if not data:
        return None
    mentions_raw = data.get("mentions", "[]")
    try:
        mentions = json.loads(mentions_raw) if isinstance(mentions_raw, str) else []
        if not isinstance(mentions, list):
            mentions = []
    except Exception:
        mentions = []

    return TaskComment(
        id=data.get("id", comment_id),
        task_id=data.get("task_id", task_id),
        author=data.get("author", "user"),
        content=data.get("content", ""),
        created_at=float(data.get("created_at", 0)),
        parent_id=data.get("parent_id") or None,
        mentions=[str(m) for m in mentions],
    )


def _build_comment_tree(flat: List[TaskComment]) -> List[TaskComment]:
    """Build threaded tree from flat list (same algorithm as MC). Returns top-level comments."""
    by_id: Dict[str, TaskComment] = {c.id: c.model_copy(deep=True) for c in flat}
    roots: List[TaskComment] = []
    for c in by_id.values():
        if c.parent_id and c.parent_id in by_id:
            by_id[c.parent_id].replies.append(c)
        else:
            roots.append(c)
    # Sort roots and replies by created_at ascending (mirrors MC ORDER BY created_at ASC)
    roots.sort(key=lambda x: x.created_at)
    for c in by_id.values():
        c.replies.sort(key=lambda x: x.created_at)
    return roots


@router.get("/tasks/{task_id}/comments", response_model=TaskCommentsResponse)
async def get_task_comments(
    task_id: str,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Get all comments for a task, organized into a thread tree.

    Ported from mission-control GET /api/tasks/[id]/comments (commit 4ef91d4).
    Returns top-level comments with nested replies, ordered by creation time.
    """
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    redis = queue._redis
    index_key = _comments_index_key(exec_user, task_id)
    comment_ids = redis.zrange(index_key, 0, -1)

    flat: List[TaskComment] = []
    for cid in comment_ids:
        comment = _load_comment(redis, exec_user, task_id, cid)
        if comment:
            flat.append(comment)

    return TaskCommentsResponse(
        task_id=task_id,
        comments=_build_comment_tree(flat),
        total=len(flat),
    )


@router.post("/tasks/{task_id}/comments", response_model=TaskComment, status_code=201)
async def create_task_comment(
    task_id: str,
    request: CreateCommentRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Add a comment (or reply) to a task.

    Ported from mission-control POST /api/tasks/[id]/comments (commit 4ef91d4).
    Supply parent_id to create a reply. content must be non-empty.
    """
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Comment content must not be empty")

    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    redis = queue._redis

    # Validate parent exists if provided
    if request.parent_id:
        parent = _load_comment(redis, exec_user, task_id, request.parent_id)
        if not parent:
            raise HTTPException(status_code=400, detail="Parent comment not found")

    comment_id = str(uuid.uuid4())
    now = time.time()

    mentions = extract_mentions(request.content)

    payload: Dict[str, str] = {
        "id": comment_id,
        "task_id": task_id,
        "author": request.author,
        "content": request.content,
        "created_at": str(now),
        "mentions": json.dumps(mentions, ensure_ascii=False),
    }
    if request.parent_id:
        payload["parent_id"] = request.parent_id

    redis.hset(_comment_key(exec_user, task_id, comment_id), payload)
    redis.zadd(_comments_index_key(exec_user, task_id), {comment_id: now})

    return TaskComment(
        id=comment_id,
        task_id=task_id,
        author=request.author,
        content=request.content,
        created_at=now,
        parent_id=request.parent_id,
        mentions=mentions,
    )

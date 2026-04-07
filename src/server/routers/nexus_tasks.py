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
from pydantic import BaseModel, Field

from ..config import settings
from src.runtime.events.agui import AGUIMessage, MessageRole, MessagesSnapshotEvent
from ..models import (
    TaskStatus,
    TaskPriority,
)
from ..services.user_directory import UserDirectoryManager
from src.runtime.commands.slash.handler import slugify_project
from ..providers import get_provider_registry
from ..services.session_storage import get_session_storage
from ..logger import get_logger
from .nexus_auth import verify_nexus_auth
from .nexus_models import (
    SuccessResponse,
    TaskItem,
    TaskListResponse,
    TaskBulkRequest,
    TaskBulkResponse,
    ProjectItem,
    CreateTaskRequest,
    BulkCreateTaskRequest,
    BulkCreateTaskResponse,
    UpdateTaskStatusRequest,
    UpdateTaskOutcomeRequest,
    TaskOutcomesResponse,
    TaskOutcomeSummary,
    OutcomeBuckets,
    OutcomesByDimension,
    ChatContinueRequest,
    TaskComment,
    TaskCommentsResponse,
    CreateCommentRequest,
    get_task_queue,
    normalize_task_status,
    task_to_item,
)

logger = get_logger(__name__)
_user_dir_manager = UserDirectoryManager(settings)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-tasks"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ============ Task Helper Functions ============


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

    return TaskListResponse(
        total=total,
        page=page,
        page_size=page_size,
        tasks=[task_to_item(t) for t in tasks],
    )


@router.get("/tasks/{task_id}", response_model=TaskItem)
async def get_task(task_id: str, exec_user: str = Query(settings.exec_user, description="Exec user for task isolation")):
    """Get a single task detail."""
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")
    return task_to_item(task)


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

    queue = get_task_queue(exec_user)
    task = queue.add_task(
        description=desc,
        priority=priority,
        project_id=project_id,
        project_name=project_name,
        workspace=(request.workspace or "").strip() or None,
        provider=provider,
        alias=alias_value,
        model=(request.llm_model or "").strip() or None,
        source_session_id=(request.source_session_id or "").strip() or None,
        exec_user=effective_exec_user,
        depends_on=request.depends_on or [],
        loop_enabled=bool(request.loop_enabled),
        loop_max_iterations=request.loop_max_iterations or 1,
        loop_keywords=request.loop_keywords or [],
    )

    return task_to_item(task)


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
                workspace=(task_req.workspace or "").strip() or None,
                provider=provider,
                alias=alias_value,
                source_session_id=(task_req.source_session_id or "").strip() or None,
                exec_user=effective_exec_user,
                depends_on=depends_on,
            )

            task_item = task_to_item(task)
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

    new_status = request.status.strip().lower()
    try:
        new_status_enum = TaskStatus(new_status)
    except ValueError:
        valid_statuses = [s.value for s in TaskStatus]
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status}. Must be one of: {valid_statuses}")

    # Update task status in storage
    updated_task = queue.update_task_status(task_id, new_status_enum)
    if not updated_task:
        raise HTTPException(status_code=500, detail="Failed to update task status")

    return task_to_item(updated_task)


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
        updates["feedback_rating"] = str(request.feedback_rating)
    if request.feedback_notes is not None:
        updates["feedback_notes"] = request.feedback_notes

    task_key = queue._task_key(task_id, task.exec_user)
    queue._redis.hset(task_key, updates)

    # Refresh from storage and return
    updated_task = queue.get_task(task_id)
    if not updated_task:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated task")

    return task_to_item(updated_task)


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

    # Collect all done tasks
    done_ids = queue._redis.smembers(queue._status_key(TaskStatus.DONE))
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
    if status_val == TaskStatus.DOING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {task_id} is currently running. Wait for it to finish before continuing.",
        )
    if status_val == TaskStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {task_id} is cancelled and cannot be continued.",
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

    return task_to_item(updated)


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
    return TaskComment(
        id=data.get("id", comment_id),
        task_id=data.get("task_id", task_id),
        author=data.get("author", "user"),
        content=data.get("content", ""),
        created_at=float(data.get("created_at", 0)),
        parent_id=data.get("parent_id") or None,
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
        # Only one level of nesting (MC-compatible: replies cannot have replies)
        if parent.parent_id:
            raise HTTPException(status_code=400, detail="Cannot reply to a reply")

    comment_id = str(uuid.uuid4())
    now = time.time()

    payload: Dict[str, str] = {
        "id": comment_id,
        "task_id": task_id,
        "author": request.author,
        "content": request.content,
        "created_at": str(now),
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
    )

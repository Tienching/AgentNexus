# -*- coding: utf-8 -*-
"""NexusHub-style Web API Router

Provides REST API endpoints for viewing and managing AGUI sessions.
"""

from __future__ import annotations

import asyncio
import json
import os
import pwd
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import settings
from ..models.agui_events import AGUIMessage, MessageRole, MessagesSnapshotEvent
from ..models.task_models import TaskStatus
from ..services.task_storage import TaskQueue

from ..models.session import (
    SessionMeta,
    SessionStatus,
    SessionListResponse,
    SessionMessagesResponse,
)
from ..services.session_storage import get_session_storage
from ..logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/nexus", tags=["nexus"])


# Response models
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


# ============ Usernames API ============

@router.get("/usernames", response_model=UsernamesResponse)
async def get_usernames():
    """Get all unique usernames from sessions
    
    Returns a sorted list of all usernames that have sessions.
    """
    storage = get_session_storage()
    usernames = storage.get_all_usernames()
    return UsernamesResponse(usernames=usernames)


# ============ Session List API ============

@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    username: Optional[str] = Query(None, description="Username (optional, if not provided returns all sessions)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    search: Optional[str] = Query(None, description="Search term for title"),
    status_param: Optional[str] = Query(None, alias="status", description="Filter by status"),
):
    """Get session list with pagination and filtering
    
    - **username**: Optional. If provided, returns only that user's sessions. If not, returns all sessions.
    - **page**: Page number (default: 1)
    - **page_size**: Number of sessions per page (default: 20, max: 100)
    - **search**: Optional search term to filter by title
    - **status**: Optional status filter (idle, running, completed, error)
    """
    storage = get_session_storage()
    
    # Parse status filter
    status_filter = None
    if status_param:
        try:
            status_filter = SessionStatus(status_param)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status_param}. Must be one of: idle, running, completed, error"
            )
    
    if username:
        sessions, total = storage.get_user_sessions(
            username=username,
            page=page,
            page_size=page_size,
            search=search,
            status_filter=status_filter,
        )
    else:
        sessions, total = storage.get_all_sessions(
            page=page,
            page_size=page_size,
            search=search,
            status_filter=status_filter,
        )
    
    return SessionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        sessions=sessions,
    )


# ============ Session Detail API ============

@router.get("/sessions/{session_id}", response_model=SessionMeta)
async def get_session(session_id: str):
    """Get session details by ID
    
    - **session_id**: The session ID to retrieve
    """
    storage = get_session_storage()
    
    session = storage.get_session_meta(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}"
        )
    
    return session


# ============ Session Messages API ============

@router.get("/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
async def get_session_messages(session_id: str):
    """Get all messages and tool calls for a session
    
    - **session_id**: The session ID to retrieve messages for
    """
    storage = get_session_storage()
    
    # Check if session exists
    session = storage.get_session_meta(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}"
        )
    
    messages = storage.get_session_messages(session_id)
    tool_calls = storage.get_session_tool_calls(session_id)
    
    return SessionMessagesResponse(
        session_id=session_id,
        messages=messages,
        tool_calls=tool_calls,
    )


# ============ Delete Session API ============

@router.delete("/sessions/{session_id}", response_model=SuccessResponse)
async def delete_session(
    session_id: str,
    username: Optional[str] = Query(None, description="Username for index cleanup (optional)"),
):
    """Delete a session and all associated data
    
    This operation is idempotent - deleting a non-existent session returns success.
    
    - **session_id**: The session ID to delete
    - **username**: Optional username for user index cleanup
    """
    storage = get_session_storage()

    # Try to resolve meta for cleanup/cascade (operation is idempotent)
    meta = storage.get_session_meta(session_id)
    resolved_username = username or (meta.username if meta else None)

    # Cascade hard-delete task when deleting a task session (session_id = task_<taskId>)
    if session_id.startswith("task_"):
        task_id = session_id[len("task_"):]
        task_agent = (meta.agent_name if meta and meta.agent_name else "ubuntu")
        try:
            queue = _get_task_queue(task_agent)
            queue.delete_task_hard(task_id)
        except Exception:
            # best-effort
            pass

    # Delete session (idempotent)
    storage.delete_session(session_id, resolved_username)
    
    return SuccessResponse(
        success=True,
        message=f"Session {session_id} deleted"
    )


# ============ Cancel Session API ============

@router.post("/sessions/{session_id}/cancel", response_model=CancelResponse)
async def cancel_session(session_id: str):
    """Cancel a running session
    
    If the session is running, it will be marked as completed.
    If the session is not running, no action is taken.
    
    - **session_id**: The session ID to cancel
    """
    storage = get_session_storage()
    
    session = storage.get_session_meta(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}"
        )
    
    if session.status == SessionStatus.RUNNING:
        storage.update_session_status(session_id, SessionStatus.COMPLETED)
        return CancelResponse(success=True, cancelled=True)
    
    return CancelResponse(success=True, cancelled=False)


# ============ Task API ==========


class TaskItem(BaseModel):
    id: str
    description: str
    status: str
    priority: str
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    workspace: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    attempt_count: int = 0
    error_message: Optional[str] = None
    agent_name: Optional[str] = None
    session_id: Optional[str] = None  # Session ID for conversation storage


class TaskListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    tasks: List[TaskItem] = []


def _get_task_queue(agent_name: str) -> TaskQueue:
    return TaskQueue(db_path=None, agent_name=agent_name)


def _normalize_task_status(status_str: str) -> str:
    return status_str.strip().lower()


def _task_updated_at(task) -> Optional[datetime]:
    # Prefer completed_at > started_at > created_at
    for dt in (getattr(task, "completed_at", None), getattr(task, "started_at", None), getattr(task, "created_at", None)):
        if dt:
            return dt
    return None


def _task_to_item(task) -> TaskItem:
    status_val = task.status if isinstance(task.status, str) else task.status.value
    priority_val = task.priority if isinstance(task.priority, str) else task.priority.value
    session_id = getattr(task, "session_id", None) or f"task_{task.id}"
    return TaskItem(
        id=str(task.id),
        description=task.description,
        status=status_val,
        priority=priority_val,
        project_id=task.project_id,
        project_name=task.project_name,
        workspace=task.workspace,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        updated_at=_task_updated_at(task),
        attempt_count=int(task.attempt_count or 0),
        error_message=task.error_message,
        agent_name=task.agent_name,
        session_id=session_id,
    )


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    agent_name: str = Query("ubuntu", description="Agent name for task isolation"),
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
        status_filter = _normalize_task_status(status_param)
        allowed = {s.value for s in TaskStatus}
        if status_filter not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status_param}. Must be one of: {', '.join(sorted(allowed))}",
            )

    queue = _get_task_queue(agent_name)
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
        tasks=[_task_to_item(t) for t in tasks],
    )


@router.get("/tasks/{task_id}", response_model=TaskItem)
async def get_task(task_id: str, agent_name: str = Query("ubuntu", description="Agent name for task isolation")):
    """Get a single task detail."""
    queue = _get_task_queue(agent_name)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")
    return _task_to_item(task)


@router.delete("/tasks/{task_id}", response_model=SuccessResponse)
async def delete_task(task_id: str, agent_name: str = Query("ubuntu", description="Agent name for task isolation")):
    """Hard delete a task and its associated session."""
    queue = _get_task_queue(agent_name)

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


def _resolve_task_conversation_log_path(agent_name: str, task_id: str) -> Path:
    """解析任务对话日志路径。

    注意：`UserDirectoryManager` 在非 root 且 current_user != agent_name 时会降级到当前用户 HOME 下。
    这里必须复用相同规则，否则 UI 会一直拿不到对话记录。
    """
    session_id = f"task_{task_id}"
    preferred_dir = Path(settings.user_home_base) / agent_name / "sessions" / session_id

    current_user = pwd.getpwuid(os.getuid()).pw_name
    if current_user != agent_name and os.geteuid() != 0:
        base_dir = Path.home() / agent_name / "sessions" / session_id
    else:
        base_dir = preferred_dir

    return base_dir / ".claude" / "conversation.json"


def _sanitize_text(text: str) -> str:
    """尽量保留可见内容。

    说明：某些运行会把输出完全包在 `<think>...</think>` 里。
    如果我们直接剥离 think 段，会导致 UI 看起来"没有对话"。

    策略：优先尝试移除 think 段；若移除后为空，则回退到原文。
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


@router.get("/tasks/{task_id}/agui/messages")
async def get_task_agui_messages(
    task_id: str,
    agent_name: str = Query("ubuntu", description="Agent name for task isolation"),
    limit: Optional[int] = Query(None, ge=1, le=500, description="Max number of messages"),
    tail: Optional[int] = Query(None, ge=1, le=500, description="Return only the last N messages"),
):
    """Get task conversation log as an AGUI MessagesSnapshot.

    优先从 Redis 会话存储读取（任务执行时会归档 AG-UI 事件），
    如果没有归档数据，再回退到读取 `.claude/conversation.json`。
    """

    # Get task to retrieve session_id
    queue = _get_task_queue(agent_name)
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
    log_path = _resolve_task_conversation_log_path(agent_name=agent_name, task_id=task_id)

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


@router.get("/tasks/{task_id}/agui/stream", response_class=StreamingResponse)
async def stream_task_agui_messages(
    request: Request,
    task_id: str,
    agent_name: str = Query("ubuntu", description="Agent name for task isolation"),
    tail: Optional[int] = Query(200, ge=1, le=1000, description="Replay only the last N events on first connect"),
    poll_interval_ms: int = Query(300, ge=200, le=5000, description="Polling interval in ms"),
):
    """以 SSE 方式流式输出任务的 AG-UI 事件（参考 Chat 的 AGUI SSE）。

    说明：Task 在后台跑，浏览器拿不到 CCR 原始 SSE。
    我们在任务执行时把"转换后的 AG-UI 事件"写入 Redis 的事件日志，
    这里再把它们按顺序 SSE 推给前端，实现像 Chat 一样的流式回放。

    支持 `Last-Event-ID` 自动断线续传。
    """

    # Get task to retrieve session_id
    queue = _get_task_queue(agent_name)
    task = queue.get_task(task_id)
    session_id = (task.session_id if task else None) or f"task_{task_id}"
    storage = get_session_storage()

    def _parse_last_event_id() -> Optional[int]:
        v = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")
        if v is None:
            return None
        try:
            return int(str(v).strip())
        except Exception:
            return None

    async def generate():
        last_heartbeat = 0.0

        # cursor is the next event index to send
        last_id = _parse_last_event_id()
        total = storage.get_agui_event_count(session_id)
        if last_id is not None:
            cursor = max(0, last_id + 1)
        else:
            cursor = max(0, total - int(tail or 0))

        while True:
            # heartbeat（避免代理缓冲/断链）
            now = time.time()
            if now - last_heartbeat >= 15:
                last_heartbeat = now
                yield ": heartbeat\n\n"

            total = storage.get_agui_event_count(session_id)
            if total > cursor:
                events = storage.get_agui_events(session_id, start=cursor, end=total - 1)
                for idx, evt in enumerate(events, start=cursor):
                    try:
                        payload = json.dumps(evt, ensure_ascii=False)
                        yield f"id: {idx}\n" + f"data: {payload}\n\n"
                    except Exception:
                        continue
                cursor += len(events)

            await asyncio.sleep(poll_interval_ms / 1000.0)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

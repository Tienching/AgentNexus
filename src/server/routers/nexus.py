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
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field

from ..config import settings
from src.runtime.events.agui import AGUIMessage, MessageRole, MessagesSnapshotEvent
from ..models import (
    TaskStatus,
    TaskPriority,
    SessionMeta,
    SessionStatus,
    SessionListResponse,
    SessionMessagesResponse,
    MessageStatus,
)
from ..services.task_storage import TaskQueue
from src.runtime.commands.slash.handler import slugify_project
from ..providers import get_provider_registry
from ..services.session_storage import get_session_storage
from ..logger import get_logger
from .nexus_auth import verify_nexus_auth

logger = get_logger(__name__)

router = APIRouter(prefix="/api/nexus", tags=["nexus"], dependencies=[Depends(verify_nexus_auth)])


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


class AgentInfo(BaseModel):
    id: str
    username: str
    agent_type: str
    display_name: str
    available: bool = True


class AgentsResponse(BaseModel):
    agents: list[AgentInfo] = []


# ============ Usernames API ============

@router.get("/usernames", response_model=UsernamesResponse)
async def get_usernames():
    """Get all unique usernames from sessions
    
    Returns a sorted list of all usernames that have sessions.
    """
    storage = get_session_storage()
    usernames = storage.get_all_usernames()
    return UsernamesResponse(usernames=usernames)


# ============ Agents API ============

@router.get("/agents", response_model=AgentsResponse)
async def get_agents():
    """Get available agents by user and tool type.

    Returns a list of available agent configurations for the UI selector.
    """
    home_base = Path(settings.user_home_base)
    usernames: list[str] = []
    try:
        if home_base.exists():
            for entry in home_base.iterdir():
                if not entry.is_dir():
                    continue
                name = entry.name
                try:
                    pw = pwd.getpwnam(name)
                except KeyError:
                    continue
                if pw.pw_shell in ("/usr/sbin/nologin", "/sbin/nologin", "/bin/false", "/usr/bin/nologin"):
                    continue
                usernames.append(name)
        usernames = sorted(set(usernames))
    except Exception:
        usernames = []
    if not usernames:
        usernames = ["ubuntu"]

    agent_types = [
        {"type": "claude", "label": "claude"},
        {"type": "gemini", "label": "gemini"},
        {"type": "codex", "label": "codex"},
        {"type": "codebuddy", "label": "codebuddy"},
    ]

    agents: list[AgentInfo] = []
    for username in usernames:
        for entry in agent_types:
            agent_type = entry["type"]
            label = entry["label"]
            agents.append(AgentInfo(
                id=f"{username}::{agent_type}",
                username=username,
                agent_type=agent_type,
                display_name=f"{username} / {label}",
                available=True,
            ))

    return AgentsResponse(agents=agents)


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
    
    # Enrich sessions with exec_dir from Redis (stored separately from meta)
    for s in sessions:
        if not s.exec_dir:
            ed = storage.get_exec_dir_override(s.id)
            if ed:
                s.exec_dir = ed

    # Self-heal: fix sessions stuck in "running"
    for s in sessions:
        if s.status == SessionStatus.RUNNING:
            try:
                new_status = _self_heal_running_session(storage, s.id, s.updated_at)
                if new_status:
                    s.status = new_status
            except Exception:
                pass

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

    # For streaming messages, merge in the live streaming content from Redis
    # so that the snapshot API returns text even during task execution.
    for msg in messages:
        if msg.status == MessageStatus.STREAMING and not msg.content:
            streaming_content = storage.get_streaming_content(session_id, msg.id)
            if streaming_content:
                msg.content = streaming_content
    
    # Include cli_session_id if this session was promoted from CLI history
    cli_session_id = storage.get_cli_session_id(session_id)

    return SessionMessagesResponse(
        session_id=session_id,
        messages=messages,
        tool_calls=tool_calls,
        session=session,
        cli_session_id=cli_session_id or None,
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

    # Cascade hard-delete associated task (best-effort)
    task_agent = (meta.exec_user if meta and meta.exec_user else "ubuntu")
    try:
        queue = _get_task_queue(task_agent)
        linked_task = queue.find_task_by_session_id(session_id)
        if linked_task:
            queue.delete_task_hard(linked_task.id)
    except Exception:
        # best-effort
        pass

    # Delete session (idempotent)
    storage.delete_session(session_id, resolved_username)
    
    return SuccessResponse(
        success=True,
        message=f"Session {session_id} deleted"
    )


# ============ Bulk Delete Sessions API ============

class SessionBulkRequest(BaseModel):
    session_ids: List[str] = Field(default_factory=list)


class SessionBulkResponse(SuccessResponse):
    result: Dict[str, Any] = Field(default_factory=dict)


@router.post("/sessions/bulk_delete", response_model=SessionBulkResponse)
async def bulk_delete_sessions(
    request: SessionBulkRequest,
):
    """Batch delete sessions and their associated data.

    This endpoint deletes multiple sessions at once, including any
    associated task data for task sessions (session_id starting with 'task_').
    """
    session_ids = [str(sid) for sid in (request.session_ids or [])]
    if not session_ids:
        raise HTTPException(status_code=400, detail="session_ids is required")
    if len(session_ids) > 500:
        raise HTTPException(status_code=400, detail="session_ids too large (max 500)")

    storage = get_session_storage()

    deleted: List[str] = []
    skipped: Dict[str, str] = {}

    for session_id in session_ids:
        try:
            # Get session meta for cleanup
            meta = storage.get_session_meta(session_id)

            # Cascade hard-delete associated task (best-effort)
            task_agent = (meta.exec_user if meta and meta.exec_user else "ubuntu")
            try:
                queue = _get_task_queue(task_agent)
                linked_task = queue.find_task_by_session_id(session_id)
                if linked_task:
                    queue.delete_task_hard(linked_task.id)
            except Exception:
                pass

            # Delete session
            resolved_username = meta.username if meta else None
            storage.delete_session(session_id, resolved_username)
            deleted.append(session_id)

        except Exception as e:
            skipped[session_id] = f"error:{e}"

    result = {"count": len(deleted), "deleted": deleted, "skipped": skipped}
    return SessionBulkResponse(success=True, message=f"Deleted {len(deleted)} sessions", result=result)


@router.post("/sessions/delete_all", response_model=SessionBulkResponse)
async def delete_all_sessions(
    username: Optional[str] = Query(None, description="Only delete sessions for this username"),
    search: Optional[str] = Query(None, description="Only delete sessions matching this search term"),
    status_param: Optional[str] = Query(None, alias="status", description="Only delete sessions with this status"),
):
    """Delete ALL sessions matching the given filters (no pagination limit).

    This is useful when 'Select All' in the UI only covers the loaded page.
    Cascade-deletes associated tasks.
    """
    storage = get_session_storage()

    status_filter = None
    if status_param:
        try:
            status_filter = SessionStatus(status_param)
        except ValueError:
            pass

    # Fetch ALL matching sessions (no pagination)
    if username:
        sessions, _total = storage.get_user_sessions(
            username=username, page=1, page_size=10000,
            search=search, status_filter=status_filter,
        )
    else:
        sessions, _total = storage.get_all_sessions(
            page=1, page_size=10000,
            search=search, status_filter=status_filter,
        )

    deleted: List[str] = []
    skipped: Dict[str, str] = {}

    for meta in sessions:
        session_id = meta.id
        try:
            # Cascade hard-delete associated task (best-effort)
            task_agent = (meta.exec_user if meta.exec_user else "ubuntu")
            try:
                queue = _get_task_queue(task_agent)
                linked_task = queue.find_task_by_session_id(session_id)
                if linked_task:
                    queue.delete_task_hard(linked_task.id)
            except Exception:
                pass

            resolved_username = meta.username or username
            storage.delete_session(session_id, resolved_username)
            deleted.append(session_id)
        except Exception as e:
            skipped[session_id] = f"error:{e}"

    result = {"count": len(deleted), "deleted": deleted, "skipped": skipped}
    return SessionBulkResponse(success=True, message=f"Deleted {len(deleted)} sessions", result=result)


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


# ============ Session Files API ============

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


def _resolve_session_folder(session_id: str, exec_user: str) -> Optional[Path]:
    """Resolve the folder path for a session.

    - Regular session: /home/{exec_user}/.nexus/sessions/{session_id}/
    - Task session with inplace workspace: workspace directory from task
    """
    current_user = pwd.getpwuid(os.getuid()).pw_name

    # Check if this is a task session (has task_id in meta) and has an inplace workspace
    try:
        from ..services.session_storage import get_session_storage
        storage = get_session_storage()
        task_id = storage._redis.hget(f"session:{session_id}:meta", "task_id")
        if task_id:
            queue = _get_task_queue(exec_user)
            task = queue.get_task(task_id)
            if task and task.workspace:
                workspace_path = Path(task.workspace)
                if workspace_path.exists():
                    return workspace_path
    except Exception:
        pass

    # Default session folder path
    if current_user != exec_user and os.geteuid() != 0:
        base_dir = Path.home() / exec_user / ".nexus" / "sessions" / session_id
    else:
        base_dir = Path(settings.user_home_base) / exec_user / ".nexus" / "sessions" / session_id

    return base_dir if base_dir.exists() else None


@router.get("/sessions/{session_id}/files", response_model=SessionFilesResponse)
async def list_session_files(
    session_id: str,
    exec_user: str = Query(settings.exec_user, description="Exec user name"),
    subpath: str = Query("", description="Subdirectory path within session folder"),
):
    """List files in a session's folder.

    - **session_id**: The session ID
    - **exec_user**: Exec user for folder resolution
    - **subpath**: Optional subdirectory path
    """
    folder = _resolve_session_folder(session_id, exec_user)

    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session folder not found for: {session_id}"
        )

    # Handle subpath
    target_path = folder
    if subpath:
        # Prevent directory traversal attacks
        safe_subpath = Path(subpath).as_posix()
        if ".." in safe_subpath:
            raise HTTPException(status_code=400, detail="Invalid path")
        target_path = folder / safe_subpath
        if not target_path.exists():
            raise HTTPException(status_code=404, detail=f"Path not found: {subpath}")
        if not str(target_path.resolve()).startswith(str(folder.resolve())):
            raise HTTPException(status_code=400, detail="Invalid path")

    files: List[FileItem] = []

    try:
        for entry in sorted(target_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            # Skip hidden files starting with .
            if entry.name.startswith("."):
                continue

            stat = entry.stat()
            modified_time = datetime.fromtimestamp(stat.st_mtime).isoformat()

            # Calculate relative path from session folder
            rel_path = str(entry.relative_to(folder))

            files.append(FileItem(
                name=entry.name,
                path=rel_path,
                is_dir=entry.is_dir(),
                size=stat.st_size if entry.is_file() else None,
                modified=modified_time,
            ))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")
    except Exception as e:
        logger.error(f"Failed to list session files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list files")

    return SessionFilesResponse(
        session_id=session_id,
        folder_path=str(folder),
        files=files,
    )


@router.get("/sessions/{session_id}/files/download")
async def download_session_file(
    session_id: str,
    file_path: str = Query(..., description="File path relative to session folder"),
    exec_user: str = Query(settings.exec_user, description="Exec user name"),
):
    """Download a file from session folder.

    - **session_id**: The session ID
    - **file_path**: File path relative to session folder
    - **exec_user**: Exec user for folder resolution
    """
    folder = _resolve_session_folder(session_id, exec_user)

    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session folder not found for: {session_id}"
        )

    # Prevent directory traversal attacks
    safe_path = Path(file_path).as_posix()
    if ".." in safe_path:
        raise HTTPException(status_code=400, detail="Invalid path")

    target_file = folder / safe_path

    # Verify the file is within the session folder
    if not str(target_file.resolve()).startswith(str(folder.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target_file.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    if not target_file.is_file():
        raise HTTPException(status_code=400, detail="Cannot download directory")

    return FileResponse(
        path=str(target_file),
        filename=target_file.name,
        media_type="application/octet-stream",
    )


# ============ Task API ==========


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
    exec_user: Optional[str] = None
    session_id: Optional[str] = None  # Session ID for conversation storage
    depends_on: List[str] = Field(default_factory=list)  # Task dependencies
    # Ralph Loop fields
    loop_enabled: bool = False
    loop_iteration: int = 0
    loop_max_iterations: int = 1
    loop_keywords: List[str] = Field(default_factory=list)
    loop_keyword_found: bool = False


class TaskListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    tasks: List[TaskItem] = []


class TaskBulkRequest(BaseModel):
    task_ids: List[str] = Field(default_factory=list)


class TaskBulkResponse(SuccessResponse):
    result: Dict[str, Any] = Field(default_factory=dict)


def _get_task_queue(exec_user: str) -> TaskQueue:
    return TaskQueue(db_path=None, exec_user=exec_user)


def _normalize_task_status(status_str: str) -> str:
    return status_str.strip().lower()


def _task_updated_at(task) -> Optional[datetime]:
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


def _task_to_item(task) -> TaskItem:
    status_val = task.status if isinstance(task.status, str) else task.status.value
    priority_val = task.priority if isinstance(task.priority, str) else task.priority.value
    session_id = getattr(task, "session_id", None) or f"task_{task.id}"
    depends_on = getattr(task, "depends_on", None) or []
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
        updated_at=_task_updated_at(task),
        attempt_count=int(task.attempt_count or 0),
        error_message=task.error_message,
        exec_user=task.exec_user,
        session_id=session_id,
        depends_on=depends_on,
        loop_enabled=getattr(task, "loop_enabled", False),
        loop_iteration=getattr(task, "loop_iteration", 0),
        loop_max_iterations=getattr(task, "loop_max_iterations", 1),
        loop_keywords=getattr(task, "loop_keywords", []) or [],
        loop_keyword_found=getattr(task, "loop_keyword_found", False),
    )


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


@router.get("/projects", response_model=List[ProjectItem])
async def list_projects(exec_user: str = Query(settings.exec_user, description="Exec user for task isolation")):
    """Get all unique projects from existing tasks."""
    queue = _get_task_queue(exec_user)
    return queue.get_projects()


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
        status_filter = _normalize_task_status(status_param)
        allowed = {s.value for s in TaskStatus}
        if status_filter not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status_param}. Must be one of: {', '.join(sorted(allowed))}",
            )

    queue = _get_task_queue(exec_user)
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
async def get_task(task_id: str, exec_user: str = Query(settings.exec_user, description="Exec user for task isolation")):
    """Get a single task detail."""
    queue = _get_task_queue(exec_user)
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_id}")
    return _task_to_item(task)


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
    provider = (request.provider or "").strip().lower() or default_provider
    allowed = set(get_provider_registry().list_providers())
    if provider not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}")
    alias_value = (request.alias or "").strip() or default_alias or provider

    default_exec_user = (settings.default_exec_user or "").strip() or None
    effective_exec_user = (request.exec_user or "").strip() or default_exec_user

    project_name = (request.project_name or "").strip() or None
    project_id = (request.project_id or "").strip() or None
    if project_name and not project_id:
        project_id = slugify_project(project_name)

    priority = TaskPriority.PROJECT if (project_name or project_id) else TaskPriority.THOUGHT

    queue = _get_task_queue(exec_user)
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

    return _task_to_item(task)


class BulkCreateTaskRequest(BaseModel):
    """Batch create multiple tasks at once."""
    tasks: List[CreateTaskRequest] = Field(..., description="List of tasks to create (max 50)")


class BulkCreateTaskResponse(BaseModel):
    """Response for batch task creation."""
    success: bool = True
    created: List[TaskItem] = Field(default_factory=list)
    errors: List[Dict[str, str]] = Field(default_factory=list)


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
    
    queue = _get_task_queue(exec_user)
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
            
            task_item = _task_to_item(task)
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
    queue = _get_task_queue(exec_user)

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


class UpdateTaskStatusRequest(BaseModel):
    status: str = Field(..., description="New task status (todo/doing/done/failed/cancelled/archived)")


@router.patch("/tasks/{task_id}/status", response_model=TaskItem)
async def update_task_status(
    task_id: str,
    request: UpdateTaskStatusRequest,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
):
    """Manually update task status.
    
    Used to unblock dependent tasks or cancel blocked tasks.
    """
    queue = _get_task_queue(exec_user)
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
    
    return _task_to_item(updated_task)


class ChatContinueRequest(BaseModel):
    message: str = Field(..., description="Follow-up message to send to the task")
    model: Optional[str] = Field(None, description="Override model for this run (optional)")


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
    queue = _get_task_queue(exec_user)
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

    return _task_to_item(updated)


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

    queue = _get_task_queue(exec_user)
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

    queue = _get_task_queue(exec_user)
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

    queue = _get_task_queue(exec_user)

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

    queue = _get_task_queue(exec_user)
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


def _resolve_task_conversation_log_path(exec_user: str, task_id: str) -> Path:
    """解析任务对话日志路径。

    注意：`UserDirectoryManager` 在非 root 且 current_user != exec_user 时会降级到当前用户 HOME 下。
    这里必须复用相同规则，否则 UI 会一直拿不到对话记录。
    """
    session_id = f"task_{task_id}"
    preferred_dir = Path(settings.user_home_base) / exec_user / ".nexus" / "sessions" / session_id

    current_user = pwd.getpwuid(os.getuid()).pw_name
    if current_user != exec_user and os.geteuid() != 0:
        base_dir = Path.home() / exec_user / ".nexus" / "sessions" / session_id
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
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
    limit: Optional[int] = Query(None, ge=1, le=5000, description="Max number of messages"),
    tail: Optional[int] = Query(None, ge=1, le=5000, description="Return only the last N messages"),
):
    """Get task conversation log as an AGUI MessagesSnapshot.

    优先从 Redis 会话存储读取（任务执行时会归档 AG-UI 事件），
    如果没有归档数据，再回退到读取 `.claude/conversation.json`。
    """

    # Get task to retrieve session_id
    queue = _get_task_queue(exec_user)
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
    log_path = _resolve_task_conversation_log_path(exec_user=exec_user, task_id=task_id)

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


# ============ SSE Streaming Helpers ============


def _parse_last_event_id(request: Request) -> Optional[int]:
    """Parse Last-Event-ID header for SSE reconnection support."""
    v = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")
    if v is None:
        return None
    try:
        return int(str(v).strip())
    except Exception:
        return None


def _self_heal_running_session(storage, session_id: str, updated_at) -> Optional[SessionStatus]:
    """Check if a session stuck in RUNNING should be healed, and fix it if so.

    Scans the last N events for RUN_STARTED / RUN_FINISHED / RUN_ERROR.
    Only heals if the terminal event appears AFTER the last RUN_STARTED.
    Falls back to stale-timeout healing (cli_timeout + 60s) if no terminal event found.

    Returns the new status if healed, or None if no healing was performed.
    """
    updated_at_ms = 0
    if updated_at is not None:
        try:
            updated_at_ms = int(updated_at)
        except (ValueError, TypeError):
            pass

    now_ms = int(time.time() * 1000)
    recently_updated = updated_at_ms > 0 and (now_ms - updated_at_ms) < 30_000
    if recently_updated:
        return None

    # Scan last events for terminal markers
    healed = False
    total_events = storage.get_agui_event_count(session_id)
    if total_events > 0:
        scan_count = min(total_events, 20)
        last_events = storage.get_agui_events(
            session_id,
            start=max(0, total_events - scan_count),
            end=total_events - 1,
        )
        last_started_idx = -1
        last_terminal_idx = -1
        last_terminal_type = None
        for idx, evt in enumerate(last_events):
            if isinstance(evt, dict):
                if evt.get("type") == "RUN_STARTED":
                    last_started_idx = idx
                elif evt.get("type") in ("RUN_FINISHED", "RUN_ERROR"):
                    last_terminal_idx = idx
                    last_terminal_type = evt.get("type")

        if last_terminal_idx > last_started_idx and last_terminal_type:
            new_status = SessionStatus.ERROR if last_terminal_type == "RUN_ERROR" else SessionStatus.COMPLETED
            storage.update_session_status(session_id, new_status)
            logger.info(f"Self-healed session {session_id} status: running -> {new_status.value}")
            return new_status

    # Stale timeout: cli_timeout + 60 seconds with no terminal event
    stale_threshold_seconds = max(int(getattr(settings, "cli_timeout", 600) or 600) + 60, 60)
    stale_threshold_ms = stale_threshold_seconds * 1000
    if updated_at_ms > 0 and (now_ms - updated_at_ms) > stale_threshold_ms:
        storage.update_session_status(session_id, SessionStatus.COMPLETED)
        logger.info(f"Self-healed stale session {session_id} status: running -> completed (stale {(now_ms - updated_at_ms) // 1000}s)")
        return SessionStatus.COMPLETED

    return None


def _compute_initial_cursor(
    storage,
    session_id: str,
    total: int,
    tail: int,
    *,
    smart_cursor: bool = False,
) -> int:
    """Compute the starting cursor for SSE event replay.

    Args:
        smart_cursor: If True (session stream), scan for the last RUN_STARTED
            event and start from there to avoid replaying a previous run's
            RUN_FINISHED which would close the stream immediately.
    """
    raw_cursor = max(0, total - tail)

    if not smart_cursor or total <= 0:
        return raw_cursor

    scan_start = max(0, total - min(total, tail))
    try:
        scan_events = storage.get_agui_events(session_id, start=scan_start, end=total - 1)
        last_run_started_offset = -1
        for offset, evt in enumerate(scan_events):
            if isinstance(evt, dict) and evt.get("type") == "RUN_STARTED":
                last_run_started_offset = offset
        if last_run_started_offset >= 0:
            return scan_start + last_run_started_offset
    except Exception:
        pass
    return raw_cursor


async def _sse_generate_events(
    request: Request,
    storage,
    session_id: str,
    cursor: int,
    poll_interval_ms: int,
    idle_timeout_check,
):
    """Shared SSE async generator for streaming AG-UI events.

    Args:
        idle_timeout_check: Async callable(idle_cycles) -> bool.
            Called when idle_cycles exceeds max_idle_cycles.
            Return True to close the stream, False to keep waiting.
    """
    last_heartbeat = 0.0
    idle_cycles = 0
    max_idle_cycles = 600  # ~3 min of idle at default 300ms interval
    is_initial_replay = True

    while True:
        if await request.is_disconnected():
            break

        # Heartbeat to prevent proxy buffering / connection drops
        now = time.time()
        if now - last_heartbeat >= 15:
            last_heartbeat = now
            yield ": heartbeat\n\n"

        total = storage.get_agui_event_count(session_id)
        if total > cursor:
            idle_cycles = 0
            events = storage.get_agui_events(session_id, start=cursor, end=total - 1)
            batch_size = len(events)
            for i, (idx, evt) in enumerate(zip(range(cursor, cursor + batch_size), events)):
                try:
                    payload = json.dumps(evt, ensure_ascii=False)
                    yield f"id: {idx}\ndata: {payload}\n\n"
                    if isinstance(evt, dict) and evt.get("type") in ("RUN_FINISHED", "RUN_ERROR"):
                        return
                except Exception:
                    continue
                # During initial replay, add small delays every few events
                # so the frontend renders progressively
                if is_initial_replay and batch_size > 10 and (i + 1) % 5 == 0:
                    await asyncio.sleep(0.02)
            cursor += batch_size
            is_initial_replay = False
        else:
            idle_cycles += 1
            is_initial_replay = False
            if idle_cycles > max_idle_cycles:
                if await idle_timeout_check():
                    return

        await asyncio.sleep(poll_interval_ms / 1000.0)


def _make_sse_response(generator) -> StreamingResponse:
    """Wrap an async generator into a standard SSE StreamingResponse."""
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============ SSE Streaming Endpoints ============


@router.get("/tasks/{task_id}/agui/stream", response_class=StreamingResponse)
async def stream_task_agui_messages(
    request: Request,
    task_id: str,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
    tail: Optional[int] = Query(200, ge=1, le=5000, description="Replay only the last N events on first connect"),
    poll_interval_ms: int = Query(300, ge=200, le=5000, description="Polling interval in ms"),
):
    """以 SSE 方式流式输出任务的 AG-UI 事件（参考 Chat 的 AGUI SSE）。

    说明：Task 在后台跑，浏览器拿不到 CLI 原始 SSE。
    我们在任务执行时把"转换后的 AG-UI 事件"写入 Redis 的事件日志，
    这里再把它们按顺序 SSE 推给前端，实现像 Chat 一样的流式回放。

    支持 `Last-Event-ID` 自动断线续传。
    """
    queue = _get_task_queue(exec_user)
    task = queue.get_task(task_id)
    session_id = (task.session_id if task else None) or f"task_{task_id}"
    storage = get_session_storage()

    # Self-heal stuck sessions
    try:
        session_meta = storage.get_session_meta(session_id)
        if session_meta and session_meta.status == SessionStatus.RUNNING:
            _self_heal_running_session(storage, session_id, session_meta.updated_at)
    except Exception as e:
        logger.warning(f"Failed to self-heal task session status: {e}")

    # Compute initial cursor
    last_id = _parse_last_event_id(request)
    total = storage.get_agui_event_count(session_id)
    if last_id is not None:
        cursor = max(0, last_id + 1)
    else:
        cursor = _compute_initial_cursor(storage, session_id, total, int(tail or 200))

    async def check_task_idle_timeout() -> bool:
        try:
            task_obj = queue.get_task(task_id)
            if task_obj and task_obj.status in ("done", "failed", "cancelled"):
                return True
        except Exception:
            pass
        return False

    return _make_sse_response(
        _sse_generate_events(request, storage, session_id, cursor, poll_interval_ms, check_task_idle_timeout)
    )


@router.get("/sessions/{session_id}/agui/stream", response_class=StreamingResponse)
async def stream_session_agui_messages(
    request: Request,
    session_id: str,
    tail: Optional[int] = Query(200, ge=1, le=5000, description="Replay only the last N events on first connect"),
    poll_interval_ms: int = Query(300, ge=200, le=5000, description="Polling interval in ms"),
):
    """以 SSE 方式流式输出 session 的 AG-UI 事件。

    适用于 channel session（如企微 channel_wecom_*）等非 Chat 直连场景，
    让 Nexus 前端在消息处理中也能看到实时流式输出。

    支持 `Last-Event-ID` 自动断线续传。
    """
    storage = get_session_storage()

    meta = storage.get_session_meta(session_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Session not found")

    # Self-heal stuck sessions
    if meta.status == SessionStatus.RUNNING:
        try:
            new_status = _self_heal_running_session(storage, session_id, meta.updated_at)
            if new_status:
                meta.status = new_status
        except Exception as e:
            logger.warning(f"Failed to self-heal session status: {e}")

    # Compute initial cursor (with smart cursor for session streams)
    last_id = _parse_last_event_id(request)
    total = storage.get_agui_event_count(session_id)
    if last_id is not None:
        cursor = max(0, last_id + 1)
    else:
        cursor = _compute_initial_cursor(
            storage, session_id, total, int(tail or 200), smart_cursor=True,
        )

    async def check_session_idle_timeout() -> bool:
        try:
            current_meta = storage.get_session_meta(session_id)
            if current_meta and current_meta.status not in (
                SessionStatus.RUNNING, SessionStatus.PENDING
            ):
                return True
        except Exception:
            pass
        return False

    return _make_sse_response(
        _sse_generate_events(request, storage, session_id, cursor, poll_interval_ms, check_session_idle_timeout)
    )


# ============ Server Defaults API ============

class ServerDefaultsResponse(BaseModel):
    exec_user: str = ""
    default_provider: str = ""
    default_alias: str = ""
    default_exec_user: str = ""


@router.get("/defaults", response_model=ServerDefaultsResponse)
async def get_server_defaults():
    """Return .env default configuration values for the UI to use as initial defaults."""
    return ServerDefaultsResponse(
        exec_user=settings.exec_user or "",
        default_provider=settings.default_provider or "",
        default_alias=settings.default_alias or "",
        default_exec_user=settings.default_exec_user or "",
    )


# ============ Skills API ============

# Default provider -> config directory name mapping
_PROVIDER_CONFIG_DIRS = {
    "claude": ".claude",
    "codebuddy": ".codebuddy",
    "codex": ".codex",
    "gemini": ".gemini",
}

# Known providers that have standard skills directories
_KNOWN_PROVIDERS = set(_PROVIDER_CONFIG_DIRS.keys())

# Valid skill name pattern (prevent path injection)
_SKILL_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$')


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


def _parse_skill_md(file_path: Path) -> dict:
    """Parse SKILL.md frontmatter (name, description, version) using regex."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    # Match YAML frontmatter between --- delimiters
    fm_match = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if not fm_match:
        return {}

    result = {}
    for line in fm_match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # Simple key: value parsing (handles quoted and unquoted values)
        m = re.match(r'^(\w+)\s*:\s*"?([^"]*)"?\s*$', line)
        if m:
            result[m.group(1)] = m.group(2).strip()
    return result


def _scan_skills_dir(skills_dir: Path, provider: str) -> List[SkillInfo]:
    """Scan a skills directory and return list of SkillInfo."""
    skills = []
    if not skills_dir.is_dir():
        return skills

    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith('.') or entry.name == 'learned':
            continue
        skill_md = entry / "SKILL.md"
        if skill_md.is_file():
            meta = _parse_skill_md(skill_md)
            skills.append(SkillInfo(
                name=meta.get("name", entry.name),
                description=meta.get("description", ""),
                version=meta.get("version", ""),
                provider=provider,
                path=str(entry),
            ))
    return skills


@router.get("/skills", response_model=SkillsResponse)
async def get_skills(
    exec_user: str = Query(default="", description="Exec user for home directory resolution"),
    custom_paths: str = Query(default="", description="JSON-encoded dict of alias->skills_path"),
):
    """Scan provider skills directories and return discovered skills."""
    user = exec_user or settings.exec_user or "ubuntu"
    home_base = settings.user_home_base or "/home"
    user_home = Path(home_base) / user

    # Parse custom alias paths
    alias_paths: Dict[str, str] = {}
    if custom_paths:
        try:
            alias_paths = json.loads(custom_paths)
        except (json.JSONDecodeError, TypeError):
            pass

    result: Dict[str, List[SkillInfo]] = {}

    def _resolve_tilde(path_str: str) -> Path:
        """Resolve ~ or ~/ to the target user home directory."""
        if path_str.startswith("~/") or path_str == "~":
            return user_home / path_str[2:] if len(path_str) > 2 else user_home
        return Path(path_str)

    def _scan_all():
        # Scan default providers
        for provider, config_dir in _PROVIDER_CONFIG_DIRS.items():
            skills_dir = user_home / config_dir / "skills"
            result[provider] = _scan_skills_dir(skills_dir, provider)

        # Scan custom alias paths
        for alias_name, path_str in alias_paths.items():
            if alias_name in _KNOWN_PROVIDERS:
                continue  # Skip if it's a known provider (already scanned)
            skills_dir = _resolve_tilde(path_str)
            if skills_dir.is_absolute():
                result[alias_name] = _scan_skills_dir(skills_dir, alias_name)
            else:
                logger.warning(f"Skipping non-absolute skills path for alias '{alias_name}': {path_str}")

    await asyncio.to_thread(_scan_all)
    return SkillsResponse(providers=result)


@router.post("/skills", response_model=SuccessResponse)
async def create_skill(request: CreateSkillRequest):
    """Create a new skill in the provider's skills directory."""
    provider = (request.provider or "").strip().lower()
    skill_name = (request.skill_name or "").strip()

    if not provider:
        raise HTTPException(status_code=400, detail="provider is required")
    if not skill_name:
        raise HTTPException(status_code=400, detail="skill_name is required")
    if not _SKILL_NAME_RE.match(skill_name):
        raise HTTPException(
            status_code=400,
            detail="Invalid skill name. Only letters, numbers, hyphens, dots, and underscores are allowed.",
        )

    # Determine skills directory
    user = settings.exec_user or "ubuntu"
    home_base = settings.user_home_base or "/home"
    user_home = Path(home_base) / user

    if request.skills_path:
        raw = request.skills_path
        if raw.startswith("~/") or raw == "~":
            skills_dir = user_home / raw[2:] if len(raw) > 2 else user_home
        else:
            skills_dir = Path(raw)
        if not skills_dir.is_absolute():
            raise HTTPException(status_code=400, detail="skills_path must be an absolute path")
    elif provider in _PROVIDER_CONFIG_DIRS:
        skills_dir = user_home / _PROVIDER_CONFIG_DIRS[provider] / "skills"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider}'. Provide skills_path for custom aliases.",
        )

    skill_dir = (skills_dir / skill_name).resolve()
    if not str(skill_dir).startswith(str(skills_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid skill path")

    def _create():
        if skill_dir.exists():
            raise FileExistsError(f"Skill '{skill_name}' already exists at {skill_dir}")
        skill_dir.mkdir(parents=True, exist_ok=False)
        # Build SKILL.md
        frontmatter = f"---\nname: {skill_name}\ndescription: {request.description}\n---\n\n"
        body = request.content or f"# {skill_name}\n"
        (skill_dir / "SKILL.md").write_text(frontmatter + body, encoding="utf-8")

    try:
        await asyncio.to_thread(_create)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied writing to {skills_dir}")
    except Exception as e:
        logger.error(f"Failed to create skill '{skill_name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create skill: {e}")

    logger.info(f"Created skill '{skill_name}' for provider '{provider}' at {skill_dir}")
    return SuccessResponse(message=f"Skill '{skill_name}' created successfully")


@router.delete("/skills/{provider}/{skill_name}", response_model=SuccessResponse)
async def delete_skill(
    provider: str,
    skill_name: str,
    exec_user: str = Query(default="", description="Exec user for home directory resolution"),
    skills_path: Optional[str] = Query(default=None, description="Custom skills directory path"),
):
    """Delete a skill directory."""
    provider = (provider or "").strip().lower()
    skill_name = (skill_name or "").strip()

    if not skill_name or not _SKILL_NAME_RE.match(skill_name):
        raise HTTPException(status_code=400, detail="Invalid skill name")

    # Determine skills directory
    user = exec_user or settings.exec_user or "ubuntu"
    home_base = settings.user_home_base or "/home"
    user_home = Path(home_base) / user

    if skills_path:
        raw = skills_path
        if raw.startswith("~/") or raw == "~":
            skills_dir = user_home / raw[2:] if len(raw) > 2 else user_home
        else:
            skills_dir = Path(raw)
        if not skills_dir.is_absolute():
            raise HTTPException(status_code=400, detail="skills_path must be an absolute path")
    elif provider in _PROVIDER_CONFIG_DIRS:
        skills_dir = user_home / _PROVIDER_CONFIG_DIRS[provider] / "skills"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider}'. Provide skills_path for custom aliases.",
        )

    skill_dir = (skills_dir / skill_name).resolve()
    if not str(skill_dir).startswith(str(skills_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid skill path")

    def _delete():
        if not skill_dir.exists():
            raise FileNotFoundError(f"Skill '{skill_name}' not found at {skill_dir}")
        if not skill_dir.is_dir():
            raise ValueError(f"'{skill_dir}' is not a directory")
        shutil.rmtree(skill_dir)

    try:
        await asyncio.to_thread(_delete)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied deleting {skill_dir}")
    except Exception as e:
        logger.error(f"Failed to delete skill '{skill_name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete skill: {e}")

    logger.info(f"Deleted skill '{skill_name}' for provider '{provider}' at {skill_dir}")
    return SuccessResponse(message=f"Skill '{skill_name}' deleted successfully")


# ============ Concurrency Config API ============

class ConcurrencyConfigResponse(BaseModel):
    global_max_concurrency: int = 0
    provider_concurrency: Dict[str, int] = Field(default_factory=dict)


class SetProviderConcurrencyRequest(BaseModel):
    name: str = Field(..., description="Provider or alias name")
    limit: int = Field(..., ge=0, description="Max concurrency (0 = remove limit)")


class SetGlobalConcurrencyRequest(BaseModel):
    limit: int = Field(..., ge=0, description="Global max concurrency (0 = unlimited)")


@router.get("/concurrency", response_model=ConcurrencyConfigResponse)
async def get_concurrency_config():
    """Get the current concurrency configuration."""
    from src.runtime.stores.concurrency_config import get_concurrency_config_store
    store = get_concurrency_config_store()
    cfg = store.get_all()
    return ConcurrencyConfigResponse(**cfg)


@router.post("/concurrency/provider", response_model=SuccessResponse)
async def set_provider_concurrency(request: SetProviderConcurrencyRequest):
    """Set max concurrency for a provider or alias."""
    from src.runtime.stores.concurrency_config import get_concurrency_config_store
    from src.runtime.execution.task_executor import get_executor

    store = get_concurrency_config_store()
    name = (request.name or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    try:
        ok = store.set_provider_concurrency(name, request.limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not ok:
        raise HTTPException(status_code=500, detail="Failed to set provider concurrency")

    # Hot-reload
    executor = get_executor()
    if executor:
        executor.set_provider_concurrency(name, request.limit)

    return SuccessResponse(message=f"Provider '{name}' concurrency set to {request.limit}")


@router.delete("/concurrency/provider/{name}", response_model=SuccessResponse)
async def remove_provider_concurrency(name: str):
    """Remove concurrency limit for a provider or alias."""
    from src.runtime.stores.concurrency_config import get_concurrency_config_store
    from src.runtime.execution.task_executor import get_executor

    store = get_concurrency_config_store()
    name = (name or "").strip().lower()
    store.remove_provider_concurrency(name)

    executor = get_executor()
    if executor:
        executor.set_provider_concurrency(name, 0)

    return SuccessResponse(message=f"Provider '{name}' concurrency limit removed")


@router.post("/concurrency/global", response_model=SuccessResponse)
async def set_global_concurrency(request: SetGlobalConcurrencyRequest):
    """Set global max concurrency (0 = unlimited)."""
    from src.runtime.stores.concurrency_config import get_concurrency_config_store
    from src.runtime.execution.task_executor import get_executor

    store = get_concurrency_config_store()
    try:
        ok = store.set_global_concurrency(request.limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not ok:
        raise HTTPException(status_code=500, detail="Failed to set global concurrency")

    executor = get_executor()
    if executor:
        executor.set_global_concurrency(request.limit)

    return SuccessResponse(message=f"Global concurrency set to {request.limit}")

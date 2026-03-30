# -*- coding: utf-8 -*-
"""Nexus Sessions API Router

Provides REST API endpoints for session management:
- List sessions with pagination/filtering
- Get session details and messages
- Delete sessions (single, bulk, delete-all)
- Cancel running sessions
"""

from __future__ import annotations

import pwd
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..config import settings
from ..models import (
    SessionMeta,
    SessionStatus,
    SessionListResponse,
    SessionMessagesResponse,
    MessageStatus,
)
from ..services.session_storage import get_session_storage
from ..logger import get_logger
from .nexus_auth import verify_nexus_auth
from .nexus_models import (
    SuccessResponse,
    CancelResponse,
    UsernamesResponse,
    AgentInfo,
    AgentsResponse,
    SessionBulkRequest,
    SessionBulkResponse,
    get_task_queue,
)
from .nexus_streaming import self_heal_running_session

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-sessions"],
    dependencies=[Depends(verify_nexus_auth)],
)


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
                new_status = self_heal_running_session(storage, s.id, s.updated_at)
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
        queue = get_task_queue(task_agent)
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
                queue = get_task_queue(task_agent)
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
                queue = get_task_queue(task_agent)
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


# ============ Tmux Command API ============

@router.get("/sessions/{session_id}/tmux-command")
async def get_tmux_command(session_id: str):
    """Get a tmux command to attach to this session's CLI conversation.

    Returns a shell command that:
      1. Creates (or attaches to) a tmux session named ``nexus-<short_id>``
      2. Runs the appropriate CLI tool (e.g. ``claude -c``) inside the session's
         working directory so the user can continue the conversation interactively.

    - **session_id**: The session ID to generate the tmux command for
    """
    storage = get_session_storage()

    session = storage.get_session_meta(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    # Resolve working directory
    exec_dir = session.exec_dir or storage.get_exec_dir_override(session_id)
    if not exec_dir:
        home_base = settings.user_home_base
        exec_user = session.exec_user or session.username or settings.exec_user
        exec_dir = str(Path(home_base) / exec_user)

    # Resolve provider / alias
    provider = session.provider or "claude"
    alias = session.alias or provider

    # Build CLI continue command based on provider
    cli_session_id = storage.get_cli_session_id(session_id)

    cli_parts = [alias]
    if provider in ("claude", "codebuddy", "claude-internal"):
        if cli_session_id:
            cli_parts += ["--resume", cli_session_id]
        else:
            cli_parts.append("-c")
    elif provider == "gemini":
        cli_parts.append("--resume latest")
    elif provider == "codex":
        cli_parts += ["resume", "--last"]

    cli_cmd = " ".join(cli_parts)

    # Build tmux session name (short, unique per session)
    short_id = session_id[:12]
    tmux_name = f"nexus-{short_id}"

    # Full tmux command: create new session or attach to existing
    tmux_cmd = (
        f"tmux new-session -A -s {tmux_name} "
        f"-c {exec_dir} "
        f"'{cli_cmd}'"
    )

    return {
        "success": True,
        "tmux_command": tmux_cmd,
        "tmux_session_name": tmux_name,
        "cli_command": cli_cmd,
        "exec_dir": exec_dir,
        "provider": provider,
        "cli_session_id": cli_session_id,
    }

# -*- coding: utf-8 -*-
"""NexusHub-style Web API Router

Provides REST API endpoints for viewing and managing AGUI sessions.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

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
    
    # Delete session (idempotent)
    storage.delete_session(session_id, username)
    
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

# -*- coding: utf-8 -*-
"""Session data models for NexusHub-style Web Viewer

Defines data models for storing AGUI session data in Redis.
"""

import time
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .execution_binding import ExecutionBinding


class SessionStatus(str, Enum):
    """Session status enumeration"""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    ARCHIVED = "archived"


class SessionMeta(BaseModel):
    """Session metadata stored in Redis Hash"""
    id: str = Field(..., description="Session ID (same as thread_id)")
    thread_id: str = Field(..., description="AG-UI thread ID")
    run_id: Optional[str] = Field(None, description="AG-UI run ID")
    title: str = Field("New Session", description="Session title (first user message)")
    username: str = Field(..., description="Username")
    exec_user: Optional[str] = Field(None, description="Linux exec user for command execution")
    provider: Optional[str] = Field(None, description="Provider (e.g., claude, gemini)")
    alias: Optional[str] = Field(None, description="Alias (optional, defaults to provider)")
    prior_session_id: Optional[str] = Field(None, description="Explicit resume source session ID")
    prior_work_dir: Optional[str] = Field(None, description="Explicit prior working directory")
    cli_session_id: Optional[str] = Field(None, description="Underlying CLI session ID")
    claude_session_id: Optional[str] = Field(None, description="Legacy compat field for CLI session ID")
    archived_at: Optional[int] = Field(None, description="Archived timestamp (ms)")
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000), description="Created timestamp (ms)")
    updated_at: int = Field(default_factory=lambda: int(time.time() * 1000), description="Updated timestamp (ms)")
    message_count: int = Field(0, description="Total message count")
    status: SessionStatus = Field(SessionStatus.IDLE, description="Session status")
    source: Optional[str] = Field(None, description="Session source ('history' for parsed local files, None for runtime)")
    exec_dir: Optional[str] = Field(None, description="Working directory (cwd) for this session")
    task_id: Optional[str] = Field(None, description="Associated task ID (non-None for task sessions)")
    source_session_id: Optional[str] = Field(None, description="Upstream source session ID, if this session was resumed from another session")
    session_kind: Optional[str] = Field(None, description="Session kind: chat | task | history")
    execution_binding: Optional[ExecutionBinding] = Field(None, description="Control-plane binding metadata")

    def to_redis_hash(self) -> Dict[str, str]:
        """Convert to Redis hash mapping (all values as strings)"""
        effective_cli_session_id = self.cli_session_id or self.claude_session_id
        effective_prior_session_id = self.prior_session_id or ""
        effective_prior_work_dir = self.prior_work_dir or ""
        data = {
            "id": self.id,
            "thread_id": self.thread_id,
            "run_id": self.run_id or "",
            "title": self.title,
            "username": self.username,
            "exec_user": self.exec_user or "",
            "provider": self.provider or "",
            "alias": self.alias or "",
            "prior_session_id": effective_prior_session_id,
            "prior_work_dir": effective_prior_work_dir,
            "cli_session_id": effective_cli_session_id or "",
            "claude_session_id": effective_cli_session_id or "",
            "archived_at": str(self.archived_at or ""),
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
            "message_count": str(self.message_count),
            "status": self.status.value,
            "exec_dir": self.exec_dir or "",
        }
        if self.source is not None:
            data["source"] = self.source
        if self.task_id is not None:
            data["task_id"] = self.task_id
        if self.source_session_id is not None:
            data["source_session_id"] = self.source_session_id
        if self.session_kind is not None:
            data["session_kind"] = self.session_kind
        return data

    @classmethod
    def from_redis_hash(cls, data: Dict[str, str]) -> "SessionMeta":
        """Create from Redis hash mapping"""
        exec_user = data.get("exec_user") or None
        cli_session_id = data.get("cli_session_id") or data.get("claude_session_id") or None
        prior_session_id = data.get("prior_session_id") or data.get("source_session_id") or data.get("inherited_from") or None
        prior_work_dir = data.get("prior_work_dir") or data.get("exec_dir_override") or data.get("exec_dir") or None
        archived_at_raw = data.get("archived_at") or None
        try:
            archived_at = int(archived_at_raw) if archived_at_raw not in (None, "") else None
        except Exception:
            archived_at = None
        
        return cls(
            id=data.get("id", ""),
            thread_id=data.get("thread_id", ""),
            run_id=data.get("run_id") or None,
            title=data.get("title", "New Session"),
            username=data.get("username", ""),
            exec_user=exec_user,
            provider=data.get("provider") or None,
            alias=data.get("alias") or None,
            prior_session_id=prior_session_id,
            prior_work_dir=prior_work_dir,
            cli_session_id=cli_session_id,
            claude_session_id=data.get("claude_session_id") or cli_session_id,
            archived_at=archived_at,
            created_at=int(data.get("created_at", 0)),
            updated_at=int(data.get("updated_at", 0)),
            message_count=int(data.get("message_count", 0)),
            status=SessionStatus(data.get("status", "idle")),
            exec_dir=data.get("exec_dir") or data.get("exec_dir_override") or None,
            task_id=data.get("task_id") or None,
            source_session_id=data.get("source_session_id") or data.get("inherited_from") or None,
            session_kind=data.get("session_kind") or None,
            source=data.get("source") or None,
        )

    def to_execution_binding(self) -> ExecutionBinding:
        """Derive the control-plane execution binding for this session."""
        return ExecutionBinding(
            session_id=self.id,
            cli_session_id=self.cli_session_id,
            session_kind=self.session_kind or ("task" if self.task_id else ("history" if self.source == "history" else "chat")),
            provider=self.provider,
            alias=self.alias,
            exec_user=self.exec_user,
            work_dir=self.prior_work_dir or self.exec_dir,
            source_type=self.source or ("task" if self.task_id else None),
            source_session_id=self.prior_session_id or self.source_session_id,
            task_id=self.task_id,
            metadata={},
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class MessageStatus(str, Enum):
    """Message status enumeration"""
    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETE = "complete"
    ERROR = "error"


class ContentSegment(BaseModel):
    """Content segment for ordering text and tool calls"""
    type: Literal["text", "tool_call"] = Field(..., description="Segment type")
    content: Optional[str] = Field(None, description="Text content (for text type)")
    tool_call_id: Optional[str] = Field(None, description="Tool call ID (for tool_call type)")
    sequence: int = Field(0, description="Sequence number for ordering")


class StoredMessage(BaseModel):
    """Message stored in Redis List"""
    id: str = Field(..., description="Message ID")
    role: Literal["user", "assistant", "system", "tool"] = Field(..., description="Message role")
    content: str = Field("", description="Message content")
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000), description="Timestamp (ms)")
    status: MessageStatus = Field(MessageStatus.PENDING, description="Message status")
    tool_call_ids: Optional[List[str]] = Field(None, description="Associated tool call IDs")
    content_segments: Optional[List[ContentSegment]] = Field(None, description="Content segments for ordering text and tool calls")
    # DAG chain fields (Claude Code ch30)
    parent_uuid: Optional[str] = Field(None, description="Parent message UUID for DAG chain reconstruction")
    # Interrupted turn recovery
    is_interrupted: bool = Field(False, description="Whether this message was part of an interrupted turn")
    interrupted_reason: Optional[str] = Field(None, description="Reason for interruption (e.g. 'user_cancel', 'error', 'budget_exceeded')")

    def to_json(self) -> str:
        """Serialize to JSON string for Redis storage"""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "StoredMessage":
        """Deserialize from JSON string"""
        return cls.model_validate_json(json_str)


class ToolCallStatus(str, Enum):
    """Tool call status enumeration"""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class StoredToolCall(BaseModel):
    """Tool call stored in Redis Hash"""
    id: str = Field(..., description="Tool call ID")
    tool_name: str = Field(..., description="Tool name")
    args: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    args_string: str = Field("", description="Tool arguments as string")
    status: ToolCallStatus = Field(ToolCallStatus.PENDING, description="Tool call status")
    result: Optional[Any] = Field(None, description="Tool call result")
    error: Optional[str] = Field(None, description="Error message if failed")
    start_time: int = Field(default_factory=lambda: int(time.time() * 1000), description="Start timestamp (ms)")
    end_time: Optional[int] = Field(None, description="End timestamp (ms)")
    parent_message_id: Optional[str] = Field(None, description="Parent message ID")

    def to_json(self) -> str:
        """Serialize to JSON string for Redis storage"""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "StoredToolCall":
        """Deserialize from JSON string"""
        return cls.model_validate_json(json_str)


# API Response Models

class SessionListResponse(BaseModel):
    """Response model for session list API"""
    total: int = Field(..., description="Total session count")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Page size")
    sessions: List[SessionMeta] = Field(default_factory=list, description="Session list")


class SessionMessagesResponse(BaseModel):
    """Response model for session messages API"""
    session_id: str = Field(..., description="Session ID")
    messages: List[StoredMessage] = Field(default_factory=list, description="Message list")
    tool_calls: List[StoredToolCall] = Field(default_factory=list, description="Tool call list")
    session: Optional[SessionMeta] = Field(None, description="Session metadata")
    cli_session_id: Optional[str] = Field(None, description="Associated CLI session ID (if promoted from history)")
    # Recovery metadata
    interrupted_turns: List[Dict[str, Any]] = Field(default_factory=list, description="Interrupted turns that can be resumed")
    orphan_tool_results: List[str] = Field(default_factory=list, description="Tool result IDs without matching tool_calls")


class InterruptedTurn(BaseModel):
    """Represents an interrupted agent turn that can be resumed."""
    session_id: str = Field(..., description="Session ID")
    message_id: str = Field(..., description="Last message ID before interruption")
    parent_uuid: Optional[str] = Field(None, description="Parent UUID for DAG chain")
    reason: str = Field(..., description="Interruption reason")
    pending_tool_calls: List[str] = Field(default_factory=list, description="Tool call IDs that were pending")
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000), description="Timestamp of interruption (ms)")
    recoverable: bool = Field(True, description="Whether this turn can be auto-recovered")

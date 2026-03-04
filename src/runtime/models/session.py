# -*- coding: utf-8 -*-
"""Session data models for NexusHub-style Web Viewer

Defines data models for storing AGUI session data in Redis.
"""

import json
import time
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    """Session status enumeration"""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


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
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000), description="Created timestamp (ms)")
    updated_at: int = Field(default_factory=lambda: int(time.time() * 1000), description="Updated timestamp (ms)")
    message_count: int = Field(0, description="Total message count")
    status: SessionStatus = Field(SessionStatus.IDLE, description="Session status")
    source: Optional[str] = Field(None, description="Session source ('history' for parsed local files, None for runtime)")
    exec_dir: Optional[str] = Field(None, description="Working directory (cwd) for this session")
    task_id: Optional[str] = Field(None, description="Associated task ID (non-None for task sessions)")

    def to_redis_hash(self) -> Dict[str, str]:
        """Convert to Redis hash mapping (all values as strings)"""
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "run_id": self.run_id or "",
            "title": self.title,
            "username": self.username,
            "exec_user": self.exec_user or "",
            "provider": self.provider or "",
            "alias": self.alias or "",
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
            "message_count": str(self.message_count),
            "status": self.status.value,
            "exec_dir": self.exec_dir or "",
        }

    @classmethod
    def from_redis_hash(cls, data: Dict[str, str]) -> "SessionMeta":
        """Create from Redis hash mapping"""
        exec_user = data.get("exec_user") or None
        
        return cls(
            id=data.get("id", ""),
            thread_id=data.get("thread_id", ""),
            run_id=data.get("run_id") or None,
            title=data.get("title", "New Session"),
            username=data.get("username", ""),
            exec_user=exec_user,
            provider=data.get("provider") or None,
            alias=data.get("alias") or None,
            created_at=int(data.get("created_at", 0)),
            updated_at=int(data.get("updated_at", 0)),
            message_count=int(data.get("message_count", 0)),
            status=SessionStatus(data.get("status", "idle")),
            exec_dir=data.get("exec_dir") or data.get("exec_dir_override") or None,
            task_id=data.get("task_id") or None,
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
    role: Literal["user", "assistant", "system"] = Field(..., description="Message role")
    content: str = Field("", description="Message content")
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000), description="Timestamp (ms)")
    status: MessageStatus = Field(MessageStatus.PENDING, description="Message status")
    tool_call_ids: Optional[List[str]] = Field(None, description="Associated tool call IDs")
    content_segments: Optional[List[ContentSegment]] = Field(None, description="Content segments for ordering text and tool calls")

    def to_json(self) -> str:
        """Serialize to JSON string for Redis storage"""
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "StoredMessage":
        """Deserialize from JSON string"""
        data = json.loads(json_str)
        return cls(**data)


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
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "StoredToolCall":
        """Deserialize from JSON string"""
        data = json.loads(json_str)
        return cls(**data)


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

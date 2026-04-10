# -*- coding: utf-8 -*-
"""Task data models for slash commands

Provides Task, TaskStatus, TaskPriority models for task management.
Uses Pydantic models for Redis serialization.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List
import json
import uuid

from pydantic import BaseModel, Field, ConfigDict


def _utcnow() -> datetime:
    """Return current UTC time"""
    return datetime.now(timezone.utc)


def _generate_task_id() -> str:
    """Generate a unique task ID"""
    return str(uuid.uuid4())[:8]


class TaskPriority(str, Enum):
    """Task priority levels"""
    THOUGHT = "thought"      # Low priority, experimental
    SERIOUS = "serious"      # High priority, needs completion
    PROJECT = "project"      # Top priority, maps to Project
    GENERATED = "generated"  # Auto-generated backlog filler


class TaskStatus(str, Enum):
    """Task status states.

    Canonical workflow:
    inbox -> assigned -> awaiting_owner -> in_progress -> review -> quality_review -> done

    Additional terminal / utility states:
    failed, cancelled, archived
    """
    INBOX = "inbox"
    ASSIGNED = "assigned"
    AWAITING_OWNER = "awaiting_owner"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    QUALITY_REVIEW = "quality_review"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"

    # Backward-compatible aliases
    TODO = "inbox"
    DOING = "in_progress"

    @classmethod
    def from_legacy(cls, value: str) -> "TaskStatus":
        """Convert legacy status values to canonical workflow statuses."""
        normalized = (value or "").strip().lower()
        legacy_map = {
            "pending": cls.INBOX,
            "todo": cls.INBOX,
            "inbox": cls.INBOX,
            "assigned": cls.ASSIGNED,
            "awaiting_owner": cls.AWAITING_OWNER,
            "in_progress": cls.IN_PROGRESS,
            "doing": cls.IN_PROGRESS,
            "running": cls.IN_PROGRESS,
            "review": cls.REVIEW,
            "quality_review": cls.QUALITY_REVIEW,
            "completed": cls.DONE,
            "done": cls.DONE,
            "failed": cls.FAILED,
            "cancelled": cls.CANCELLED,
            "archived": cls.ARCHIVED,
        }
        if normalized in legacy_map:
            return legacy_map[normalized]
        raise ValueError(f"Unknown status: {value}")

    @classmethod
    def can_transition(cls, current: "TaskStatus", new: "TaskStatus") -> bool:
        """Return True when a transition between statuses is allowed."""
        if current == new:
            return True
        allowed = {
            cls.INBOX: {cls.ASSIGNED, cls.IN_PROGRESS, cls.CANCELLED, cls.ARCHIVED},
            cls.ASSIGNED: {cls.AWAITING_OWNER, cls.IN_PROGRESS, cls.CANCELLED, cls.ARCHIVED},
            cls.AWAITING_OWNER: {cls.ASSIGNED, cls.IN_PROGRESS, cls.CANCELLED, cls.ARCHIVED},
            cls.IN_PROGRESS: {cls.REVIEW, cls.AWAITING_OWNER, cls.FAILED, cls.CANCELLED},
            cls.REVIEW: {cls.QUALITY_REVIEW, cls.IN_PROGRESS, cls.FAILED, cls.CANCELLED},
            cls.QUALITY_REVIEW: {cls.DONE, cls.REVIEW, cls.IN_PROGRESS, cls.FAILED, cls.CANCELLED},
            cls.DONE: {cls.ARCHIVED},
            cls.FAILED: {cls.INBOX, cls.ASSIGNED, cls.ARCHIVED},
            cls.CANCELLED: {cls.INBOX, cls.ARCHIVED},
            cls.ARCHIVED: {cls.INBOX, cls.DONE},
        }
        return new in allowed.get(current, set())


class RuntimeTaskStatus(str, Enum):
    """Ephemeral runtime state for executor orchestration.

    This layer is intentionally separate from collaboration ``TaskStatus`` to
    support dual-layer state management.
    """
    QUEUED = "queued"
    RUNNING = "running"
    IDLE = "idle"
    ORPHANED = "orphaned"
    FAILED = "failed"


class Task(BaseModel):
    """Task model for Redis storage
    
    Uses Pydantic for serialization/deserialization with Redis.
    """
    id: str = Field(default_factory=_generate_task_id)
    description: str
    priority: TaskPriority = TaskPriority.THOUGHT
    status: TaskStatus = TaskStatus.INBOX

    # Collaboration / board metadata
    assigned_to: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    due_date: Optional[datetime] = None
    ticket_ref: Optional[str] = None

    # Timing
    created_at: datetime = Field(default_factory=_utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    
    # Execution details
    attempt_count: int = 0
    error_message: Optional[str] = None

    # Runtime-layer execution status (separate from collaboration status)
    runtime_status: RuntimeTaskStatus = RuntimeTaskStatus.QUEUED
    runtime_orphaned: bool = False
    runtime_orphaned_at: Optional[datetime] = None
    runtime_last_heartbeat: Optional[datetime] = None

    # Outcome tracking — ported from mission-control commit 6cf4256
    # outcome: final result category set when task transitions to DONE/FAILED
    outcome: Optional[str] = None          # "success" | "failed" | "partial" | "abandoned"
    resolution: Optional[str] = None      # free-text resolution notes
    feedback_rating: Optional[int] = None  # 1-5 human rating
    feedback_notes: Optional[str] = None   # human feedback text
    
    # Metadata
    context: Optional[Dict[str, Any]] = None
    
    # Project grouping
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    
    # Working directory for task execution
    workspace: Optional[str] = None
    
    # Exec user isolation (Linux user for su command)
    exec_user: Optional[str] = None

    # Provider pinned at task creation time (e.g., claude, gemini)
    provider: str = "claude"
    # Optional alias (defaults to provider)
    alias: Optional[str] = None
    # Optional LLM model name (e.g., claude-opus-4.6, gemini-2.5-pro)
    model: Optional[str] = None
    
    # Session ID for conversation storage (format: {session_id}_{task_id})
    session_id: Optional[str] = None

    # Source session ID (where the task was created from)
    source_session_id: Optional[str] = None

    # Task dependencies - list of task IDs that must complete before this task runs
    depends_on: List[str] = Field(default_factory=list)

    # CLI session UUID for context resumption (provider-agnostic).
    # Used with: claude --resume ID, gemini --resume ID, codex resume ID
    cli_session_id: Optional[str] = None

    # Legacy alias kept for backward-compat Redis data (mapped in from_redis_hash)
    claude_session_id: Optional[str] = None

    # Schedule reference - set when task was created by a schedule
    schedule_id: Optional[str] = None

    # Callback notification configuration for async task completion
    response_url: Optional[str] = None          # Callback URL for task completion notification
    callback_msg_id: Optional[str] = None       # Message ID to pass back in callback
    callback_user: Optional[str] = None         # User identifier for callback

    # Unified notification target (replaces response_url for channel-based notifications)
    # Serialised as JSON dict when stored in Redis
    notification_sink_type: Optional[str] = None    # e.g. "response_url", "telegram", "slack"
    notification_channel: Optional[str] = None      # channel name
    notification_chat_id: Optional[str] = None      # chat/channel ID
    notification_message_id: Optional[str] = None   # for editing existing progress message

    # Ralph Loop configuration
    loop_enabled: bool = False                                      # Whether Ralph Loop is active
    loop_max_iterations: int = 1                                    # Max number of loop iterations
    loop_iteration: int = 0                                         # Current iteration count
    loop_keywords: List[str] = Field(default_factory=list)          # Keywords to match in output
    loop_keyword_found: bool = False                                # Whether keyword was found

    model_config = ConfigDict(use_enum_values=True)
    
    def to_redis_hash(self) -> Dict[str, str]:
        """Convert task to Redis hash format"""
        data = self.model_dump()
        result = {}
        for key, value in data.items():
            if value is None:
                continue
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, dict):
                result[key] = json.dumps(value)
            elif isinstance(value, list):
                result[key] = json.dumps(value)
            elif isinstance(value, Enum):
                result[key] = value.value
            else:
                result[key] = str(value)
        return result
    
    @classmethod
    def from_redis_hash(cls, data: Dict[str, str]) -> "Task":
        """Create task from Redis hash data"""
        if not data:
            raise ValueError("Empty data")
        
        parsed = {}
        for key, value in data.items():
            if key in ("created_at", "started_at", "completed_at", "archived_at", "deleted_at", "due_date", "runtime_orphaned_at", "runtime_last_heartbeat"):
                parsed[key] = datetime.fromisoformat(value) if value else None
            elif key == "context":
                parsed[key] = json.loads(value) if value else None
            elif key in ("depends_on", "tags"):
                parsed[key] = json.loads(value) if value else []
            elif key in ("attempt_count", "feedback_rating"):
                try:
                    parsed[key] = int(value) if value not in ("", "None", "null") else None
                except (ValueError, TypeError):
                    parsed[key] = None
            elif key in ("loop_iteration", "loop_max_iterations"):
                parsed[key] = int(value)
            elif key in ("loop_enabled", "loop_keyword_found", "runtime_orphaned"):
                parsed[key] = value.lower() in ("true", "1", "yes")
            elif key == "loop_keywords":
                parsed[key] = json.loads(value) if value else []
            elif key == "priority":
                parsed[key] = TaskPriority(value)
            elif key == "status":
                parsed[key] = TaskStatus.from_legacy(value)
            elif key == "runtime_status":
                try:
                    parsed[key] = RuntimeTaskStatus(value)
                except ValueError:
                    parsed[key] = RuntimeTaskStatus.QUEUED
            else:
                parsed[key] = value

        # Migrate legacy claude_session_id → cli_session_id
        if "claude_session_id" in parsed and not parsed.get("cli_session_id"):
            parsed["cli_session_id"] = parsed["claude_session_id"]
        
        return cls(**parsed)
    
    def __repr__(self):
        return f"<Task(id={self.id}, priority={self.priority}, status={self.status})>"

    def get_notification_target(self):
        """Build a NotificationTarget from task fields, or None if not configured.

        Returns a NotificationTarget (from the notification module) if either:
        - notification_sink_type is set (unified notification)
        - response_url is set (legacy HTTP webhook)
        """
        from src.server.services.notification.models import NotificationTarget

        if self.notification_sink_type:
            return NotificationTarget(
                sink_type=self.notification_sink_type,
                response_url=self.response_url or "",
                channel_name=self.notification_channel or "",
                chat_id=self.notification_chat_id or "",
                message_id=self.notification_message_id or "",
                request_data={
                    "msg_id": self.callback_msg_id,
                    "user": self.callback_user,
                    "session_id": self.source_session_id or self.session_id,
                },
            )
        elif self.response_url:
            # Legacy: create HTTP webhook target for backward compat
            return NotificationTarget(
                sink_type="response_url",
                response_url=self.response_url,
                request_data={
                    "msg_id": self.callback_msg_id,
                    "user": self.callback_user,
                    "session_id": self.source_session_id or self.session_id,
                },
            )
        return None


class ExecutorConfig(BaseModel):
    """Configuration for task executor"""
    provider_concurrency: Dict[str, int] = Field(default_factory=dict)
    global_max_concurrency: int = Field(default=3, ge=0)  # 0 = unlimited
    poll_interval: float = Field(default=1.0, ge=0.1)  # seconds
    max_retries: int = Field(default=3, ge=0)
    retry_delay: float = Field(default=5.0, ge=0)  # seconds
    task_timeout: float = Field(default=3600.0, ge=0)  # seconds, 0 = no timeout

    def get_provider_max_concurrency(self, provider_key: Optional[str]) -> int:
        """Get max concurrency for a provider/alias. Returns 0 if unlimited."""
        if provider_key and provider_key in self.provider_concurrency:
            return self.provider_concurrency[provider_key]
        return 0  # no limit

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

from pydantic import BaseModel, Field, ConfigDict, model_validator

from .execution_binding import ExecutionBinding
from .notification_models import TaskNotificationConfig


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
    """Task status states — aligned with netharness 7-status model.

    Workflow:
    pending → running → in_review → completed
              ↘ cancelled        ↘ failed
                                  ↘ archived

    Also supported:
    - review_state: none / requested / approved (netharness pattern)
    - display_status: computed from status + review_state + archived_at
    """
    PENDING = "pending"
    RUNNING = "running"
    IN_REVIEW = "in_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"

    # Backward-compatible aliases (same values as new canonical statuses)
    TODO = "pending"
    DOING = "running"
    DONE = "completed"

    @classmethod
    def from_legacy(cls, value: str) -> "TaskStatus":
        """Convert legacy status values to canonical netharness-aligned statuses."""
        normalized = (value or "").strip().lower()
        legacy_map = {
            # New canonical values pass through
            "pending": cls.PENDING,
            "running": cls.RUNNING,
            "in_review": cls.IN_REVIEW,
            "completed": cls.COMPLETED,
            "failed": cls.FAILED,
            "cancelled": cls.CANCELLED,
            "archived": cls.ARCHIVED,
            # Old 10-status model mappings
            "inbox": cls.PENDING,
            "assigned": cls.PENDING,
            "awaiting_owner": cls.PENDING,
            "in_progress": cls.RUNNING,
            "review": cls.IN_REVIEW,
            "quality_review": cls.IN_REVIEW,
            "done": cls.COMPLETED,
            # Legacy aliases
            "todo": cls.PENDING,
            "doing": cls.RUNNING,
            # Runtime-only status
            "orphaned": cls.PENDING,
        }
        if normalized in legacy_map:
            return legacy_map[normalized]
        raise ValueError(f"Unknown status: {value}")

    @classmethod
    def can_transition(cls, current: "TaskStatus", new: "TaskStatus") -> bool:
        """Return True when a transition between statuses is allowed.

        Aligned with netharness VALID_TRANSITIONS:
        pending → {running, cancelled}
        running → {pending, in_review, completed, failed, cancelled}
        in_review → {running, completed, failed, cancelled}
        completed → {archived}
        failed → {pending, archived}
        cancelled → {pending, archived}
        archived → {pending, completed}
        """
        if current == new:
            return True
        allowed = {
            cls.PENDING: {cls.RUNNING, cls.CANCELLED, cls.ARCHIVED},
            cls.RUNNING: {cls.PENDING, cls.IN_REVIEW, cls.COMPLETED, cls.FAILED, cls.CANCELLED},
            cls.IN_REVIEW: {cls.RUNNING, cls.COMPLETED, cls.FAILED, cls.CANCELLED},
            cls.COMPLETED: {cls.ARCHIVED},
            cls.FAILED: {cls.PENDING, cls.ARCHIVED},
            cls.CANCELLED: {cls.PENDING, cls.ARCHIVED},
            cls.ARCHIVED: {cls.PENDING, cls.COMPLETED},
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
    status: TaskStatus = TaskStatus.PENDING

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
    provider: str = "claude"  # default from providers.registry.DEFAULT_PROVIDER
    # Optional alias (defaults to provider)
    alias: Optional[str] = None
    # Optional LLM model name (e.g., claude-opus-4.6, gemini-2.5-pro)
    model: Optional[str] = None
    
    # Session ID for conversation storage (format: {session_id}_{task_id})
    session_id: Optional[str] = None

    # Source session ID (where the task was created from)
    source_session_id: Optional[str] = None
    # Explicit resume / handoff contract for control-plane parity
    prior_session_id: Optional[str] = None
    prior_work_dir: Optional[str] = None
    repo_url: Optional[str] = None
    repo_root: Optional[str] = None
    worktree_path: Optional[str] = None

    # Task dependencies - list of task IDs that must complete before this task runs
    depends_on: List[str] = Field(default_factory=list)

    # CLI session UUID for context resumption (provider-agnostic).
    # Used with: claude/gemini --resume ID, codebuddy -r ID, codex resume ID
    cli_session_id: Optional[str] = None

    # Control-plane execution binding metadata
    session_kind: Optional[str] = None
    execution_binding: Optional[ExecutionBinding] = None

    # Legacy alias kept for backward-compat Redis data (mapped in from_redis_hash)
    claude_session_id: Optional[str] = None

    # Schedule reference - set when task was created by a schedule
    schedule_id: Optional[str] = None

    # Application-layer notification transport metadata.
    # Legacy top-level response_url / notification_* accessors are kept below.
    notification: Optional[TaskNotificationConfig] = None

    # Ralph Loop configuration
    loop_enabled: bool = False                                      # Whether Ralph Loop is active
    loop_max_iterations: int = 1                                    # Max number of loop iterations
    loop_iteration: int = 0                                         # Current iteration count
    loop_keywords: List[str] = Field(default_factory=list)          # Keywords to match in output
    loop_keyword_found: bool = False                                # Whether keyword was found

    model_config = ConfigDict(use_enum_values=True, extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _coalesce_notification_fields(cls, data: Any) -> Any:
        """Pack legacy transport fields into the nested notification model."""
        if not isinstance(data, dict):
            return data

        payload = dict(data)
        existing_notification = payload.get("notification")
        if isinstance(existing_notification, TaskNotificationConfig):
            notification_data = existing_notification.model_dump(exclude_none=True)
        elif isinstance(existing_notification, dict):
            notification_data = dict(existing_notification)
        else:
            notification_data = {}

        field_map = {
            "response_url": "response_url",
            "callback_msg_id": "callback_msg_id",
            "callback_user": "callback_user",
            "notification_sink_type": "sink_type",
            "notification_channel": "channel_name",
            "notification_chat_id": "chat_id",
            "notification_message_id": "message_id",
        }
        for legacy_field, nested_field in field_map.items():
            if legacy_field not in payload:
                continue
            value = payload.pop(legacy_field)
            if value in (None, "", [], {}):
                continue
            notification_data[nested_field] = value

        if notification_data:
            payload["notification"] = notification_data
        return payload

    def _ensure_notification(self) -> TaskNotificationConfig:
        notification = self.notification
        if notification is None:
            notification = TaskNotificationConfig()
            object.__setattr__(self, "notification", notification)
        return notification

    @property
    def response_url(self) -> Optional[str]:
        return self.notification.response_url if self.notification else None

    @response_url.setter
    def response_url(self, value: Optional[str]) -> None:
        self._ensure_notification().response_url = value or None

    @property
    def callback_msg_id(self) -> Optional[str]:
        return self.notification.callback_msg_id if self.notification else None

    @callback_msg_id.setter
    def callback_msg_id(self, value: Optional[str]) -> None:
        self._ensure_notification().callback_msg_id = value or None

    @property
    def callback_user(self) -> Optional[str]:
        return self.notification.callback_user if self.notification else None

    @callback_user.setter
    def callback_user(self, value: Optional[str]) -> None:
        self._ensure_notification().callback_user = value or None

    @property
    def notification_sink_type(self) -> Optional[str]:
        return self.notification.sink_type if self.notification else None

    @notification_sink_type.setter
    def notification_sink_type(self, value: Optional[str]) -> None:
        self._ensure_notification().sink_type = value or None

    @property
    def notification_channel(self) -> Optional[str]:
        return self.notification.channel_name if self.notification else None

    @notification_channel.setter
    def notification_channel(self, value: Optional[str]) -> None:
        self._ensure_notification().channel_name = value or None

    @property
    def notification_chat_id(self) -> Optional[str]:
        return self.notification.chat_id if self.notification else None

    @notification_chat_id.setter
    def notification_chat_id(self, value: Optional[str]) -> None:
        self._ensure_notification().chat_id = value or None

    @property
    def notification_message_id(self) -> Optional[str]:
        return self.notification.message_id if self.notification else None

    @notification_message_id.setter
    def notification_message_id(self, value: Optional[str]) -> None:
        self._ensure_notification().message_id = value or None
    
    def to_redis_hash(self) -> Dict[str, str]:
        """Convert task to Redis hash format"""
        data = self.model_dump()
        notification = data.pop("notification", None) or {}
        if notification:
            notification_field_map = {
                "response_url": "response_url",
                "callback_msg_id": "callback_msg_id",
                "callback_user": "callback_user",
                "sink_type": "notification_sink_type",
                "channel_name": "notification_channel",
                "chat_id": "notification_chat_id",
                "message_id": "notification_message_id",
            }
            for nested_field, legacy_field in notification_field_map.items():
                value = notification.get(nested_field)
                if value not in (None, "", [], {}):
                    data[legacy_field] = value
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
            elif key == "execution_binding":
                try:
                    parsed[key] = ExecutionBinding.model_validate_json(value) if value else None
                except Exception:
                    parsed[key] = None
            elif key == "priority":
                parsed[key] = TaskPriority(value)
            elif key == "status":
                parsed[key] = TaskStatus.from_legacy(value)
            elif key == "runtime_status":
                try:
                    parsed[key] = RuntimeTaskStatus(value)
                except ValueError:
                    parsed[key] = RuntimeTaskStatus.QUEUED
            elif key == "session_kind":
                parsed[key] = value or None
            elif key in ("prior_session_id", "prior_work_dir", "repo_url", "repo_root", "worktree_path"):
                parsed[key] = value or None
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

        Returns a NotificationTarget (from the shared runtime model) if either:
        - notification_sink_type is set (unified notification)
        - response_url is set (legacy HTTP webhook)
        """
        if not self.notification:
            return None
        return self.notification.to_target(
            session_id=self.session_id,
            source_session_id=self.source_session_id,
        )

    def to_execution_binding(self) -> ExecutionBinding:
        """Derive a control-plane binding from the task run."""
        return ExecutionBinding(
            session_id=self.session_id or self.id,
            cli_session_id=self.cli_session_id,
            session_kind=self.session_kind or "task",
            provider=self.provider,
            alias=self.alias,
            exec_user=self.exec_user,
            work_dir=self.worktree_path or self.prior_work_dir or self.workspace,
            source_type="task",
            source_session_id=self.prior_session_id or self.source_session_id,
            task_id=self.id,
            metadata={
                "priority": self.priority if isinstance(self.priority, str) else self.priority.value,
                **({k: v for k, v in {
                    "repo_url": self.repo_url,
                    "repo_root": self.repo_root,
                    "worktree_path": self.worktree_path,
                }.items() if v}),
            },
            created_at=int(self.created_at.timestamp() * 1000),
            updated_at=int((self.completed_at or self.started_at or self.created_at).timestamp() * 1000),
            expires_at=None,
        )


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

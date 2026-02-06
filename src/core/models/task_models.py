# -*- coding: utf-8 -*-
"""Task data models for slash commands

Provides Task, TaskStatus, TaskPriority models for task management.
Uses Pydantic models for Redis serialization.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any
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
    PROJECT = "project"      # High priority, project-related
    GENERATED = "generated"  # Auto-generated backlog filler


class TaskStatus(str, Enum):
    """Task status states
    
    Status names updated for clarity:
    - TODO: Task is waiting to be processed
    - DOING: Task is currently being executed
    - DONE: Task completed successfully
    - FAILED: Task execution failed
    - CANCELLED: Task was cancelled (soft delete)
    - ARCHIVED: Task was archived (hidden from main board, shown in Archived column)
    """
    TODO = "todo"           # Renamed from PENDING
    DOING = "doing"         # Renamed from IN_PROGRESS
    DONE = "done"           # Renamed from COMPLETED
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"
    
    # Aliases for backward compatibility
    @classmethod
    def from_legacy(cls, value: str) -> "TaskStatus":
        """Convert legacy status values to new format"""
        legacy_map = {
            "pending": cls.TODO,
            "in_progress": cls.DOING,
            "completed": cls.DONE,
            "failed": cls.FAILED,
            "cancelled": cls.CANCELLED,
        }
        if value in legacy_map:
            return legacy_map[value]
        # Try to find by value
        for status in cls:
            if status.value == value:
                return status
        raise ValueError(f"Unknown status: {value}")


class Task(BaseModel):
    """Task model for Redis storage
    
    Uses Pydantic for serialization/deserialization with Redis.
    """
    id: str = Field(default_factory=_generate_task_id)
    description: str
    priority: TaskPriority = TaskPriority.THOUGHT
    status: TaskStatus = TaskStatus.TODO
    
    # Timing
    created_at: datetime = Field(default_factory=_utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    
    # Execution details
    attempt_count: int = 0
    error_message: Optional[str] = None
    
    # Metadata
    context: Optional[Dict[str, Any]] = None
    
    # Project grouping
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    
    # Working directory for task execution
    workspace: Optional[str] = None
    
    # Agent isolation
    agent_name: Optional[str] = None

    # Provider pinned at task creation time (e.g., claude, gemini)
    provider: str = "claude"
    # Optional alias (defaults to provider)
    alias: Optional[str] = None
    
    # Session ID for conversation storage (format: {session_id}_{task_id})
    session_id: Optional[str] = None
    
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
            if key in ("created_at", "started_at", "completed_at", "archived_at", "deleted_at"):
                parsed[key] = datetime.fromisoformat(value) if value else None
            elif key == "context":
                parsed[key] = json.loads(value) if value else None
            elif key == "attempt_count":
                parsed[key] = int(value)
            elif key == "priority":
                parsed[key] = TaskPriority(value)
            elif key == "status":
                # Handle legacy status values
                try:
                    parsed[key] = TaskStatus(value)
                except ValueError:
                    parsed[key] = TaskStatus.from_legacy(value)
            else:
                parsed[key] = value
        
        return cls(**parsed)
    
    def __repr__(self):
        return f"<Task(id={self.id}, priority={self.priority}, status={self.status})>"


class ExecutorConfig(BaseModel):
    """Configuration for task executor"""
    default_max_concurrency: int = Field(default=1, ge=1)
    workspace_concurrency: Dict[str, int] = Field(default_factory=dict)
    poll_interval: float = Field(default=1.0, ge=0.1)  # seconds
    max_retries: int = Field(default=3, ge=0)
    retry_delay: float = Field(default=5.0, ge=0)  # seconds
    task_timeout: float = Field(default=3600.0, ge=0)  # seconds, 0 = no timeout
    
    def get_max_concurrency(self, workspace: Optional[str]) -> int:
        """Get max concurrency for a specific workspace"""
        if workspace and workspace in self.workspace_concurrency:
            return self.workspace_concurrency[workspace]
        return self.default_max_concurrency

"""Data models for the mission system."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

TaskStatus = Literal["pending", "running", "completed", "failed", "skipped", "cancelled"]
MilestoneStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
MissionStatus = Literal["planned", "planning", "running", "paused", "completed", "failed", "cancelled"]
AgentRole = Literal["planner", "coder", "reviewer", "tester"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration string."""
    if seconds <= 0:
        return "0s"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m{secs:.0f}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h{mins}m{secs:.0f}s"


@dataclass
class TokenUsage:
    """Token usage statistics for a single task or aggregated."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_iterations: int = 0  # Number of LLM call rounds

    def add(self, usage: dict[str, int] | None) -> None:
        """Add usage from a single LLM response."""
        if not usage:
            return
        self.prompt_tokens += usage.get("prompt_tokens", 0)
        self.completion_tokens += usage.get("completion_tokens", 0)
        self.total_tokens += usage.get("total_tokens", 0)

    def merge(self, other: TokenUsage) -> None:
        """Merge another TokenUsage into this one."""
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        self.llm_iterations += other.llm_iterations

    @property
    def estimated_cost_usd(self) -> float:
        """Rough cost estimate (GLM-4.5-air: ~$0.5/1M input, ~$1.5/1M output)."""
        return (self.prompt_tokens * 0.5 + self.completion_tokens * 1.5) / 1_000_000


@dataclass
class TaskResult:
    """Result of a single task execution."""

    status: TaskStatus = "pending"
    output: str = ""
    error: str | None = None
    started_at_ms: int = 0
    completed_at_ms: int = 0
    retry_count: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)

    @property
    def duration_seconds(self) -> float:
        """Wall-clock duration in seconds."""
        if self.started_at_ms and self.completed_at_ms:
            return (self.completed_at_ms - self.started_at_ms) / 1000.0
        return 0.0


@dataclass
class Task:
    """A single executable unit within a milestone."""

    id: str  # e.g. "t-001"
    title: str
    description: str
    role: AgentRole = "coder"
    status: TaskStatus = "pending"
    depends_on: list[str] = field(default_factory=list)
    result: TaskResult | None = None
    max_retries: int = 2
    max_iterations: int = 25  # LLM iterations per task
    model: str = ""  # Per-task model override; empty = use mission default


@dataclass
class Milestone:
    """A group of related tasks forming a logical phase."""

    id: str  # e.g. "m-001"
    title: str
    description: str
    tasks: list[Task] = field(default_factory=list)
    status: MilestoneStatus = "pending"
    validation_criteria: str = ""
    validation_commands: list[str] = field(default_factory=list)
    validation_timeout: int = 120  # seconds per validation command
    depends_on: list[str] = field(default_factory=list)  # milestone IDs for parallel execution


@dataclass
class MissionOrigin:
    """Where the mission was created from."""

    channel: str = "cli"
    chat_id: str = "direct"


@dataclass
class MissionConfig:
    """Configuration for mission execution."""

    max_parallel_tasks: int = 3
    auto_review: bool = True
    auto_test: bool = True
    task_timeout_seconds: int = 600  # 10 min per task
    mission_timeout_seconds: int = 7200  # 2 hours total
    max_total_iterations: int = 200  # LLM iteration budget across all tasks
    context_window_tokens: int = 100_000  # Context window size (~128K for GLM-4.5-air)
    prior_result_max_chars: int = 2000  # Max chars for prior task results (was hardcoded 500)
    role_model_map: dict[str, str] = field(default_factory=dict)  # role -> model override


@dataclass
class Mission:
    """A long-running autonomous task with milestones and tasks."""

    id: str  # e.g. "msn-abc123"
    goal: str
    mission_type: str = "general"
    status: MissionStatus = "planning"
    milestones: list[Milestone] = field(default_factory=list)
    origin: MissionOrigin = field(default_factory=MissionOrigin)
    config: MissionConfig = field(default_factory=MissionConfig)
    created_at_ms: int = 0
    updated_at_ms: int = 0
    completed_at_ms: int = 0
    error: str | None = None
    log: list[str] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)  # aggregate across all tasks

    def add_log(self, entry: str) -> None:
        """Add a timestamped log entry."""
        import datetime

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {entry}")

    @property
    def total_tasks(self) -> int:
        return sum(len(m.tasks) for m in self.milestones)

    @property
    def completed_tasks(self) -> int:
        return sum(
            1 for m in self.milestones for t in m.tasks if t.status == "completed"
        )

    @property
    def progress_pct(self) -> float:
        total = self.total_tasks
        return (self.completed_tasks / total * 100) if total > 0 else 0.0

    @property
    def current_milestone(self) -> Milestone | None:
        for m in self.milestones:
            if m.status in ("pending", "running"):
                return m
        return None

    @property
    def wall_clock_seconds(self) -> float:
        """Wall-clock duration from creation to now or completion."""
        if not self.created_at_ms:
            return 0.0
        end = self.completed_at_ms or _now_ms()
        return (end - self.created_at_ms) / 1000.0

    @property
    def wall_clock_display(self) -> str:
        """Human-readable wall-clock duration."""
        return _format_duration(self.wall_clock_seconds)


@dataclass
class MissionStore:
    """In-memory store for missions."""

    version: int = 1
    missions: list[Mission] = field(default_factory=list)

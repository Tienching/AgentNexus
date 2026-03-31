"""Data models for the self-evolution system."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

EvolutionPhase = Literal["assessment", "planning", "implementation", "reflection"]
SessionStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
LearningSource = Literal["evolution", "github-issues", "testing", "self-review", "community"]


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Lesson:
    """A single learning from an evolution session."""

    type: str = "lesson"
    day: int = 0
    timestamp: str = ""
    source: LearningSource = "evolution"
    title: str = ""
    context: str = ""
    takeaway: str = ""


@dataclass
class SocialInsight:
    """A learning from community/social interaction."""

    type: str = "social"
    day: int = 0
    timestamp: str = ""
    source: str = ""
    who: str = ""
    insight: str = ""


@dataclass
class EvolutionTask:
    """A task planned by the evolution planner."""

    id: str = ""
    title: str = ""
    files: list[str] = field(default_factory=list)
    issue: str = "none"
    description: str = ""
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    output: str = ""
    error: str | None = None


@dataclass
class AssessmentReport:
    """Structured assessment from Phase A1."""

    build_status: str = ""
    recent_changes: str = ""
    source_architecture: str = ""
    self_test_results: str = ""
    capability_gaps: str = ""
    bugs_found: str = ""
    open_issues: str = ""
    research_findings: str = ""
    raw_text: str = ""
    generated_at_ms: int = 0


@dataclass
class SessionMetrics:
    """Metrics collected during an evolution session."""

    codebase_loc: int = 0
    test_count: int = 0
    test_pass_count: int = 0
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    tasks_planned: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    duration_seconds: float = 0.0


@dataclass
class EvolutionSession:
    """A complete evolution session spanning all phases."""

    id: str = ""
    day: int = 0
    date: str = ""
    phase: EvolutionPhase = "assessment"
    status: SessionStatus = "pending"
    assessment: AssessmentReport | None = None
    tasks: list[EvolutionTask] = field(default_factory=list)
    metrics: SessionMetrics = field(default_factory=SessionMetrics)
    lessons_learned: list[Lesson] = field(default_factory=list)
    started_at_ms: int = 0
    completed_at_ms: int = 0
    error: str | None = None
    log: list[str] = field(default_factory=list)

    def add_log(self, entry: str) -> None:
        """Add a timestamped log entry."""
        import datetime

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {entry}")

    @property
    def duration_seconds(self) -> float:
        if self.started_at_ms and self.completed_at_ms:
            return (self.completed_at_ms - self.started_at_ms) / 1000.0
        return 0.0


@dataclass
class EvolutionConfig:
    """Configuration for the evolution system."""

    enabled: bool = False
    interval_hours: int = 1
    cron_expr: str = "0 * * * *"
    memory_path: str = "./memory"
    journal_path: str = "./JOURNAL.md"
    identity_file: str = "./IDENTITY.md"
    personality_file: str = "./PERSONALITY.md"
    max_session_duration_seconds: int = 3600
    max_tasks_per_session: int = 3
    max_fix_attempts: int = 10
    protected_files: list[str] = field(default_factory=lambda: [
        "IDENTITY.md",
        "PERSONALITY.md",
    ])
    codebuddy_path: str = "codebuddy"
    codebuddy_model: str = ""
    codebuddy_timeout: int = 600
    working_dir: str = "."
    # Worktree parallel execution
    use_worktree: bool = True
    worktree_base_dir: str = ".evolve"
    parallel_tasks: bool = True

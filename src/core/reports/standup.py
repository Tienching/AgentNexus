# -*- coding: utf-8 -*-
"""Standup report generation.

Generates daily standup reports with per-agent stats,
team achievements, and blockers.

Usage:
    from src.core.reports.standup import StandupReportGenerator

    generator = StandupReportGenerator()
    report = generator.generate_report()
    print(report.markdown())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.runtime.models.task_models import TaskStatus
from src.runtime.stores.db import get_db


@dataclass
class AgentStats:
    """Statistics for a single agent."""
    agent_id: str
    tasks_completed: int = 0
    tasks_in_progress: int = 0
    tasks_blocked: int = 0
    tasks_created: int = 0
    avg_completion_time_hours: float = 0.0


@dataclass
class StandupReport:
    """Daily standup report."""
    date: str
    total_tasks_completed: int = 0
    total_tasks_in_progress: int = 0
    total_tasks_blocked: int = 0
    total_new_tasks: int = 0
    agent_stats: Dict[str, AgentStats] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)
    achievements: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def markdown(self) -> str:
        """Format report as markdown."""
        lines = [
            f"# Standup Report - {self.date}",
            "",
            "## Summary",
            f"- Tasks Completed: {self.total_tasks_completed}",
            f"- Tasks In Progress: {self.total_tasks_in_progress}",
            f"- Tasks Blocked: {self.total_tasks_blocked}",
            f"- New Tasks: {self.total_new_tasks}",
            "",
        ]

        if self.agent_stats:
            lines.append("## Agent Stats")
            lines.append("")
            lines.append("| Agent | Completed | In Progress | Blocked |")
            lines.append("|-------|-----------|-------------|---------|")
            for agent_id, stats in sorted(self.agent_stats.items()):
                lines.append(
                    f"| {agent_id} | {stats.tasks_completed} | "
                    f"{stats.tasks_in_progress} | {stats.tasks_blocked} |"
                )
            lines.append("")

        if self.blockers:
            lines.append("## Blockers")
            for blocker in self.blockers:
                lines.append(f"- {blocker}")
            lines.append("")

        if self.achievements:
            lines.append("## Team Achievements")
            for achievement in self.achievements:
                lines.append(f"- {achievement}")
            lines.append("")

        return "\n".join(lines)


class StandupReportGenerator:
    """Generates daily standup reports."""

    def __init__(self):
        self._db = get_db()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Ensure required tables exist for reporting."""
        # The activity table (MC-011) should be used for activity data
        # This ensures we have the tables we need
        pass

    def generate_report(
        self,
        date: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> StandupReport:
        """Generate a standup report.

        Args:
            date: Date string (YYYY-MM-DD). Defaults to today.
            agent_id: Optional agent ID to filter by

        Returns:
            StandupReport with statistics
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Calculate time range for the date
        start_ts = datetime.strptime(date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        ).timestamp()
        end_ts = start_ts + 86400  # Add 24 hours

        report = StandupReport(date=date)

        # Get task statistics from activity stream
        try:
            rows = self._db.execute_fetchall(
                """SELECT actor, type, entity_type, entity_id, description
                   FROM activities
                   WHERE created_at >= ? AND created_at < ?""",
                (start_ts, end_ts),
            )

            for row in rows:
                actor = row["actor"]
                event_type = row["type"]

                # Track agent stats
                if actor not in report.agent_stats:
                    report.agent_stats[actor] = AgentStats(agent_id=actor)

                # Count events
                if event_type == "task_completed":
                    report.total_tasks_completed += 1
                    report.agent_stats[actor].tasks_completed += 1
                    report.achievements.append(
                        f"{actor} completed: {row['description']}"
                    )
                elif event_type == "task_created":
                    report.total_new_tasks += 1
                    report.agent_stats[actor].tasks_created += 1
                elif event_type in ("task_status_changed", "task_assigned"):
                    if "blocked" in row["description"].lower():
                        report.total_tasks_blocked += 1
                        report.agent_stats[actor].tasks_blocked += 1
                        report.blockers.append(f"{actor}: {row['description']}")

        except Exception:
            # If no activity table, generate empty report
            pass

        # Get current running tasks
        try:
            in_progress_rows = self._db.execute_fetchall(
                """SELECT assigned_to, COUNT(*) as count
                   FROM tasks
                   WHERE status = ?
                   GROUP BY assigned_to""",
                (TaskStatus.RUNNING.value,),
            )
            for row in in_progress_rows:
                agent = row["assigned_to"] or "unassigned"
                if agent not in report.agent_stats:
                    report.agent_stats[agent] = AgentStats(agent_id=agent)
                report.agent_stats[agent].tasks_in_progress = row["count"]
                report.total_tasks_in_progress += row["count"]
        except Exception:
            pass

        # Trim achievements and blockers to top items
        report.achievements = report.achievements[:10]
        report.blockers = report.blockers[:10]

        return report

    def get_agent_daily_summary(
        self,
        agent_id: str,
        date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get a summary for a specific agent.

        Args:
            agent_id: Agent ID
            date: Date string (YYYY-MM-DD). Defaults to today.

        Returns:
            Summary dict
        """
        report = self.generate_report(date=date)
        stats = report.agent_stats.get(agent_id, AgentStats(agent_id=agent_id))

        return {
            "agent_id": agent_id,
            "date": report.date,
            "tasks_completed": stats.tasks_completed,
            "tasks_in_progress": stats.tasks_in_progress,
            "tasks_blocked": stats.tasks_blocked,
            "tasks_created": stats.tasks_created,
            "achievements": [
                a for a in report.achievements
                if a.startswith(agent_id)
            ],
            "blockers": [
                b for b in report.blockers
                if b.startswith(agent_id)
            ],
        }

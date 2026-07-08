# -*- coding: utf-8 -*-
"""SwarmCoordinator — idle detection, shutdown negotiation, and task claiming.

Coordinates agent lifecycle states and task distribution within a swarm team.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .mailbox import SwarmMailbox, MailMessage
from .team_file import TeamFile, TeamMember


# ---------------------------------------------------------------------------
# Task board entry
# ---------------------------------------------------------------------------

@dataclass
class TaskBoardEntry:
    """An entry on the team task board."""

    task_id: str
    description: str
    priority: int = 0
    claimed_by: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskBoardEntry:
        return cls(**data)


# ---------------------------------------------------------------------------
# Shutdown tracking
# ---------------------------------------------------------------------------

@dataclass
class ShutdownStatus:
    """Tracks the shutdown negotiation state for a single agent."""

    agent_name: str
    requested: bool = False
    approved: bool = False
    rejected: bool = False
    rejection_reason: str = ""
    approver: str = ""
    requested_at: float = 0.0
    resolved_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# SwarmCoordinator
# ---------------------------------------------------------------------------

class SwarmCoordinator:
    """Coordinate idle detection, shutdown negotiation, and task claiming."""

    def __init__(self, team_file: TeamFile, mailbox: SwarmMailbox):
        self.team_file = team_file
        self.mailbox = mailbox
        self._shutdown_statuses: Dict[str, ShutdownStatus] = {}
        self._task_board: Dict[str, TaskBoardEntry] = {}
        self._task_board_path = (
            team_file.base_dir
            / ".codebuddy"
            / "teams"
            / team_file.team_name
            / "task_board.json"
        )
        self._load_task_board()

    # -- task board persistence -----------------------------------------------

    def _load_task_board(self) -> None:
        if self._task_board_path.exists():
            try:
                raw = json.loads(self._task_board_path.read_text(encoding="utf-8"))
                self._task_board = {
                    k: TaskBoardEntry.from_dict(v) for k, v in raw.items()
                }
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load task board: {}", exc)
                self._task_board = {}

    def _save_task_board(self) -> None:
        self._task_board_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v.to_dict() for k, v in self._task_board.items()}
        self._task_board_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # -- idle detection -------------------------------------------------------

    def mark_idle(self, agent_name: str) -> None:
        """Mark an agent as idle."""
        member = self.team_file.get_member(agent_name)
        if member:
            member.status = "idle"
            self.team_file.save()
            logger.debug("Agent {} marked idle", agent_name)

    def mark_busy(self, agent_name: str) -> None:
        """Mark an agent as busy."""
        member = self.team_file.get_member(agent_name)
        if member:
            member.status = "busy"
            self.team_file.save()
            logger.debug("Agent {} marked busy", agent_name)

    def get_idle_agents(self) -> List[TeamMember]:
        """Return all idle team members."""
        return [m for m in self.team_file.members if m.status == "idle"]

    # -- shutdown negotiation -------------------------------------------------

    def request_shutdown(self, agent_name: str) -> bool:
        """An agent requests to shut down.

        Returns True if the agent has no outstanding task assignments
        (i.e. it is safe to shut down immediately).
        """
        # Check if agent has assigned tasks
        has_tasks = any(
            v == agent_name for v in self.team_file.task_assignments.values()
        )
        if has_tasks:
            logger.info("Agent {} requested shutdown but has assigned tasks", agent_name)

        status = self._shutdown_statuses.get(agent_name, ShutdownStatus(agent_name=agent_name))
        status.requested = True
        status.requested_at = time.time()
        self._shutdown_statuses[agent_name] = status

        # Notify the lead via mailbox
        lead = self._get_lead()
        if lead:
            self.mailbox.send(
                from_agent=agent_name,
                to_agent=lead.name,
                message=MailMessage(
                    id=f"mail-{uuid.uuid4().hex[:12]}",
                    from_agent=agent_name,
                    to_agent=lead.name,
                    type="shutdown_request",
                    content=f"Agent {agent_name} requests shutdown. Has tasks: {has_tasks}",
                ),
            )

        return not has_tasks

    def approve_shutdown(self, agent_name: str, approver: str) -> None:
        """Approve an agent's shutdown request."""
        status = self._shutdown_statuses.get(agent_name)
        if not status or not status.requested:
            logger.warning("No pending shutdown request for agent {}", agent_name)
            return

        status.approved = True
        status.rejected = False
        status.approver = approver
        status.resolved_at = time.time()

        # Update member status
        member = self.team_file.get_member(agent_name)
        if member:
            member.status = "shutting_down"
            self.team_file.save()

        # Notify the agent
        self.mailbox.send(
            from_agent=approver,
            to_agent=agent_name,
            message=MailMessage(
                id=f"mail-{uuid.uuid4().hex[:12]}",
                from_agent=approver,
                to_agent=agent_name,
                type="shutdown_response",
                content="Shutdown approved. You may terminate gracefully.",
            ),
        )
        logger.info("Shutdown approved for agent {} by {}", agent_name, approver)

    def reject_shutdown(self, agent_name: str, reason: str) -> None:
        """Reject an agent's shutdown request with a reason."""
        status = self._shutdown_statuses.get(agent_name)
        if not status or not status.requested:
            logger.warning("No pending shutdown request for agent {}", agent_name)
            return

        status.rejected = True
        status.approved = False
        status.rejection_reason = reason
        status.resolved_at = time.time()

        # Notify the agent
        self.mailbox.send(
            from_agent=self._get_lead_name(),
            to_agent=agent_name,
            message=MailMessage(
                id=f"mail-{uuid.uuid4().hex[:12]}",
                from_agent=self._get_lead_name(),
                to_agent=agent_name,
                type="shutdown_response",
                content=f"Shutdown rejected. Reason: {reason}",
            ),
        )
        logger.info("Shutdown rejected for agent {}: {}", agent_name, reason)

    def get_shutdown_status(self, agent_name: str) -> Dict[str, Any]:
        """Return the shutdown negotiation state for an agent."""
        status = self._shutdown_statuses.get(agent_name)
        if not status:
            return {"agent_name": agent_name, "requested": False}
        return status.to_dict()

    # -- task claiming --------------------------------------------------------

    def post_task(self, task_id: str, description: str, priority: int = 0) -> None:
        """Post a task to the team task board."""
        entry = TaskBoardEntry(
            task_id=task_id,
            description=description,
            priority=priority,
        )
        self._task_board[task_id] = entry
        self._save_task_board()
        logger.info("Task {} posted to board: {}", task_id, description)

    def claim_task(self, agent_name: str, task_id: str) -> bool:
        """Claim an available task. Returns True on success."""
        entry = self._task_board.get(task_id)
        if not entry:
            logger.warning("Task {} not found on board", task_id)
            return False
        if entry.claimed_by is not None:
            logger.warning("Task {} already claimed by {}", task_id, entry.claimed_by)
            return False

        entry.claimed_by = agent_name
        self.team_file.assign_task(task_id, agent_name)
        self._save_task_board()

        # Mark the agent as busy
        self.mark_busy(agent_name)

        logger.info("Task {} claimed by {}", task_id, agent_name)
        return True

    def release_task(self, agent_name: str, task_id: str) -> None:
        """Release a claimed task back to the board."""
        entry = self._task_board.get(task_id)
        if not entry or entry.claimed_by != agent_name:
            return

        entry.claimed_by = None
        self.team_file.unassign_task(task_id)
        self._save_task_board()
        logger.info("Task {} released by {}", task_id, agent_name)

    def get_available_tasks(self) -> List[Dict[str, Any]]:
        """Return all unclaimed tasks sorted by priority (highest first)."""
        available = [e for e in self._task_board.values() if e.claimed_by is None]
        available.sort(key=lambda e: e.priority, reverse=True)
        return [e.to_dict() for e in available]

    def get_agent_tasks(self, agent_name: str) -> List[Dict[str, Any]]:
        """Return all tasks claimed by a specific agent."""
        claimed = [e for e in self._task_board.values() if e.claimed_by == agent_name]
        return [e.to_dict() for e in claimed]

    # -- helpers --------------------------------------------------------------

    def _get_lead(self) -> Optional[TeamMember]:
        """Return the team lead member, if any."""
        for m in self.team_file.members:
            if m.role == "lead":
                return m
        return None

    def _get_lead_name(self) -> str:
        lead = self._get_lead()
        return lead.name if lead else "system"

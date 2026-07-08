# -*- coding: utf-8 -*-
"""TeamFile — shared state file for swarm teams.

Stores team membership, shared key-value state, and task assignments
under ``.codebuddy/teams/{team_name}/team.json``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class TeamMember:
    """A member of a swarm team."""

    name: str
    role: str  # "lead" | "worker"
    status: str  # "idle" | "busy" | "shutting_down"
    agent_id: str
    capabilities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TeamMember:
        return cls(**data)


class TeamFile:
    """Team shared-state file.

    Persists to ``<base_dir>/.codebuddy/teams/{team_name}/team.json``.
    """

    def __init__(
        self,
        team_name: str,
        base_dir: Path | None = None,
        members: List[TeamMember] | None = None,
        shared_state: Dict[str, Any] | None = None,
        task_assignments: Dict[str, str] | None = None,
    ):
        self.team_name = team_name
        self.base_dir = base_dir or Path.cwd()
        self.members: List[TeamMember] = members or []
        self.shared_state: Dict[str, Any] = shared_state or {}
        self.task_assignments: Dict[str, str] = task_assignments or {}
        self._created_at: float = time.time()
        self._updated_at: float = time.time()

    # -- persistence ----------------------------------------------------------

    @property
    def _team_dir(self) -> Path:
        return self.base_dir / ".codebuddy" / "teams" / self.team_name

    @property
    def _file_path(self) -> Path:
        return self._team_dir / "team.json"

    @classmethod
    def load(cls, path: Path) -> TeamFile:
        """Load a TeamFile from its *team directory* or the JSON file itself."""
        if path.is_dir():
            json_path = path / "team.json"
        else:
            json_path = path

        if not json_path.exists():
            raise FileNotFoundError(f"TeamFile not found: {json_path}")

        raw = json.loads(json_path.read_text(encoding="utf-8"))
        base_dir = json_path.parent.parent.parent  # .codebuddy/teams/{name}/ -> base

        members = [TeamMember.from_dict(m) for m in raw.get("members", [])]
        tf = cls(
            team_name=raw["team_name"],
            base_dir=base_dir,
            members=members,
            shared_state=raw.get("shared_state", {}),
            task_assignments=raw.get("task_assignments", {}),
        )
        tf._created_at = raw.get("created_at", tf._created_at)
        tf._updated_at = raw.get("updated_at", tf._updated_at)
        return tf

    def save(self) -> None:
        """Persist the TeamFile to disk."""
        self._updated_at = time.time()
        self._team_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "team_name": self.team_name,
            "members": [m.to_dict() for m in self.members],
            "shared_state": self.shared_state,
            "task_assignments": self.task_assignments,
            "created_at": self._created_at,
            "updated_at": self._updated_at,
        }
        self._file_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug("TeamFile saved: {}", self._file_path)

    # -- membership -----------------------------------------------------------

    def add_member(self, member: TeamMember) -> None:
        """Add a member. Replaces existing member with the same name."""
        self.remove_member(member.name)
        self.members.append(member)
        self.save()

    def remove_member(self, name: str) -> bool:
        """Remove a member by name. Returns True if a member was removed."""
        before = len(self.members)
        self.members = [m for m in self.members if m.name != name]
        removed = len(self.members) < before
        if removed:
            self.save()
        return removed

    def get_member(self, name: str) -> Optional[TeamMember]:
        """Get a member by name."""
        for m in self.members:
            if m.name == name:
                return m
        return None

    # -- shared state ---------------------------------------------------------

    def update_state(self, key: str, value: Any) -> None:
        """Set a shared state key-value pair."""
        self.shared_state[key] = value
        self.save()

    # -- task assignments -----------------------------------------------------

    def assign_task(self, task_id: str, member_name: str) -> None:
        """Assign a task to a member."""
        self.task_assignments[task_id] = member_name
        self.save()

    def unassign_task(self, task_id: str) -> bool:
        """Remove a task assignment. Returns True if it existed."""
        if task_id in self.task_assignments:
            del self.task_assignments[task_id]
            self.save()
            return True
        return False

    # -- helpers --------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "team_name": self.team_name,
            "members": [m.to_dict() for m in self.members],
            "shared_state": self.shared_state,
            "task_assignments": self.task_assignments,
            "created_at": self._created_at,
            "updated_at": self._updated_at,
        }

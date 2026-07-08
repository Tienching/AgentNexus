# -*- coding: utf-8 -*-
"""SwarmMailbox — file-based mailbox for inter-agent async communication.

Each team has its own mailbox directory under
``<base_dir>/.codebuddy/teams/{team_name}/mailbox/``.

Individual agent inboxes live at ``mailbox/{agent_name}/`` as JSON files,
one per message.  Broadcast messages are copied into every member inbox.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .team_file import TeamFile


@dataclass
class MailMessage:
    """A single message in the mailbox system."""

    id: str
    from_agent: str
    to_agent: str  # or "__broadcast__"
    type: str  # "task_assignment" | "task_result" | "shutdown_request" | "shutdown_response" | "status_update"
    content: str
    created_at: float = field(default_factory=time.time)
    read: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MailMessage:
        return cls(**data)


class SwarmMailbox:
    """File-based mailbox system for inter-agent async communication."""

    BROADCAST = "__broadcast__"

    def __init__(self, team_name: str, base_dir: Path | None = None):
        self.team_name = team_name
        self.base_dir = base_dir or Path.cwd()

    # -- paths ----------------------------------------------------------------

    @property
    def _mailbox_dir(self) -> Path:
        return self.base_dir / ".codebuddy" / "teams" / self.team_name / "mailbox"

    def _inbox_dir(self, agent_name: str) -> Path:
        """Return the inbox directory for *agent_name*, creating it if needed."""
        d = self._mailbox_dir / agent_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _msg_path(self, agent_name: str, message_id: str) -> Path:
        return self._inbox_dir(agent_name) / f"{message_id}.json"

    # -- send / receive -------------------------------------------------------

    def send(self, from_agent: str, to_agent: str, message: MailMessage) -> str:
        """Send a message to a specific agent's inbox.

        Returns the message ID.
        """
        if not message.id:
            message.id = f"mail-{uuid.uuid4().hex[:12]}"
        message.from_agent = from_agent
        message.to_agent = to_agent

        path = self._msg_path(to_agent, message.id)
        path.write_text(
            json.dumps(message.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug("Mail: {} -> {} [{}]", from_agent, to_agent, message.type)
        return message.id

    def receive(self, agent_name: str) -> List[MailMessage]:
        """Return all messages in an agent's inbox (newest first)."""
        inbox = self._inbox_dir(agent_name)
        messages: List[MailMessage] = []
        for f in sorted(inbox.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                messages.append(MailMessage.from_dict(data))
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Skipping malformed mail file {}: {}", f.name, exc)
        return messages

    def mark_read(self, agent_name: str, message_id: str) -> bool:
        """Mark a specific message as read. Returns True if found."""
        path = self._msg_path(agent_name, message_id)
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["read"] = True
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return True
        except (json.JSONDecodeError, OSError):
            return False

    def broadcast(self, from_agent: str, content: str, team_file: TeamFile) -> List[str]:
        """Broadcast a message to all team members (except sender).

        Returns list of message IDs.
        """
        ids: List[str] = []
        for member in team_file.members:
            if member.name == from_agent:
                continue
            msg = MailMessage(
                id=f"mail-{uuid.uuid4().hex[:12]}",
                from_agent=from_agent,
                to_agent=self.BROADCAST,
                type="status_update",
                content=content,
            )
            ids.append(self.send(from_agent, member.name, msg))
        logger.debug("Mail: broadcast from {} to {} members", from_agent, len(ids))
        return ids

    def get_unread_count(self, agent_name: str) -> int:
        """Return the number of unread messages for an agent."""
        return sum(1 for m in self.receive(agent_name) if not m.read)

    def delete_message(self, agent_name: str, message_id: str) -> bool:
        """Delete a message from an agent's inbox. Returns True if found."""
        path = self._msg_path(agent_name, message_id)
        if path.exists():
            path.unlink()
            return True
        return False

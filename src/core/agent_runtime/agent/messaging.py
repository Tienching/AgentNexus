# -*- coding: utf-8 -*-
"""Inter-agent messaging system.

MC-018: Supports direct messages, group channels, and typed message metadata.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.core.stores.sqlite_backend import get_backend


class MessageType(str, Enum):
    DIRECT = "direct"
    GROUP = "group"
    SYSTEM = "system"
    ASSIGNMENT = "assignment"
    BLOCKER = "blocker"
    UPDATE = "update"


@dataclass
class AgentMessage:
    id: str
    from_agent: str
    to_agent: Optional[str]
    channel: Optional[str]
    type: MessageType
    content: str
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    read: bool = False


class AgentMessagingService:
    """SQLite-backed agent messaging service."""

    def __init__(self):
        self._store = get_backend()

    @staticmethod
    def _msg_key(message_id: str) -> str:
        return f"agent_msg:{message_id}"

    @staticmethod
    def _inbox_key(agent_name: str) -> str:
        return f"agent_inbox:{agent_name}"

    @staticmethod
    def _channel_key(channel: str) -> str:
        return f"agent_channel:{channel}"

    @staticmethod
    def _conv_key(a: str, b: str) -> str:
        left, right = sorted([a, b])
        return f"agent_conv:{left}:{right}"

    def send_direct(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        message_type: MessageType = MessageType.DIRECT,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentMessage:
        """Send a direct message from one agent to another."""
        msg = AgentMessage(
            id=f"msg-{uuid.uuid4().hex[:12]}",
            from_agent=from_agent,
            to_agent=to_agent,
            channel=None,
            type=message_type,
            content=content,
            metadata=metadata or {},
        )
        self._persist_message(msg)

        self._store.rpush(self._inbox_key(to_agent), msg.id)
        self._store.rpush(self._conv_key(from_agent, to_agent), msg.id)
        return msg

    def send_group(
        self,
        from_agent: str,
        channel: str,
        content: str,
        recipients: Optional[List[str]] = None,
        message_type: MessageType = MessageType.GROUP,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentMessage:
        """Send a group message to a channel (optionally fan-out to inboxes)."""
        msg = AgentMessage(
            id=f"msg-{uuid.uuid4().hex[:12]}",
            from_agent=from_agent,
            to_agent=None,
            channel=channel,
            type=message_type,
            content=content,
            metadata=metadata or {},
        )
        self._persist_message(msg)

        self._store.rpush(self._channel_key(channel), msg.id)
        for name in recipients or []:
            self._store.rpush(self._inbox_key(name), msg.id)
        return msg

    def get_inbox(self, agent_name: str, limit: int = 100, unread_only: bool = False) -> List[AgentMessage]:
        """Get agent inbox messages (newest first)."""
        ids = self._store.lrange(self._inbox_key(agent_name), 0, max(0, limit))
        messages = [self.get_message(str(mid)) for mid in ids]
        out = [m for m in messages if m is not None]
        if unread_only:
            out = [m for m in out if not m.read]
        out.sort(key=lambda m: m.created_at, reverse=True)
        return out[:limit]

    def get_channel_messages(self, channel: str, limit: int = 100) -> List[AgentMessage]:
        ids = self._store.lrange(self._channel_key(channel), 0, max(0, limit))
        messages = [self.get_message(str(mid)) for mid in ids]
        out = [m for m in messages if m is not None]
        out.sort(key=lambda m: m.created_at, reverse=True)
        return out[:limit]

    def get_conversation(self, agent_a: str, agent_b: str, limit: int = 100) -> List[AgentMessage]:
        ids = self._store.lrange(self._conv_key(agent_a, agent_b), 0, max(0, limit))
        messages = [self.get_message(str(mid)) for mid in ids]
        out = [m for m in messages if m is not None]
        out.sort(key=lambda m: m.created_at)
        return out[-limit:]

    def get_message(self, message_id: str) -> Optional[AgentMessage]:
        payload = self._store.hgetall(self._msg_key(message_id))
        if not payload:
            return None
        try:
            return AgentMessage(
                id=str(payload.get("id")),
                from_agent=str(payload.get("from_agent")),
                to_agent=str(payload.get("to_agent")) if payload.get("to_agent") else None,
                channel=str(payload.get("channel")) if payload.get("channel") else None,
                type=MessageType(str(payload.get("type") or MessageType.DIRECT.value)),
                content=str(payload.get("content") or ""),
                created_at=float(payload.get("created_at") or time.time()),
                metadata=dict(payload.get("metadata") or {}),
                read=bool(payload.get("read") or False),
            )
        except Exception:
            return None

    def mark_read(self, message_id: str) -> bool:
        msg = self.get_message(message_id)
        if not msg:
            return False
        msg.read = True
        self._persist_message(msg)
        return True

    def _persist_message(self, msg: AgentMessage) -> None:
        key = self._msg_key(msg.id)
        payload = asdict(msg)
        payload["type"] = msg.type.value
        self._store.hset(key, "id", payload["id"])
        self._store.hset(key, "from_agent", payload["from_agent"])
        self._store.hset(key, "to_agent", payload["to_agent"])
        self._store.hset(key, "channel", payload["channel"])
        self._store.hset(key, "type", payload["type"])
        self._store.hset(key, "content", payload["content"])
        self._store.hset(key, "created_at", payload["created_at"])
        self._store.hset(key, "metadata", payload["metadata"])
        self._store.hset(key, "read", payload["read"])


_service: Optional[AgentMessagingService] = None


def get_messaging_service() -> AgentMessagingService:
    global _service
    if _service is None:
        _service = AgentMessagingService()
    return _service

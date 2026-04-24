# -*- coding: utf-8 -*-
"""Session bridge: maps agent-nexus session IDs to nexus session keys.

Nexus sessions are identified by ``"channel:chat_id"`` strings. We prefix
agent-nexus IDs with ``"nexus:"`` so they never collide with native
channel sessions coming from Telegram / Slack / etc.
Legacy nanobot helper names are kept as aliases.
"""

from __future__ import annotations


_PREFIX = "nexus"


def to_nexus_session_key(session_id: str) -> str:
    """Convert an agent-nexus ``session_id`` to a nexus session key.

    >>> to_nexus_session_key("abc123")
    'nexus:abc123'
    """
    return f"{_PREFIX}:{session_id}"


def to_nexus_channel_and_chat(session_id: str) -> tuple[str, str]:
    """Return (channel, chat_id) for a nexus InboundMessage.

    >>> to_nexus_channel_and_chat("abc123")
    ('nexus', 'abc123')
    """
    return _PREFIX, session_id


def from_nexus_session_key(session_key: str) -> str | None:
    """Extract the agent-nexus session_id from a nexus session key.

    Returns ``None`` if the key was not created by us.

    >>> from_nexus_session_key("nexus:abc123")
    'abc123'
    >>> from_nexus_session_key("telegram:12345") is None
    True
    """
    if session_key.startswith(f"{_PREFIX}:"):
        return session_key[len(_PREFIX) + 1:]
    return None


# Backward-compatible nanobot aliases
to_nanobot_session_key = to_nexus_session_key
to_nanobot_channel_and_chat = to_nexus_channel_and_chat
from_nanobot_session_key = from_nexus_session_key

__all__ = [
    "to_nexus_session_key",
    "to_nexus_channel_and_chat",
    "from_nexus_session_key",
    "to_nanobot_session_key",
    "to_nanobot_channel_and_chat",
    "from_nanobot_session_key",
]

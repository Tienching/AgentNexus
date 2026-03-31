# -*- coding: utf-8 -*-
"""Session bridge: maps agent-nexus session IDs to nanobot session keys.

Nanobot sessions are identified by ``"channel:chat_id"`` strings.  We
prefix nexus IDs with ``nexus:`` so they never collide with native
nanobot sessions coming from Telegram / Slack / etc.
"""

from __future__ import annotations


_PREFIX = "nexus"


def to_nanobot_session_key(session_id: str) -> str:
    """Convert an agent-nexus ``session_id`` to a nanobot session key.

    >>> to_nanobot_session_key("abc123")
    'nexus:abc123'
    """
    return f"{_PREFIX}:{session_id}"


def to_nanobot_channel_and_chat(session_id: str) -> tuple[str, str]:
    """Return (channel, chat_id) for a nanobot InboundMessage.

    >>> to_nanobot_channel_and_chat("abc123")
    ('nexus', 'abc123')
    """
    return _PREFIX, session_id


def from_nanobot_session_key(session_key: str) -> str | None:
    """Extract the agent-nexus session_id from a nanobot session key.

    Returns ``None`` if the key was not created by us.

    >>> from_nanobot_session_key("nexus:abc123")
    'abc123'
    >>> from_nanobot_session_key("telegram:12345") is None
    True
    """
    if session_key.startswith(f"{_PREFIX}:"):
        return session_key[len(_PREFIX) + 1:]
    return None

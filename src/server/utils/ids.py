# -*- coding: utf-8 -*-
"""Unified ID generation for sessions, runs, and channels.

Format
------
- Session (chat / history promote / task): ``session_{ts8}{rand4}``
- Run (AG-UI single request-response):     ``run_{ts8}{rand4}``
- Channel (deterministic per platform):     ``channel_{platform}_{chatId}``

The *short_id* is a 12-hex-char string: 8 hex digits of the current
Unix timestamp (seconds, big-endian) followed by 4 hex digits of
cryptographic randomness.  This makes IDs naturally time-ordered while
remaining short and collision-resistant.

External callers may supply their own IDs; the ``resolve_*`` helpers
fall back to auto-generation only when the external value is empty.
"""

import os
import time


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _short_id() -> str:
    """Return a 12-hex-char, time-ordered short identifier.

    Layout: ``TTTTTTTT RRRR``
      - ``T`` = 8 hex digits from ``int(time.time())`` (4 bytes, big-endian)
      - ``R`` = 4 hex digits of ``os.urandom(2)``
    """
    ts = int(time.time()).to_bytes(4, "big").hex()
    rand = os.urandom(2).hex()
    return ts + rand


# ---------------------------------------------------------------------------
# Session IDs
# ---------------------------------------------------------------------------

def gen_session_id() -> str:
    """Generate a new session ID (for chat, history promote, task, etc.)."""
    return f"session_{_short_id()}"


def gen_channel_session_id(channel: str, chat_id: str) -> str:
    """Generate a deterministic channel session ID."""
    return f"channel_{channel}_{chat_id}"


def resolve_session_id(external_id: str | None) -> str:
    """Use the caller-supplied ID if non-empty, otherwise auto-generate."""
    if external_id and external_id.strip():
        return external_id.strip()
    return gen_session_id()


# ---------------------------------------------------------------------------
# Run IDs
# ---------------------------------------------------------------------------

def gen_run_id() -> str:
    """Generate a new run ID (AG-UI single request-response cycle)."""
    return f"run_{_short_id()}"


def resolve_run_id(external_id: str | None) -> str:
    """Use the caller-supplied run ID if non-empty, otherwise auto-generate."""
    if external_id and external_id.strip():
        return external_id.strip()
    return gen_run_id()

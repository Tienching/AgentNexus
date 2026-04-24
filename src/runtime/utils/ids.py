# -*- coding: utf-8 -*-
"""Shared ID generation for runtime and server layers."""

from __future__ import annotations

import os
import time


def _short_id() -> str:
    """Return a short, time-prefixed identifier with enough entropy to avoid collisions."""
    ts = int(time.time()).to_bytes(4, "big").hex()
    rand = os.urandom(4).hex()
    return ts + rand


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


def gen_run_id() -> str:
    """Generate a new run ID (AG-UI single request-response cycle)."""
    return f"run_{_short_id()}"


def resolve_run_id(external_id: str | None) -> str:
    """Use the caller-supplied run ID if non-empty, otherwise auto-generate."""
    if external_id and external_id.strip():
        return external_id.strip()
    return gen_run_id()


__all__ = [
    "gen_channel_session_id",
    "gen_run_id",
    "gen_session_id",
    "resolve_run_id",
    "resolve_session_id",
]

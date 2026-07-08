# -*- coding: utf-8 -*-
"""Exec-user validation guard.

The chat / terminal endpoints accept exec_user (a Linux username) and
switch to that user via su - <user> -c ... before running a CLI. Without
validation this is an identity-spoofing vector: a caller can target any
existing system account (incl. root).

This module centralises a strict allow-list check that every exec_user
flow must pass before reaching su.
"""

from __future__ import annotations

import asyncio
import os
import pwd
import re

from fastapi import HTTPException, status

# A safe Linux username: start with letter/underscore, followed by letters,
# digits, underscore or dash. Max 32 chars (glibc LOGIN_NAME_MAX boundary).
_USERNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,31}$")

# Reserved / dangerous names that must never be used as an exec target, even
# if they happen to exist on the host.
_RESERVED = {"root", "toor", "nobody", "daemon", "bin", "sys", "halt", "shutdown"}


def _allowed_whitelist() -> set[str] | None:
    """Return the optional allowed-user set from ALLOWED_EXEC_USERS env.

    Comma-separated. Empty/unset means "any valid existing user" (still subject
    to the regex + existence + reserved checks).
    """
    raw = (os.getenv("ALLOWED_EXEC_USERS") or "").strip()
    if not raw:
        return None
    return {name.strip() for name in raw.split(",") if name.strip()}


def _check_user_core(user: str) -> str:
    """Server-side core validation. Reuses providers.base rules + allow-list.

    The format/reserved/existence rules are delegated to
    :func:`src.providers.base._validate_target_user` (single source of truth);
    this wrapper adds the optional ALLOWED_EXEC_USERS allow-list.
    """
    from src.providers.base import _validate_target_user

    if not isinstance(user, str) or not user:
        raise ValueError("exec_user is required")
    _validate_target_user(user)  # format + reserved + existence (no echo)
    whitelist = _allowed_whitelist()
    if whitelist is not None and user not in whitelist:
        raise ValueError("exec_user is not in the allow list")
    return user


def validate_exec_user_sync(user: str) -> str:
    """Validate an exec_user value and return it if safe (sync)."""
    return _check_user_core(user)


async def validate_exec_user(user: str) -> str:
    """Validate an exec_user value and return it if safe (async).

    The ``pwd.getpwnam`` lookup is a blocking system call, so it runs in a
    thread to avoid stalling the event loop. Raises ``HTTPException`` on any
    violation so it can be used directly inside a FastAPI handler.
    """
    try:
        return await asyncio.to_thread(_check_user_core, user)
    except ValueError as exc:
        msg = str(exc)
        # Reserved/allow-list denials are 403; format/existence are 400.
        if "not permitted" in msg or "allow list" in msg:
            code = status.HTTP_403_FORBIDDEN
        else:
            code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg)

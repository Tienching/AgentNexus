# -*- coding: utf-8 -*-
"""Shared error-message sanitisation for provider / SSE error events.

Raw exception text (file paths, host names, config values, stack details) must
not be streamed to clients. The full exception is logged here; callers receive
a generic, localised message unless running in an explicit debug mode.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_GENERIC = "处理请求时出错，请稍后重试或联系管理员"
_GENERIC_TIMEOUT = "处理超时，请重试"


def _is_debug() -> bool:
    return str(os.getenv("DEBUG", "false")).lower() in {"1", "true", "yes"} or            str(os.getenv("NEXUS_DEBUG_ERRORS", "false")).lower() in {"1", "true", "yes"}


def safe_error_message(exc: BaseException | str, *, timeout: bool = False) -> str:
    """Return a client-safe message and log the full exception.

    Args:
        exc: the exception (or raw message string) to sanitise.
        timeout: when True, return the dedicated timeout message.

    The full ``repr`` is always logged at error level for operators; the
    returned string is safe to stream to end users.
    """
    raw = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    logger.error("Sanitised provider error: %s", raw, exc_info=not isinstance(exc, str))
    if _is_debug():
        # Only when operators explicitly opt in.
        return raw[:500]
    return _GENERIC_TIMEOUT if timeout else _GENERIC

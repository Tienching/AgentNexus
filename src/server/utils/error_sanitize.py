# -*- coding: utf-8 -*-
"""Server-side error sanitisation (HTTPException detail / API responses).

Mirrors providers/_error_sanitize but kept under server/utils so the server
layer does not depend on the providers package. Raw exception text is logged;
clients receive a generic localised message unless debug is opted in.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_GENERIC = "服务器内部错误，请稍后重试或联系管理员"


def _is_debug() -> bool:
    return str(os.getenv("DEBUG", "false")).lower() in {"1", "true", "yes"} or            str(os.getenv("NEXUS_DEBUG_ERRORS", "false")).lower() in {"1", "true", "yes"}


def safe_error_message(exc: BaseException | str) -> str:
    """Log the full exception and return a client-safe generic message."""
    raw = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    logger.error("Sanitised server error: %s", raw, exc_info=not isinstance(exc, str))
    return raw[:500] if _is_debug() else _GENERIC

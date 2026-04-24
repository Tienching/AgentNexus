# -*- coding: utf-8 -*-
"""Core-session storage compatibility facade.

The canonical implementation now lives in :mod:`src.runtime.stores.session_storage`.
Keep the legacy ``src.core.stores.session_storage`` import path alive, but do not
maintain a second storage implementation here.
"""

from __future__ import annotations

from src.runtime.stores.session_storage import (
    SESSION_TTL,
    STREAMING_CONTENT_TTL,
    SessionStorage,
    get_session_storage,
)

__all__ = [
    "SESSION_TTL",
    "STREAMING_CONTENT_TTL",
    "SessionStorage",
    "get_session_storage",
]

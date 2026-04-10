# -*- coding: utf-8 -*-
"""Session Storage Service (thin adapter)

Canonical implementation lives in `src.runtime.stores.session_storage`.
This module preserves the import path for the FastAPI layer.
"""

from __future__ import annotations

from typing import Optional

from src.runtime.stores.session_storage import (
    SessionStorage,
    SESSION_TTL,
    STREAMING_CONTENT_TTL,
)


_storage: Optional[SessionStorage] = None


def get_session_storage() -> SessionStorage:
    global _storage
    if _storage is None:
        _storage = SessionStorage()
    return _storage

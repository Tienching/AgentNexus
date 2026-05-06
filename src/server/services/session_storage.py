# -*- coding: utf-8 -*-
"""Session Storage Service (thin adapter)

Canonical implementation lives in `src.runtime.stores.session_storage`.
This module preserves the import path for the FastAPI layer.
"""

from __future__ import annotations

from src.runtime.stores.session_storage import (
    SessionStorage,
)
from .app_container import get_app_container


def get_session_storage() -> SessionStorage:
    return get_app_container().session_storage()

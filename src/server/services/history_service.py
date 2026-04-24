# -*- coding: utf-8 -*-
"""History service (thin adapter).

Canonical implementation lives in ``src.runtime.history.service``.
This module preserves an app-scoped access path for API-layer callers so the
server does not repeatedly instantiate parser registries and caches.
"""

from __future__ import annotations

from src.runtime.history import HistoryService

from .app_container import get_app_container


def get_history_service() -> HistoryService:
    """Return the app-scoped HistoryService instance."""
    return get_app_container().history_service()


__all__ = ["HistoryService", "get_history_service"]

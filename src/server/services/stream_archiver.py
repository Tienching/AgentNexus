# -*- coding: utf-8 -*-
"""Stream Archiver (thin adapter)

Canonical implementation lives in `src.runtime.archiving.stream_archiver`.
This module preserves the import path used by the FastAPI layer and tests.
"""

from __future__ import annotations

from typing import Optional

from .session_storage import get_session_storage
from src.runtime.archiving.stream_archiver import StreamArchiver as StreamArchiver  # noqa: F401
from src.runtime.archiving.stream_archiver import StreamArchiver as _RuntimeStreamArchiver


def create_archiver(
    thread_id: str,
    run_id: Optional[str],
    username: str,
    agent_name: Optional[str] = None,
    provider: Optional[str] = None,
):
    """Factory compatible with historical API.

    Ensures the default storage uses the API-layer `get_session_storage()` which is
    configured with the same Redis key prefix and connection settings.
    """

    return _RuntimeStreamArchiver(
        session_id=thread_id,
        thread_id=thread_id,
        run_id=run_id,
        username=username,
        agent_name=agent_name,
        provider=provider,
        storage=get_session_storage(),
    )

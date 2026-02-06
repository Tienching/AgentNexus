# -*- coding: utf-8 -*-
"""Stream Archiver (thin adapter)

Canonical implementation lives in `src.runtime.archiving.stream_archiver`.
This module preserves the import path used by the FastAPI layer and tests.
"""

from __future__ import annotations

import logging
from typing import Optional

from .session_storage import get_session_storage
from src.runtime.archiving.stream_archiver import StreamArchiver as StreamArchiver  # noqa: F401
from src.runtime.archiving.stream_archiver import StreamArchiver as _RuntimeStreamArchiver

logger = logging.getLogger(__name__)


def create_archiver(
    thread_id: str,
    run_id: Optional[str],
    username: str,
    agent_name: Optional[str] = None,
    provider: Optional[str] = None,
    alias: Optional[str] = None,
):
    """Factory compatible with historical API.

    Ensures the default storage uses the API-layer `get_session_storage()` which is
    configured with the same Redis key prefix and connection settings.

    Also checks for target_session_id override (for /workspace -t mode).
    """
    storage = get_session_storage()

    # Check if there's a target_session_id override (for /workspace -t mode)
    # If set, archive messages to the target session instead of the current session
    archive_session_id = thread_id
    try:
        target_session_id = storage.get_target_session_id(thread_id)
        if target_session_id:
            archive_session_id = target_session_id
            logger.info(f"Using target_session_id for archiving: {thread_id} -> {target_session_id}")
    except Exception as e:
        logger.warning(f"Failed to check target_session_id: {e}")

    return _RuntimeStreamArchiver(
        session_id=archive_session_id,  # Use target_session_id if set
        thread_id=thread_id,
        run_id=run_id,
        username=username,
        agent_name=agent_name,
        provider=provider,
        alias=alias,
        storage=storage,
    )

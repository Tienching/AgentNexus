# -*- coding: utf-8 -*-
"""Stream Archiver (thin adapter)

Canonical implementation lives in `src.runtime.archiving.stream_archiver`.
This module preserves the import path used by the FastAPI layer and tests.
"""

from __future__ import annotations

import logging
from typing import Optional

from .session_storage import get_session_storage
from .observability import record_sampled_event, telemetry
from src.runtime.archiving.stream_archiver import StreamArchiver as StreamArchiver  # noqa: F401
from src.runtime.archiving.stream_archiver import StreamArchiver as _RuntimeStreamArchiver

logger = logging.getLogger(__name__)


def create_archiver(
    thread_id: str,
    run_id: Optional[str],
    username: str,
    exec_user: Optional[str] = None,
    provider: Optional[str] = None,
    alias: Optional[str] = None,
    execution_binding: Optional[object] = None,
    source_session_id: Optional[str] = None,
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
    compat_hits: list[str] = []
    try:
        target_session_id = storage.get_target_session_id(thread_id)
        if target_session_id:
            archive_session_id = target_session_id
            compat_hits.append("target_session_override")
            logger.info(f"Using target_session_id for archiving: {thread_id} -> {target_session_id}")
    except Exception as e:
        logger.warning(f"Failed to check target_session_id: {e}")

    if execution_binding is not None:
        binding_session_id = getattr(execution_binding, "session_id", None)
        binding_cli_session_id = getattr(execution_binding, "cli_session_id", None)
        binding_kind = getattr(execution_binding, "session_kind", None)
        if binding_session_id and binding_session_id != archive_session_id:
            compat_hits.append("binding_session_supersedes_thread")
            archive_session_id = binding_session_id
        telemetry.increment("stream_archiver.binding_seen")
        record_sampled_event(
            "stream_archiver.binding",
            {
                "thread_id": thread_id,
                "archive_session_id": archive_session_id,
                "source_session_id": source_session_id,
                "binding_session_id": binding_session_id,
                "binding_cli_session_id_present": bool(binding_cli_session_id),
                "binding_kind": binding_kind,
                "compat_hits": compat_hits,
            },
        )

    if compat_hits:
        for hit in compat_hits:
            telemetry.increment(f"stream_archiver.compat.{hit}")
        logger.debug(
            "Stream archiver compatibility resolution",
            extra={
                "thread_id": thread_id,
                "archive_session_id": archive_session_id,
                "source_session_id": source_session_id,
                "compat_hits": compat_hits,
            },
        )

    return _RuntimeStreamArchiver(
        session_id=archive_session_id,  # Use target_session_id if set
        thread_id=thread_id,
        run_id=run_id,
        username=username,
        exec_user=exec_user,
        provider=provider,
        alias=alias,
        storage=storage,
    )

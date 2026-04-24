# -*- coding: utf-8 -*-
"""Nexus SSE Streaming API Router

Provides SSE (Server-Sent Events) streaming endpoints for real-time
AG-UI event delivery, plus session self-healing helper functions.

Includes:
- SSE streaming for task AG-UI events
- SSE streaming for session AG-UI events
- Session self-heal logic for stuck "RUNNING" sessions
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..config import settings
from ..models import (
    SessionStatus,
)
from ..services.session_storage import get_session_storage
from ..logger import get_logger
from .nexus_auth import verify_nexus_auth
from .nexus_models import get_task_queue

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-streaming"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ============ SSE Helper Functions ============


def parse_last_event_id(request: Request) -> Optional[int]:
    """Parse Last-Event-ID header for SSE reconnection support."""
    v = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")
    if v is None:
        return None
    try:
        return int(str(v).strip())
    except Exception:
        return None


def resolve_session_stale_timeout_seconds(session_id: str) -> int:
    """Resolve stale self-heal threshold for a runtime session."""
    base_timeout = int(getattr(settings, "cli_timeout", 600) or 600)
    if session_id.startswith("channel_wecom_bot_"):
        return max(base_timeout, int(getattr(settings, "wecom_bot_cli_timeout", 0) or 0), 60) + 60
    if session_id.startswith("channel_wecom_"):
        return max(base_timeout, int(getattr(settings, "wecom_cli_timeout", 0) or 0), 60) + 60
    return max(base_timeout, 60) + 60


def self_heal_running_session(storage, session_id: str, updated_at) -> Optional[SessionStatus]:
    """Check if a session stuck in RUNNING should be healed, and fix it if so.

    Scans the last N events for RUN_STARTED / RUN_FINISHED / RUN_ERROR.
    Only heals if the terminal event appears AFTER the last RUN_STARTED.
    Falls back to stale-timeout healing (cli_timeout + 60s) if no terminal event found.

    Returns the new status if healed, or None if no healing was performed.
    """
    updated_at_ms = 0
    if updated_at is not None:
        try:
            updated_at_ms = int(updated_at)
        except (ValueError, TypeError):
            pass

    now_ms = int(time.time() * 1000)
    recently_updated = updated_at_ms > 0 and (now_ms - updated_at_ms) < 30_000
    if recently_updated:
        return None

    # Scan last events for terminal markers
    healed = False
    total_events = storage.get_agui_event_count(session_id)
    if total_events > 0:
        scan_count = min(total_events, 20)
        last_events = storage.get_agui_events(
            session_id,
            start=max(0, total_events - scan_count),
            end=total_events - 1,
        )
        last_started_idx = -1
        last_terminal_idx = -1
        last_terminal_type = None
        for idx, evt in enumerate(last_events):
            if isinstance(evt, dict):
                if evt.get("type") == "RUN_STARTED":
                    last_started_idx = idx
                elif evt.get("type") in ("RUN_FINISHED", "RUN_ERROR"):
                    last_terminal_idx = idx
                    last_terminal_type = evt.get("type")

        if last_terminal_idx > last_started_idx and last_terminal_type:
            new_status = SessionStatus.ERROR if last_terminal_type == "RUN_ERROR" else SessionStatus.COMPLETED
            storage.update_session_status(session_id, new_status)
            logger.info(f"Self-healed session {session_id} status: running -> {new_status.value}")
            return new_status

    # Stale timeout: effective session timeout + 60 seconds with no terminal event
    stale_threshold_seconds = resolve_session_stale_timeout_seconds(session_id)
    stale_threshold_ms = stale_threshold_seconds * 1000
    if updated_at_ms > 0 and (now_ms - updated_at_ms) > stale_threshold_ms:
        storage.update_session_status(session_id, SessionStatus.COMPLETED)
        logger.info(f"Self-healed stale session {session_id} status: running -> completed (stale {(now_ms - updated_at_ms) // 1000}s)")
        return SessionStatus.COMPLETED

    return None


def compute_initial_cursor(
    storage,
    session_id: str,
    total: int,
    tail: int,
    *,
    smart_cursor: bool = False,
) -> int:
    """Compute the starting cursor for SSE event replay.

    Args:
        smart_cursor: If True (session stream), scan for the last RUN_STARTED
            event and start from there to avoid replaying a previous run's
            RUN_FINISHED which would close the stream immediately.
    """
    raw_cursor = max(0, total - tail)

    if not smart_cursor or total <= 0:
        return raw_cursor

    scan_start = max(0, total - min(total, tail))
    try:
        scan_events = storage.get_agui_events(session_id, start=scan_start, end=total - 1)
        last_run_started_offset = -1
        for offset, evt in enumerate(scan_events):
            if isinstance(evt, dict) and evt.get("type") == "RUN_STARTED":
                last_run_started_offset = offset
        if last_run_started_offset >= 0:
            return scan_start + last_run_started_offset
    except Exception:
        pass
    return raw_cursor


async def sse_generate_events(
    request: Request,
    storage,
    session_id: str,
    cursor: int,
    poll_interval_ms: int,
    idle_timeout_check,
):
    """Shared SSE async generator for streaming AG-UI events.

    Args:
        idle_timeout_check: Async callable(idle_cycles) -> bool.
            Called when idle_cycles exceeds max_idle_cycles.
            Return True to close the stream, False to keep waiting.
    """
    last_heartbeat = 0.0
    idle_cycles = 0
    max_idle_cycles = 600  # ~3 min of idle at default 300ms interval
    is_initial_replay = True

    while True:
        if await request.is_disconnected():
            break

        # Heartbeat to prevent proxy buffering / connection drops
        now = time.time()
        if now - last_heartbeat >= 15:
            last_heartbeat = now
            yield ": heartbeat\n\n"

        total = storage.get_agui_event_count(session_id)
        if total > cursor:
            idle_cycles = 0
            events = storage.get_agui_events(session_id, start=cursor, end=total - 1)
            batch_size = len(events)
            for i, (idx, evt) in enumerate(zip(range(cursor, cursor + batch_size), events)):
                try:
                    payload = json.dumps(evt, ensure_ascii=False)
                    yield f"id: {idx}\ndata: {payload}\n\n"
                    if isinstance(evt, dict) and evt.get("type") in ("RUN_FINISHED", "RUN_ERROR"):
                        return
                except Exception:
                    continue
                # During initial replay, add small delays every few events
                # so the frontend renders progressively
                if is_initial_replay and batch_size > 10 and (i + 1) % 5 == 0:
                    await asyncio.sleep(0.02)
            cursor += batch_size
            is_initial_replay = False
        else:
            idle_cycles += 1
            is_initial_replay = False
            if idle_cycles > max_idle_cycles:
                if await idle_timeout_check():
                    return

        await asyncio.sleep(poll_interval_ms / 1000.0)


def make_sse_response(generator) -> StreamingResponse:
    """Wrap an async generator into a standard SSE StreamingResponse."""
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============ SSE Streaming Endpoints ============


@router.get("/tasks/{task_id}/agui/stream", response_class=StreamingResponse)
async def stream_task_agui_messages(
    request: Request,
    task_id: str,
    exec_user: str = Query(settings.exec_user, description="Exec user for task isolation"),
    tail: Optional[int] = Query(200, ge=1, le=5000, description="Replay only the last N events on first connect"),
    poll_interval_ms: int = Query(300, ge=200, le=5000, description="Polling interval in ms"),
):
    """Stream task AG-UI events via SSE.

    Tasks run in the background; the browser cannot access the CLI raw SSE directly.
    During task execution, converted AG-UI events are written to a Redis event log.
    This endpoint replays them in order via SSE to the frontend.

    Supports `Last-Event-ID` for automatic reconnection.
    """
    queue = get_task_queue(exec_user)
    task = queue.get_task(task_id)
    session_id = (task.session_id if task else None) or f"task_{task_id}"
    storage = get_session_storage()

    # Self-heal stuck sessions
    try:
        session_meta = storage.get_session_meta(session_id)
        if session_meta and session_meta.status == SessionStatus.RUNNING:
            self_heal_running_session(storage, session_id, session_meta.updated_at)
    except Exception as e:
        logger.warning(f"Failed to self-heal task session status: {e}")

    # Compute initial cursor
    last_id = parse_last_event_id(request)
    total = storage.get_agui_event_count(session_id)
    if last_id is not None:
        cursor = max(0, last_id + 1)
    else:
        cursor = compute_initial_cursor(storage, session_id, total, int(tail or 200))

    async def check_task_idle_timeout() -> bool:
        try:
            task_obj = queue.get_task(task_id)
            if task_obj and task_obj.status in ("completed", "failed", "cancelled"):
                return True
        except Exception:
            pass
        return False

    return make_sse_response(
        sse_generate_events(request, storage, session_id, cursor, poll_interval_ms, check_task_idle_timeout)
    )


@router.get("/sessions/{session_id}/agui/stream", response_class=StreamingResponse)
async def stream_session_agui_messages(
    request: Request,
    session_id: str,
    tail: Optional[int] = Query(200, ge=1, le=5000, description="Replay only the last N events on first connect"),
    poll_interval_ms: int = Query(300, ge=200, le=5000, description="Polling interval in ms"),
):
    """Stream session AG-UI events via SSE.

    Suitable for channel sessions (e.g., WeCom channel_wecom_*) and other
    non-Chat scenarios, enabling the Nexus frontend to see real-time
    streaming output during message processing.

    Supports `Last-Event-ID` for automatic reconnection.
    """
    storage = get_session_storage()

    meta = storage.get_session_meta(session_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Session not found")

    # Self-heal stuck sessions
    if meta.status == SessionStatus.RUNNING:
        try:
            new_status = self_heal_running_session(storage, session_id, meta.updated_at)
            if new_status:
                meta.status = new_status
        except Exception as e:
            logger.warning(f"Failed to self-heal session status: {e}")

    # Compute initial cursor (with smart cursor for session streams)
    last_id = parse_last_event_id(request)
    total = storage.get_agui_event_count(session_id)
    if last_id is not None:
        cursor = max(0, last_id + 1)
    else:
        cursor = compute_initial_cursor(
            storage, session_id, total, int(tail or 200), smart_cursor=True,
        )

    async def check_session_idle_timeout() -> bool:
        try:
            current_meta = storage.get_session_meta(session_id)
            if current_meta and current_meta.status not in (
                SessionStatus.RUNNING, SessionStatus.PENDING
            ):
                return True
        except Exception:
            pass
        return False

    return make_sse_response(
        sse_generate_events(request, storage, session_id, cursor, poll_interval_ms, check_session_idle_timeout)
    )

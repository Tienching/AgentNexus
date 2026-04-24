# -*- coding: utf-8 -*-
"""Realtime control-plane events and activity read models."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from src.core.events.activity import get_recent_activities
from ..services import get_event_bus
from ..services.domain_events import query_domain_events
from .nexus_auth import verify_nexus_auth

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-events"],
    dependencies=[Depends(verify_nexus_auth)],
)


@router.get("/events")
async def list_domain_events(
    aggregate_type: Optional[str] = None,
    aggregate_id: Optional[str] = None,
    event_type: Optional[str] = None,
    workspace_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    session_id: Optional[str] = None,
    runtime_id: Optional[str] = None,
    task_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    items = [
        evt.to_dict()
        for evt in query_domain_events(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            session_id=session_id,
            runtime_id=runtime_id,
            task_id=task_id,
            limit=limit,
            offset=offset,
        )
    ]
    return {"items": items, "count": len(items), "offset": offset, "limit": limit}


@router.get("/activities")
async def list_activities(
    entity_type: Optional[str] = None,
    activity_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
):
    items = [activity.to_dict() for activity in get_recent_activities(limit=limit, entity_type=entity_type, activity_type=activity_type)]
    return {"items": items, "count": len(items), "limit": limit}


@router.get("/events/stream")
async def stream_control_plane_events(
    request: Request,
    include_history: bool = Query(True, description="Replay recent items before subscribing"),
    history_limit: int = Query(50, ge=1, le=200),
):
    event_bus = get_event_bus()

    async def _gen():
        queue = event_bus.subscribe(maxsize=256)
        try:
            if include_history:
                for evt in reversed(query_domain_events(limit=history_limit)):
                    payload = {"source": "domain_event", **evt.to_dict()}
                    yield f"event: domain_event.created\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                for activity in reversed(get_recent_activities(limit=history_limit)):
                    payload = {"source": "activity", **activity.to_dict()}
                    yield f"event: activity.created\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

            last_heartbeat = 0.0
            while True:
                if await request.is_disconnected():
                    break
                now = time.time()
                if now - last_heartbeat >= 15:
                    last_heartbeat = now
                    yield ": heartbeat\n\n"
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                payload = envelope.to_dict()
                yield f"event: {payload['event_type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

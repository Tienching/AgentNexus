# -*- coding: utf-8 -*-
"""Daemon WebSocket channel.

Low-latency companion to the HTTP daemon API: a connected daemon (or the board
client) keeps a WS open at ``/api/daemon/ws`` to receive task-ready wakeups and
heartbeat acks without polling. Mirrors multica's dual-transport design (HTTP
for the durable control plane, WS for fast signals).

Frames (JSON, one per message):
  INBOUND  (daemon -> server):
    {"type": "heartbeat", "daemon_id": "...", "workspace": "...", "provider": "..."}
  OUTBOUND (server -> daemon / board):
    {"type": "heartbeat_ack", "daemon_id": "...", "ok": true}
    {"type": "task_available", "workspace": "...", "runtime_id": "..."}

Auth: the bearer token (NEXUS_AUTH_TOKEN) if configured, sent as a query param
(browsers cannot set WS upgrade headers).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from ..config import settings
from ..services.agent_runtimes import get_runtime_daemon_registry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["daemon-ws"])


class DaemonConnectionHub:
    """Tracks live daemon + board WebSocket connections for fan-out."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)

    async def broadcast(self, frame: Dict[str, Any]) -> None:
        """Send a frame to all connected clients (board + daemons)."""
        text = json.dumps(frame, ensure_ascii=False)
        dead: list[WebSocket] = []
        async with self._lock:
            targets = list(self._connections)
        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)


_hub = DaemonConnectionHub()


def get_daemon_hub() -> DaemonConnectionHub:
    return _hub


def _authorized(token: str | None) -> bool:
    expected = getattr(settings, "nexus_password", "") or ""
    if not expected:
        return True  # auth not configured
    return bool(token) and token == expected


@router.websocket("/api/daemon/ws")
async def daemon_ws(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    """Daemon / board WebSocket.

    A daemon connects after HTTP-registering; it sends periodic heartbeat
    frames and receives acks + task-available wakeups.
    """
    if not _authorized(token):
        await websocket.close(code=4401)
        return

    await _hub.connect(websocket)
    logger.info("daemon WS connected")
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                frame = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            ftype = str(frame.get("type") or "").lower()
            if ftype == "heartbeat":
                daemon_id = str(frame.get("daemon_id") or "")
                workspace = str(frame.get("workspace") or "default")
                provider = frame.get("provider")
                if daemon_id:
                    reg = get_runtime_daemon_registry()
                    reg.record_daemon_heartbeat(
                        daemon_id,
                        status=frame.get("status"),
                        workspace=workspace,
                        provider=provider,
                    )
                await websocket.send_text(
                    json.dumps({"type": "heartbeat_ack", "daemon_id": daemon_id, "ok": True})
                )
            # other inbound frame types can be added here
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("daemon WS error", exc_info=True)
    finally:
        await _hub.disconnect(websocket)
        logger.info("daemon WS disconnected")

# -*- coding: utf-8 -*-
"""TeleportSessionManager — manages remote session lifecycle.

Handles session creation, reconnection, heartbeat updates, and
graceful teardown for teleport sessions.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ...server.logger import get_logger
from ...server.services.teleport_bridge import TeleportBridge, TeleportSession

logger = get_logger(__name__)


class TeleportSessionManager:
    """Manages the lifecycle of teleport sessions.

    Provides convenience methods for session orchestration on top
    of the core TeleportBridge, including auto-reconnection and
    session health monitoring.
    """

    def __init__(self, bridge: TeleportBridge | None = None):
        self._bridge = bridge or TeleportBridge.get_instance()
        self._reconnect_tasks: dict[str, asyncio.Task] = {}

    # ── Connection Management ────────────────────────────────────

    async def create_session(
        self,
        remote_url: str,
        credentials: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        auto_reconnect: bool = True,
    ) -> TeleportSession:
        """Create a new teleport session with optional auto-reconnect."""
        session = await self._bridge.connect(remote_url, credentials, metadata)

        if auto_reconnect and session.status == "connected":
            self._start_reconnect_watcher(session.id)

        return session

    async def close_session(self, session_id: str) -> bool:
        """Close a teleport session and stop its reconnect watcher."""
        # Stop reconnect watcher
        task = self._reconnect_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        return await self._bridge.disconnect(session_id)

    # ── Auto-Reconnect ──────────────────────────────────────────

    def _start_reconnect_watcher(self, session_id: str) -> None:
        """Start a background task that monitors and reconnects a session."""
        if session_id in self._reconnect_tasks:
            return
        self._reconnect_tasks[session_id] = asyncio.create_task(
            self._reconnect_loop(session_id)
        )

    async def _reconnect_loop(self, session_id: str) -> None:
        """Periodically check session health and attempt reconnection."""
        try:
            while True:
                await asyncio.sleep(30)
                session = self._bridge.get_session(session_id)
                if not session:
                    break
                if session.status == "error":
                    logger.info(f"Attempting reconnect for session {session_id}")
                    try:
                        new_session = await self._bridge.connect(
                            session.remote_url,
                            self._bridge._get_credentials(session_id),
                            session.metadata,
                        )
                        if new_session.status == "connected":
                            logger.info(f"Reconnected session {session_id}")
                    except Exception as exc:
                        logger.warning(f"Reconnect failed for {session_id}: {exc}")
        except asyncio.CancelledError:
            pass

    # ── Health & Status ──────────────────────────────────────────

    def get_session_health(self, session_id: str) -> dict[str, Any]:
        """Get health information for a teleport session."""
        session = self._bridge.get_session(session_id)
        if not session:
            return {"session_id": session_id, "status": "not_found"}

        now = time.time()
        uptime = now - session.connected_at if session.status == "connected" else 0
        stale_seconds = now - session.last_heartbeat if session.status == "connected" else 0

        return {
            "session_id": session_id,
            "status": session.status,
            "remote_url": session.remote_url,
            "uptime_seconds": uptime,
            "stale_seconds": stale_seconds,
            "has_reconnect_watcher": session_id in self._reconnect_tasks,
        }

    def list_active_sessions(self) -> list[TeleportSession]:
        """List sessions that are currently connected."""
        return [s for s in self._bridge.list_sessions() if s.status == "connected"]

    # ── Cleanup ──────────────────────────────────────────────────

    async def cleanup(self) -> None:
        """Stop all reconnect watchers and clean up."""
        for session_id, task in list(self._reconnect_tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._reconnect_tasks.clear()

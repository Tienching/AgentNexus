# -*- coding: utf-8 -*-
"""StateSynchronizer — bidirectional state synchronization for teleport sessions.

Handles syncing task results, file artifacts, and configuration between
the local agent-nexus instance and a remote execution environment.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ...server.logger import get_logger
from ...server.services.teleport_bridge import TeleportBridge, SyncResult

logger = get_logger(__name__)

SYNC_BATCH_SIZE = 50  # max items per sync request


class StateSynchronizer:
    """Bidirectional state synchronizer for teleport sessions.

    Coordinates push/pull of state between local and remote environments:
    - Push: send local task results and artifacts to remote
    - Pull: fetch remote task results and artifacts to local
    - Conflict resolution: detect and report divergent state
    """

    def __init__(self, bridge: TeleportBridge | None = None):
        self._bridge = bridge or TeleportBridge.get_instance()
        self._http_client: httpx.AsyncClient | None = None

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    # ── Full Sync (delegates to bridge) ──────────────────────────

    async def sync(self, session_id: str) -> SyncResult:
        """Perform a full bidirectional sync with the remote environment."""
        return await self._bridge.sync_state(session_id)

    # ── Push ─────────────────────────────────────────────────────

    async def push_results(
        self,
        session_id: str,
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Push local task results to the remote environment."""
        session = self._bridge.get_session(session_id)
        if not session or session.status != "connected":
            return {"pushed": 0, "error": "session not available"}

        credentials = self._bridge._get_credentials(session_id)
        headers = self._bridge._build_auth_headers(credentials)
        headers["Content-Type"] = "application/json"

        push_url = f"{session.remote_url.rstrip('/')}/api/nexus/teleport/sync/push"
        client = self._get_http_client()

        pushed = 0
        errors: list[str] = []

        # Batch push
        for i in range(0, len(results), SYNC_BATCH_SIZE):
            batch = results[i : i + SYNC_BATCH_SIZE]
            try:
                resp = await client.post(
                    push_url,
                    json={"results": batch, "source": "teleport-push"},
                    headers=headers,
                )
                resp.raise_for_status()
                pushed += len(batch)
            except httpx.HTTPError as exc:
                errors.append(f"Batch {i}: {exc}")

        session.last_heartbeat = asyncio.get_event_loop().time()

        return {"pushed": pushed, "errors": errors}

    # ── Pull ─────────────────────────────────────────────────────

    async def pull_results(
        self,
        session_id: str,
        since_timestamp: float | None = None,
    ) -> dict[str, Any]:
        """Pull remote task results to the local environment."""
        session = self._bridge.get_session(session_id)
        if not session or session.status != "connected":
            return {"pulled": 0, "error": "session not available"}

        credentials = self._bridge._get_credentials(session_id)
        headers = self._bridge._build_auth_headers(headers=credentials)

        pull_url = f"{session.remote_url.rstrip('/')}/api/nexus/teleport/sync/pull"
        params: dict[str, Any] = {}
        if since_timestamp:
            params["since"] = since_timestamp

        client = self._get_http_client()
        try:
            resp = await client.get(pull_url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            return {"pulled": len(results), "results": results}
        except httpx.HTTPError as exc:
            logger.error(f"Pull failed for session {session_id}: {exc}")
            return {"pulled": 0, "error": str(exc)}

    # ── Conflict Detection ───────────────────────────────────────

    def detect_conflicts(
        self,
        local_state: dict[str, Any],
        remote_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Detect conflicts between local and remote state.

        Compares task IDs and their statuses/timestamps to find
        divergent entries that require manual resolution.
        """
        conflicts: list[dict[str, Any]] = []

        local_tasks = {t["id"]: t for t in local_state.get("tasks", [])}
        remote_tasks = {t["id"]: t for t in remote_state.get("tasks", [])}

        # Tasks present in both but with different status
        for task_id in set(local_tasks) & set(remote_tasks):
            local = local_tasks[task_id]
            remote = remote_tasks[task_id]
            if local.get("status") != remote.get("status"):
                conflicts.append({
                    "type": "status_mismatch",
                    "task_id": task_id,
                    "local_status": local.get("status"),
                    "remote_status": remote.get("status"),
                    "local_updated": local.get("updated_at"),
                    "remote_updated": remote.get("updated_at"),
                })

        # Tasks only in one side
        for task_id in set(local_tasks) - set(remote_tasks):
            conflicts.append({
                "type": "local_only",
                "task_id": task_id,
                "local_status": local_tasks[task_id].get("status"),
            })

        for task_id in set(remote_tasks) - set(local_tasks):
            conflicts.append({
                "type": "remote_only",
                "task_id": task_id,
                "remote_status": remote_tasks[task_id].get("status"),
            })

        return conflicts

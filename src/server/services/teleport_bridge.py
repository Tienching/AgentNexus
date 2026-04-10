# -*- coding: utf-8 -*-
"""Teleport Bridge Service — bridges local Agent sessions with remote execution environments.

Provides session management, remote task execution, output streaming, and
bidirectional state synchronization between a local agent-nexus instance and
one or more remote endpoints.

Usage::

    bridge = TeleportBridge.get_instance()
    session = await bridge.connect("https://remote-host:8080", credentials={"token": "..."})
    result = await bridge.execute_remote(session.id, "run tests")
    async for chunk in bridge.stream_output(session.id):
        print(chunk)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import httpx

from ..logger import get_logger

logger = get_logger(__name__)


# ── Data Models ──────────────────────────────────────────────────────


@dataclass
class TeleportSession:
    """Represents an active connection to a remote execution environment."""

    id: str
    remote_url: str
    status: str  # "connected" | "disconnected" | "error"
    connected_at: float
    last_heartbeat: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "remote_url": self.remote_url,
            "status": self.status,
            "connected_at": self.connected_at,
            "last_heartbeat": self.last_heartbeat,
            "metadata": self.metadata,
        }


@dataclass
class RemoteResult:
    """Result of a remote task execution."""

    session_id: str
    task_id: str
    status: str  # "pending" | "running" | "completed" | "failed"
    output: str = ""
    exit_code: int | None = None
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "status": self.status,
            "output": self.output,
            "exit_code": self.exit_code,
            "artifacts": self.artifacts,
        }


@dataclass
class SyncResult:
    """Result of a state synchronization operation."""

    session_id: str
    synced_tasks: int = 0
    synced_files: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "synced_tasks": self.synced_tasks,
            "synced_files": self.synced_files,
            "conflicts": self.conflicts,
        }


# ── Heartbeat Configuration ─────────────────────────────────────────

HEARTBEAT_INTERVAL = 30.0  # seconds between heartbeat checks
HEARTBEAT_TIMEOUT = 90.0  # seconds before a session is considered stale
HTTP_TIMEOUT = 30.0  # seconds for outbound HTTP requests


# ── TeleportBridge ──────────────────────────────────────────────────


class TeleportBridge:
    """Singleton bridge that manages remote teleport sessions.

    Connects to remote agent-nexus instances (or compatible endpoints),
    dispatches tasks, streams output, and synchronizes state.
    """

    _instance: TeleportBridge | None = None

    @classmethod
    def get_instance(cls) -> TeleportBridge:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def __init__(self) -> None:
        self._sessions: dict[str, TeleportSession] = {}
        self._results: dict[str, RemoteResult] = {}  # task_id -> result
        self._output_buffers: dict[str, list[str]] = {}  # session_id -> output lines
        self._output_events: dict[str, asyncio.Event] = {}  # session_id -> new-output signal
        self._heartbeat_task: asyncio.Task | None = None
        self._http_client: httpx.AsyncClient | None = None

    # ── HTTP Client ──────────────────────────────────────────────

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
        return self._http_client

    async def _close_http_client(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    # ── Heartbeat ────────────────────────────────────────────────

    async def start_heartbeat(self) -> None:
        """Start the background heartbeat monitor."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop_heartbeat(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                now = time.time()
                for session in list(self._sessions.values()):
                    if session.status != "connected":
                        continue
                    if now - session.last_heartbeat > HEARTBEAT_TIMEOUT:
                        logger.warning(
                            f"Session {session.id} heartbeat timeout, marking as error"
                        )
                        session.status = "error"
                        session.metadata["error"] = "heartbeat_timeout"
        except asyncio.CancelledError:
            pass

    # ── Session Management ───────────────────────────────────────

    async def connect(
        self,
        remote_url: str,
        credentials: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TeleportSession:
        """Connect to a remote execution environment.

        Validates connectivity by sending a lightweight health check
        to the remote endpoint, then registers the session locally.
        """
        session_id = uuid.uuid4().hex[:16]
        now = time.time()

        credentials = credentials or {}
        metadata = metadata or {}

        # Validate connectivity
        client = self._get_http_client()
        headers = self._build_auth_headers(credentials)
        health_url = f"{remote_url.rstrip('/')}/api/health"

        try:
            resp = await client.get(health_url, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(f"Teleport connect failed for {remote_url}: {exc}")
            session = TeleportSession(
                id=session_id,
                remote_url=remote_url,
                status="error",
                connected_at=now,
                last_heartbeat=now,
                metadata={**metadata, "error": str(exc)},
            )
            self._sessions[session_id] = session
            return session

        # Store credentials securely (not in metadata that gets serialized to responses)
        metadata["_credentials_keys"] = list(credentials.keys())

        session = TeleportSession(
            id=session_id,
            remote_url=remote_url,
            status="connected",
            connected_at=now,
            last_heartbeat=now,
            metadata=metadata,
        )
        self._sessions[session_id] = session
        self._output_buffers[session_id] = []
        self._output_events[session_id] = asyncio.Event()

        # Store credentials in a separate internal dict (not exposed in to_dict)
        if not hasattr(self, "_credentials"):
            self._credentials: dict[str, dict[str, Any]] = {}
        self._credentials[session_id] = credentials

        # Ensure heartbeat is running
        await self.start_heartbeat()

        logger.info(f"Teleport session connected: {session_id} -> {remote_url}")
        return session

    async def disconnect(self, session_id: str) -> bool:
        """Disconnect a remote session."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        session.status = "disconnected"

        # Signal any pending stream consumers
        event = self._output_events.get(session_id)
        if event:
            event.set()

        # Clean up credentials
        creds = getattr(self, "_credentials", {})
        creds.pop(session_id, None)

        logger.info(f"Teleport session disconnected: {session_id}")
        return True

    def _build_auth_headers(self, credentials: dict[str, Any]) -> dict[str, str]:
        """Build HTTP headers from credentials dict."""
        headers: dict[str, str] = {}
        if "token" in credentials:
            headers["Authorization"] = f"Bearer {credentials['token']}"
        if "api_key" in credentials:
            headers["X-API-Key"] = credentials["api_key"]
        # Allow arbitrary header passthrough
        for key in credentials:
            if key.startswith("header_"):
                header_name = key[7:]  # strip "header_" prefix
                headers[header_name] = credentials[key]
        return headers

    def _get_credentials(self, session_id: str) -> dict[str, Any]:
        """Retrieve stored credentials for a session."""
        creds = getattr(self, "_credentials", {})
        return creds.get(session_id, {})

    # ── Remote Execution ─────────────────────────────────────────

    async def execute_remote(
        self,
        session_id: str,
        task: str,
        task_metadata: dict[str, Any] | None = None,
    ) -> RemoteResult:
        """Execute a task on the remote environment.

        Dispatches the task via HTTP to the remote endpoint's chat API
        and records the result.
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if session.status != "connected":
            raise ValueError(f"Session {session_id} is not connected (status={session.status})")

        task_id = uuid.uuid4().hex[:16]
        result = RemoteResult(
            session_id=session_id,
            task_id=task_id,
            status="pending",
        )
        self._results[task_id] = result

        credentials = self._get_credentials(session_id)
        headers = self._build_auth_headers(credentials)
        headers["Content-Type"] = "application/json"

        execute_url = f"{session.remote_url.rstrip('/')}/api/chat"
        payload = {
            "content": task,
            "session_id": session_id,
            "metadata": task_metadata or {},
        }

        result.status = "running"

        client = self._get_http_client()
        try:
            resp = await client.post(execute_url, json=payload, headers=headers)
            resp.raise_for_status()

            # Parse SSE or JSON response
            output_text = resp.text
            result.output = output_text
            result.status = "completed"
            result.exit_code = 0

            # Append to output buffer for streaming consumers
            self._append_output(session_id, output_text)

        except httpx.HTTPError as exc:
            result.status = "failed"
            result.output = str(exc)
            result.exit_code = 1
            logger.error(f"Remote execution failed for session {session_id}: {exc}")

        # Update heartbeat
        session.last_heartbeat = time.time()

        return result

    async def execute_remote_streaming(
        self,
        session_id: str,
        task: str,
        task_metadata: dict[str, Any] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Execute a task on the remote environment with streaming output.

        Yields SSE-style chunks as they arrive from the remote endpoint.
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if session.status != "connected":
            raise ValueError(f"Session {session_id} is not connected (status={session.status})")

        task_id = uuid.uuid4().hex[:16]
        result = RemoteResult(
            session_id=session_id,
            task_id=task_id,
            status="running",
        )
        self._results[task_id] = result

        credentials = self._get_credentials(session_id)
        headers = self._build_auth_headers(credentials)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "text/event-stream"

        execute_url = f"{session.remote_url.rstrip('/')}/api/chat"
        payload = {
            "content": task,
            "session_id": session_id,
            "metadata": task_metadata or {},
        }

        full_output_parts: list[str] = []

        client = self._get_http_client()
        try:
            async with client.stream(
                "POST", execute_url, json=payload, headers=headers
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        chunk = line[5:].strip()
                        if chunk and chunk != "[DONE]":
                            full_output_parts.append(chunk)
                            self._append_output(session_id, chunk)
                            yield chunk

            result.output = "\n".join(full_output_parts)
            result.status = "completed"
            result.exit_code = 0

        except httpx.HTTPError as exc:
            error_msg = str(exc)
            result.status = "failed"
            result.output = error_msg
            result.exit_code = 1
            self._append_output(session_id, f"[ERROR] {error_msg}")
            yield f'[ERROR] {error_msg}'

        session.last_heartbeat = time.time()

    # ── State Synchronization ────────────────────────────────────

    async def sync_state(self, session_id: str) -> SyncResult:
        """Synchronize state with the remote environment.

        Fetches remote task list and artifact manifest, then computes
        a diff against local state.
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if session.status != "connected":
            raise ValueError(f"Session {session_id} is not connected (status={session.status})")

        credentials = self._get_credentials(session_id)
        headers = self._build_auth_headers(credentials)

        sync_url = f"{session.remote_url.rstrip('/')}/api/nexus/sessions"
        client = self._get_http_client()

        try:
            resp = await client.get(sync_url, headers=headers)
            resp.raise_for_status()
            remote_data = resp.json()
        except httpx.HTTPError as exc:
            logger.error(f"Sync failed for session {session_id}: {exc}")
            return SyncResult(
                session_id=session_id,
                synced_tasks=0,
                synced_files=[],
                conflicts=[{"error": str(exc)}],
            )

        # Parse remote sessions/tasks
        sessions_list = remote_data if isinstance(remote_data, list) else remote_data.get("sessions", [])
        synced_tasks = len(sessions_list)

        # Build synced files from remote artifacts
        synced_files: list[str] = []
        for sess in sessions_list:
            artifacts = sess.get("artifacts", [])
            synced_files.extend(artifacts)

        # Detect conflicts (placeholder — in production, compare timestamps/hashes)
        conflicts: list[dict[str, Any]] = []

        session.last_heartbeat = time.time()

        result = SyncResult(
            session_id=session_id,
            synced_tasks=synced_tasks,
            synced_files=synced_files,
            conflicts=conflicts,
        )
        return result

    # ── Output Streaming ─────────────────────────────────────────

    def _append_output(self, session_id: str, data: str) -> None:
        """Append output data to a session's buffer and signal consumers."""
        buf = self._output_buffers.get(session_id)
        if buf is not None:
            buf.append(data)
        event = self._output_events.get(session_id)
        if event:
            event.set()

    async def stream_output(self, session_id: str) -> AsyncGenerator[str, None]:
        """Stream output from a remote session in real-time.

        Yields new output chunks as they become available.
        Ends when the session disconnects or errors.
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        buf = self._output_buffers.setdefault(session_id, [])
        event = self._output_events.setdefault(session_id, asyncio.Event())
        cursor = 0

        while session.status == "connected":
            # Yield any buffered output since our cursor
            while cursor < len(buf):
                yield buf[cursor]
                cursor += 1

            # Wait for new output
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                # Periodic check — session might have been disconnected
                continue

        # Drain remaining buffer
        while cursor < len(buf):
            yield buf[cursor]
            cursor += 1

    # ── Query Methods ────────────────────────────────────────────

    def list_sessions(self) -> list[TeleportSession]:
        """List all teleport sessions."""
        return list(self._sessions.values())

    def get_session(self, session_id: str) -> TeleportSession | None:
        """Get a specific teleport session."""
        return self._sessions.get(session_id)

    def get_result(self, task_id: str) -> RemoteResult | None:
        """Get a remote execution result."""
        return self._results.get(task_id)

    # ── Cleanup ──────────────────────────────────────────────────

    async def cleanup(self) -> None:
        """Stop heartbeat and close HTTP client."""
        await self.stop_heartbeat()
        await self._close_http_client()

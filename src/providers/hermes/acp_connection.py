# -*- coding: utf-8 -*-
"""ACP (Agent Client Protocol) stdio JSON-RPC client for hermes.

Framing: **NDJSON** (one JSON-RPC message per line) — confirmed by probing
``hermes acp``. This mirrors the codex MCP connection skeleton (Future map +
event queue + lifecycle) but uses newline-delimited framing instead of
Content-Length.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

logger = logging.getLogger(__name__)


class ACPError(RuntimeError):
    pass


class HermesACPConnection:
    """Manages the ``hermes acp`` subprocess and JSON-RPC protocol."""

    def __init__(self, cmd: list, cwd: Optional[str] = None, env: Optional[dict] = None):
        self._cmd = cmd
        self._cwd = cwd
        self._env = env
        self._process: Optional[asyncio.subprocess.Process] = None
        self._read_task: Optional[asyncio.Task] = None
        self._next_id = 1
        self._pending: Dict[int, asyncio.Future] = {}
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._process = await asyncio.create_subprocess_exec(
            *self._cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            env=self._env,
            limit=10 * 1024 * 1024,
        )
        self._read_task = asyncio.create_task(self._read_loop())
        self._started = True

    async def _read_loop(self) -> None:
        """Read NDJSON lines from stdout and dispatch."""
        try:
            assert self._process and self._process.stdout
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode())
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    logger.warning("acp: unparseable line: %s", exc)
                    continue
                self._handle_message(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("acp read loop ended: %s", exc)
        finally:
            # Signal end-of-stream to consumers. Use put_nowait so the sentinel
            # can never block this finally block (an awaited put() would hang if
            # the queue is full and the consumer is gone). If the bounded queue
            # is full, drop the oldest buffered notification to make room: the
            # terminal sentinel MUST reach the consumer, otherwise read_events()
            # would block forever waiting for a None that never arrives.
            try:
                self._event_queue.put_nowait(None)
            except asyncio.QueueFull:
                try:
                    self._event_queue.get_nowait()  # drop oldest non-terminal event
                except asyncio.QueueEmpty:
                    pass
                self._event_queue.put_nowait(None)

    def _handle_message(self, msg: dict) -> None:
        # Response to a request (has id + result/error)
        if "id" in msg and ("result" in msg or "error" in msg):
            fut = self._pending.pop(msg["id"], None)
            if fut is not None and not fut.done():
                if "error" in msg:
                    fut.set_exception(ACPError(f"RPC error {msg['error']}"))
                else:
                    fut.set_result(msg.get("result"))
            return
        # Notification (has method) → enqueue for consumers
        if "method" in msg:
            try:
                self._event_queue.put_nowait(msg)
            except asyncio.QueueFull:
                logger.warning("acp: event queue full, dropping notification")

    async def request(self, method: str, params: Optional[dict] = None, timeout: float = 30.0) -> Any:
        """Send a JSON-RPC request and await its response."""
        if not self._process or not self._process.stdin:
            raise ACPError("connection not started")
        req_id = self._next_id
        self._next_id += 1
        req = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            req["params"] = params
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[req_id] = fut
        line = (json.dumps(req) + "\n").encode()
        self._process.stdin.write(line)
        await self._process.stdin.drain()
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise ACPError(f"timeout waiting for response to {method}")

    async def notify(self, method: str, params: Optional[dict] = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or not self._process.stdin:
            raise ACPError("connection not started")
        notif = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            notif["params"] = params
        line = (json.dumps(notif) + "\n").encode()
        self._process.stdin.write(line)
        await self._process.stdin.drain()

    async def read_events(self) -> AsyncIterator[Optional[dict]]:
        """Yield notifications until the stream ends (None sentinel)."""
        while True:
            ev = await self.next_event()
            yield ev
            if ev is None:
                return

    async def next_event(self) -> Optional[dict]:
        """Return the next ACP notification, or None when stdout closes."""
        return await self._event_queue.get()

    # ── ACP protocol convenience methods ──────────────────────────────
    async def initialize(self) -> dict:
        return await self.request(
            "initialize",
            {"protocolVersion": 1, "capabilities": {}, "clientInfo": {"name": "nexus", "version": "1.0"}},
        )

    async def initialized(self) -> None:
        await self.notify("notifications/initialized")

    async def new_session(self, cwd: str) -> dict:
        return await self.request("session/new", {"cwd": cwd, "mcpServers": []}, timeout=30.0)

    async def prompt(self, session_id: str, text: str) -> dict:
        return await self.request(
            "session/prompt",
            {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
            timeout=600.0,
        )

    async def cancel(self, session_id: str, reason: str = "client cancelled") -> None:
        try:
            await self.request("session/cancel", {"sessionId": session_id, "reason": reason}, timeout=10.0)
        except Exception:
            pass

    async def drain_stderr(self) -> str:
        if not self._process or not self._process.stderr:
            return ""
        try:
            data = await asyncio.wait_for(self._process.stderr.read(4000), timeout=1.0)
            return data.decode("utf-8", errors="replace")
        except Exception:
            return ""

    async def stop(self) -> None:
        """Terminate the subprocess and reject all pending requests."""
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(ACPError("connection closed"))
        self._pending.clear()
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=3.0)
            except (asyncio.TimeoutError, ProcessLookupError, Exception):
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
        self._started = False

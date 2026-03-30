# -*- coding: utf-8 -*-
"""Persistent CLI process manager — long-lived subprocess with stdin/stdout pipes.

Instead of spawning a new subprocess for every chat message (the default
``CLIExecutor`` behaviour), this module keeps a single CLI process alive
per session and sends/receives messages via ``--input-format stream-json``
and ``--output-format stream-json``.

Key benefits:
    - No context reload overhead: the CLI process retains its full
      conversation history natively.
    - Faster first-token latency for follow-up messages.
    - Cleaner session semantics for agent-mode / long conversations.

Limitations:
    - Only works with providers that support ``--input-format stream-json``
      (currently: Claude, CodeBuddy).  Others fall back to the subprocess
      model automatically.
    - One process per session means sequential message processing only
      (enforced by an asyncio Lock).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    AsyncGenerator,
    Dict,
    Optional,
)

from .completion_detector import CompletionDetector, CompletionStatus

logger = logging.getLogger(__name__)

# Providers that support --input-format stream-json
_STREAM_INPUT_PROVIDERS = frozenset({"claude", "codebuddy"})


@dataclass
class PersistentProcess:
    """A long-lived CLI subprocess attached to a specific session.

    Do **not** instantiate directly; use
    ``PersistentProcessManager.get_or_create()`` instead.
    """

    session_id: str
    exec_user: str
    provider: str
    process: asyncio.subprocess.Process
    detector: CompletionDetector
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _init_received: bool = False
    _cli_session_id: Optional[str] = None

    @property
    def alive(self) -> bool:
        return self.process.returncode is None

    @property
    def cli_session_id(self) -> Optional[str]:
        """CLI-internal session UUID (extracted from init/result events)."""
        return self._cli_session_id or self.detector.session_id

    async def wait_for_init(self, timeout: float = 60.0) -> Optional[Dict[str, Any]]:
        """Wait for the ``{"type": "system", "subtype": "init", ...}`` event.

        Returns the parsed init dict, or ``None`` on timeout.
        """
        if self._init_received:
            return None

        try:
            line = await asyncio.wait_for(
                self.process.stdout.readline(),
                timeout=timeout,
            )
            if not line:
                return None
            data = json.loads(line.decode("utf-8").strip())
            if data.get("type") == "system" and data.get("subtype") == "init":
                self._init_received = True
                sid = data.get("session_id")
                if sid:
                    self._cli_session_id = sid
                logger.info(
                    "Persistent process init received",
                    extra={
                        "session_id": self.session_id,
                        "cli_session_id": sid,
                        "provider": self.provider,
                    },
                )
                return data
            # Not an init event — could be an error
            logger.warning(
                "Expected init event, got: %s",
                str(data)[:200],
            )
            return data
        except asyncio.TimeoutError:
            logger.error(
                "Timeout waiting for persistent process init (%ss)",
                timeout,
                extra={"session_id": self.session_id},
            )
            return None
        except Exception as e:
            logger.error("Error reading init event: %s", e, exc_info=True)
            return None

    async def send_message(self, content: str) -> None:
        """Send a user message to the CLI process via stdin.

        The message is formatted as a stream-json ``user`` event::

            {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "..."}]}}

        Args:
            content: Plain-text user message.

        Raises:
            RuntimeError: If the process has exited.
        """
        if not self.alive:
            raise RuntimeError(
                f"Persistent process for session {self.session_id} is not alive"
            )

        msg = json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": content}],
            },
        }) + "\n"

        self.process.stdin.write(msg.encode("utf-8"))
        await self.process.stdin.drain()
        self.last_activity = time.time()

        logger.info(
            "Sent message to persistent process",
            extra={
                "session_id": self.session_id,
                "content_length": len(content),
                "provider": self.provider,
            },
        )

    async def stream_output(
        self,
        timeout: float = 300.0,
        quiescence_timeout: Optional[float] = None,
    ) -> AsyncGenerator[str, None]:
        """Read output lines from stdout until turn completion.

        Yields raw JSON lines (compatible with ``CLIExecutor._process_stream``).
        Stops when:
            - A ``{"type": "result"}`` event is detected.
            - No output for ``quiescence_timeout`` seconds (fallback).
            - The overall ``timeout`` is exceeded.
            - The process exits unexpectedly.

        Args:
            timeout: Maximum wall-clock seconds for the entire turn.
            quiescence_timeout: Override the detector's quiescence timeout.
        """
        if quiescence_timeout is not None:
            self.detector.quiescence_timeout = quiescence_timeout

        self.detector.reset()
        deadline = time.time() + timeout
        last_output_time = time.time()

        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                logger.warning(
                    "Turn timeout (%ss) for session %s",
                    timeout,
                    self.session_id,
                )
                break

            # Use whichever is shorter: remaining deadline or quiescence
            read_timeout = min(remaining, self.detector.quiescence_timeout)

            try:
                line = await asyncio.wait_for(
                    self.process.stdout.readline(),
                    timeout=read_timeout,
                )
            except asyncio.TimeoutError:
                # Check quiescence
                idle = time.time() - last_output_time
                if idle >= self.detector.quiescence_timeout:
                    logger.info(
                        "Quiescence timeout (%ss) — assuming turn complete",
                        self.detector.quiescence_timeout,
                        extra={"session_id": self.session_id},
                    )
                    break
                continue

            if not line:
                # Process closed stdout (likely exited)
                logger.warning(
                    "Persistent process stdout closed",
                    extra={"session_id": self.session_id},
                )
                break

            raw = line.decode("utf-8").strip()
            if not raw:
                continue

            last_output_time = time.time()
            self.last_activity = last_output_time

            # Check for turn completion
            status = self.detector.check_line(raw)

            # Update CLI session ID if newly discovered
            if self.detector.session_id and not self._cli_session_id:
                self._cli_session_id = self.detector.session_id

            yield raw

            if status in (CompletionStatus.DONE, CompletionStatus.ERROR):
                break

    async def kill(self) -> None:
        """Terminate the persistent process."""
        if self.alive:
            try:
                self.process.kill()
                await self.process.wait()
            except Exception as e:
                logger.warning("Error killing persistent process: %s", e)
        logger.info(
            "Persistent process killed",
            extra={
                "session_id": self.session_id,
                "provider": self.provider,
            },
        )


class PersistentProcessManager:
    """Manages long-lived CLI processes indexed by session ID.

    Thread-safe via asyncio locks.  Each session gets at most one
    persistent process; subsequent messages reuse the same process.

    Args:
        config: Server settings object (must have ``cli_timeout``,
            ``persistent_idle_timeout``, ``persistent_quiescence_timeout``
            attributes or sensible defaults are used).
    """

    def __init__(self, config: Any = None):
        self._processes: Dict[str, PersistentProcess] = {}
        self._lock = asyncio.Lock()
        self._config = config

        # Defaults
        self._idle_timeout: float = getattr(config, "persistent_idle_timeout", 1800.0)
        self._quiescence: float = getattr(config, "persistent_quiescence_timeout", 3.0)
        self._max_per_user: int = getattr(config, "persistent_max_sessions_per_user", 5)

    async def get_or_create(
        self,
        session_id: str,
        exec_user: str,
        provider: str,
        exec_dir: Path,
        model: Optional[str] = None,
        alias: Optional[str] = None,
    ) -> PersistentProcess:
        """Get an existing persistent process or create a new one.

        Args:
            session_id: Runtime session ID.
            exec_user: Linux user to run the CLI as.
            provider: Provider name (claude, codebuddy, etc.).
            exec_dir: Working directory for the CLI process.
            model: Optional model name override.
            alias: Optional CLI command alias (e.g. ``claude-internal``).

        Returns:
            A ``PersistentProcess`` ready for ``send_message()``.

        Raises:
            RuntimeError: If the provider doesn't support persistent mode.
        """
        async with self._lock:
            # Reuse existing process if alive
            if session_id in self._processes:
                proc = self._processes[session_id]
                if proc.alive:
                    logger.info(
                        "Reusing persistent process for session %s",
                        session_id,
                    )
                    return proc
                else:
                    logger.info(
                        "Persistent process for session %s is dead, recreating",
                        session_id,
                    )
                    del self._processes[session_id]

            # Enforce per-user limit
            user_count = sum(
                1 for p in self._processes.values()
                if p.exec_user == exec_user and p.alive
            )
            if user_count >= self._max_per_user:
                # Kill oldest idle session for this user
                oldest = min(
                    (p for p in self._processes.values()
                     if p.exec_user == exec_user and p.alive),
                    key=lambda p: p.last_activity,
                )
                logger.info(
                    "Evicting oldest persistent process for user %s (session %s)",
                    exec_user,
                    oldest.session_id,
                )
                await oldest.kill()
                del self._processes[oldest.session_id]

            # Create new process
            proc = await self._create_process(
                session_id, exec_user, provider, exec_dir, model, alias,
            )
            self._processes[session_id] = proc
            return proc

    async def _create_process(
        self,
        session_id: str,
        exec_user: str,
        provider: str,
        exec_dir: Path,
        model: Optional[str] = None,
        alias: Optional[str] = None,
    ) -> PersistentProcess:
        """Spawn a new persistent CLI process."""
        cmd = self._build_persistent_cmd(provider, exec_dir, model, alias)

        # Determine if we need su wrapper
        current_user = os.environ.get("USER", "")
        if current_user == exec_user:
            full_cmd = " ".join(cmd)
            exec_cmd = ["bash", "-c", full_cmd]
        else:
            full_cmd = " ".join(cmd)
            exec_cmd = ["su", "-", exec_user, "-c", full_cmd]

        logger.info(
            "Creating persistent process",
            extra={
                "session_id": session_id,
                "exec_user": exec_user,
                "provider": provider,
                "exec_dir": str(exec_dir),
                "cmd": full_cmd,
            },
        )

        process = await asyncio.create_subprocess_exec(
            *exec_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(exec_dir),
            limit=10 * 1024 * 1024,
        )

        detector = CompletionDetector(quiescence_timeout=self._quiescence)

        proc = PersistentProcess(
            session_id=session_id,
            exec_user=exec_user,
            provider=provider,
            process=process,
            detector=detector,
        )

        # Wait for init event (non-blocking, with timeout)
        init_data = await proc.wait_for_init(timeout=60.0)
        if init_data is None and not proc.alive:
            # Process died during init — read stderr
            stderr = b""
            try:
                stderr = await proc.process.stderr.read()
            except Exception:
                pass
            raise RuntimeError(
                f"Persistent process died during init: {stderr.decode('utf-8', errors='ignore')[:500]}"
            )

        return proc

    def _build_persistent_cmd(
        self,
        provider: str,
        exec_dir: Path,
        model: Optional[str] = None,
        alias: Optional[str] = None,
    ) -> list:
        """Build the CLI command for a persistent (long-lived) process.

        Uses ``-p --input-format stream-json --output-format stream-json``
        which keeps the process alive and accepts messages via stdin.
        """
        cli_command = alias or provider or "claude"

        cmd = [cli_command]

        # -p mode is required for stream-json I/O
        cmd.append("-p")

        # Stream JSON for both input and output
        cmd.extend(["--input-format", "stream-json"])
        cmd.extend(["--output-format", "stream-json"])

        # Verbose output (required for stream-json as per CLI docs)
        cmd.append("--verbose")

        # Model override
        if model:
            cmd.extend(["--model", model])

        # Permission bypass (same as existing executor)
        if provider in ("claude", "codebuddy"):
            cmd.append("--dangerously-skip-permissions")
        elif provider == "codex":
            cmd.append("--dangerously-bypass-approvals-and-sandbox")

        return cmd

    async def destroy(self, session_id: str) -> None:
        """Kill and remove a persistent process by session ID."""
        async with self._lock:
            proc = self._processes.pop(session_id, None)
            if proc:
                await proc.kill()

    async def destroy_for_user(self, exec_user: str) -> int:
        """Kill all persistent processes for a given user.

        Returns the number of processes killed.
        """
        killed = 0
        async with self._lock:
            to_remove = [
                sid for sid, p in self._processes.items()
                if p.exec_user == exec_user
            ]
            for sid in to_remove:
                proc = self._processes.pop(sid)
                await proc.kill()
                killed += 1
        return killed

    async def cleanup_idle(self) -> int:
        """Kill processes that have been idle longer than ``_idle_timeout``.

        Intended to be called periodically (e.g. from a background task).
        Returns the number of processes cleaned up.
        """
        now = time.time()
        cleaned = 0
        async with self._lock:
            to_remove = [
                sid for sid, p in self._processes.items()
                if (now - p.last_activity) > self._idle_timeout or not p.alive
            ]
            for sid in to_remove:
                proc = self._processes.pop(sid)
                if proc.alive:
                    await proc.kill()
                cleaned += 1

        if cleaned:
            logger.info("Cleaned up %d idle persistent processes", cleaned)
        return cleaned

    async def shutdown(self) -> None:
        """Kill all persistent processes (called on server shutdown)."""
        async with self._lock:
            for proc in self._processes.values():
                if proc.alive:
                    await proc.kill()
            count = len(self._processes)
            self._processes.clear()
        if count:
            logger.info("Shut down %d persistent processes", count)

    @property
    def active_count(self) -> int:
        """Number of currently alive persistent processes."""
        return sum(1 for p in self._processes.values() if p.alive)

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get diagnostic info about a persistent process."""
        proc = self._processes.get(session_id)
        if not proc:
            return None
        return {
            "session_id": proc.session_id,
            "exec_user": proc.exec_user,
            "provider": proc.provider,
            "alive": proc.alive,
            "cli_session_id": proc.cli_session_id,
            "created_at": proc.created_at,
            "last_activity": proc.last_activity,
            "idle_seconds": time.time() - proc.last_activity,
        }

    @staticmethod
    def supports_persistent(provider: str) -> bool:
        """Check if a provider supports persistent process mode."""
        return (provider or "").strip().lower() in _STREAM_INPUT_PROVIDERS

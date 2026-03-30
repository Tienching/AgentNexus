# -*- coding: utf-8 -*-
"""Nexus Terminal WebSocket Router

Provides a WebSocket endpoint that bridges the browser (xterm.js) to a
tmux session via a PTY.  Auth is handled via a ``?token=`` query parameter
(browsers cannot send custom headers on WebSocket upgrade).

Protocol (JSON messages):
  Client → Server:
    {"type": "input", "data": "..."}      – keyboard input
    {"type": "resize", "cols": N, "rows": N}  – terminal resize
    {"type": "ping"}                       – keepalive

  Server → Client:
    {"type": "output", "data": "..."}      – terminal output (base64)
    {"type": "connected", "terminal_id": "..."}  – connection established
    {"type": "pong"}                       – keepalive response
    {"type": "error", "message": "..."}    – error
    {"type": "disconnected"}               – process ended
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from ..config import settings
from ..logger import get_logger
from ..services.session_storage import get_session_storage
from .nexus_auth import _is_auth_required, _validate_session

logger = get_logger(__name__)

router = APIRouter(tags=["nexus-terminal"])


def _get_terminal_manager():
    """Lazily retrieve the TerminalManager from app state (set in lifespan)."""
    from ..services.terminal_manager import TerminalManager
    # We use a module-level singleton as fallback
    if not hasattr(_get_terminal_manager, "_instance"):
        _get_terminal_manager._instance = TerminalManager()
    return _get_terminal_manager._instance


def set_terminal_manager(manager):
    """Called from app lifespan to inject the manager instance."""
    _get_terminal_manager._instance = manager


def _build_tmux_command(session_meta, storage) -> dict:
    """Build the tmux CLI command from session metadata.

    Returns dict with keys: tmux_cmd, tmux_session_name, cli_cmd, exec_dir, exec_user.
    Mirrors the logic in nexus_sessions.get_tmux_command().
    """
    session_id = session_meta.id

    # Resolve working directory
    exec_dir = session_meta.exec_dir or storage.get_exec_dir_override(session_id)
    if not exec_dir:
        home_base = settings.user_home_base
        exec_user = session_meta.exec_user or session_meta.username or settings.exec_user
        exec_dir = str(Path(home_base) / exec_user)

    exec_user = session_meta.exec_user or session_meta.username or settings.exec_user

    # Resolve provider / alias
    provider = session_meta.provider or "claude"
    alias = session_meta.alias or provider

    # Build CLI continue command
    cli_session_id = storage.get_cli_session_id(session_id)

    cli_parts = [alias]
    if provider in ("claude", "codebuddy"):
        if cli_session_id:
            cli_parts += ["--resume", cli_session_id]
        else:
            cli_parts.append("-c")
    elif provider == "gemini":
        cli_parts.append("--resume latest")
    elif provider == "codex":
        cli_parts += ["resume", "--last"]

    cli_cmd = " ".join(cli_parts)

    short_id = session_id[:12]
    tmux_session_name = f"nexus-{short_id}"

    return {
        "cli_cmd": cli_cmd,
        "tmux_session_name": tmux_session_name,
        "exec_dir": exec_dir,
        "exec_user": exec_user,
    }


@router.websocket("/api/nexus/terminal/{session_id}")
async def terminal_ws(
    websocket: WebSocket,
    session_id: str,
    token: Optional[str] = Query(None),
):
    """WebSocket endpoint: interactive terminal for a nexus session."""

    # --- Auth ---
    if _is_auth_required():
        # Try query param token first, then cookie from WebSocket headers
        auth_token = token
        if not auth_token:
            # WebSocket connections send cookies in headers
            cookies = websocket.cookies
            auth_token = cookies.get("nexus_token")
        if not auth_token or not _validate_session(auth_token):
            await websocket.close(code=4401, reason="Unauthorized")
            return

    await websocket.accept()

    # --- Resolve session metadata ---
    storage = get_session_storage()
    session_meta = storage.get_session_meta(session_id)
    if not session_meta:
        await websocket.send_json({"type": "error", "message": f"Session not found: {session_id}"})
        await websocket.close(code=4404, reason="Session not found")
        return

    cmd_info = _build_tmux_command(session_meta, storage)

    # --- Create PTY + tmux ---
    manager = _get_terminal_manager()
    try:
        terminal_id, fd = manager.create_terminal(
            session_id=session_id,
            exec_user=cmd_info["exec_user"],
            exec_dir=cmd_info["exec_dir"],
            cli_cmd=cmd_info["cli_cmd"],
            tmux_session_name=cmd_info["tmux_session_name"],
        )
    except Exception as e:
        logger.error(f"Failed to create terminal for {session_id}: {e}", exc_info=True)
        await websocket.send_json({"type": "error", "message": f"Failed to create terminal: {e}"})
        await websocket.close(code=4500, reason="Terminal creation failed")
        return

    await websocket.send_json({"type": "connected", "terminal_id": terminal_id})
    logger.info(f"Terminal WebSocket connected: session={session_id}, terminal={terminal_id}")

    # --- Background task: read PTY → send to WebSocket ---
    stop_event = asyncio.Event()

    async def pty_reader():
        """Continuously read PTY output and forward to WebSocket."""
        loop = asyncio.get_event_loop()
        while not stop_event.is_set():
            try:
                # Run blocking os.read in thread pool
                data = await loop.run_in_executor(
                    None, manager.read_terminal, terminal_id, 0.1
                )
                if data:
                    encoded = base64.b64encode(data).decode("ascii")
                    await websocket.send_json({"type": "output", "data": encoded})
                elif not manager.is_alive(terminal_id):
                    # Process exited
                    await websocket.send_json({"type": "disconnected"})
                    break
                else:
                    await asyncio.sleep(0.05)
            except (WebSocketDisconnect, RuntimeError):
                break
            except Exception as e:
                logger.debug(f"pty_reader error: {e}")
                await asyncio.sleep(0.1)

    reader_task = asyncio.create_task(pty_reader())

    # --- Main loop: read WebSocket → write to PTY ---
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "input":
                data = msg.get("data", "")
                if data:
                    manager.write_terminal(terminal_id, data)

            elif msg_type == "resize":
                cols = msg.get("cols", 80)
                rows = msg.get("rows", 24)
                manager.resize_terminal(terminal_id, rows, cols)

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info(f"Terminal WebSocket disconnected: session={session_id}")
    except Exception as e:
        logger.error(f"Terminal WebSocket error: {e}", exc_info=True)
    finally:
        stop_event.set()
        reader_task.cancel()
        try:
            await reader_task
        except (asyncio.CancelledError, Exception):
            pass

        # Don't kill the tmux session on disconnect — allow reconnect
        logger.info(f"Terminal WebSocket closed: session={session_id}, terminal={terminal_id}")

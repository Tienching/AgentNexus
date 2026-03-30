# -*- coding: utf-8 -*-
"""Terminal Manager — PTY + tmux session lifecycle management.

Provides a bridge between WebSocket connections and tmux sessions via
pseudo-terminals (PTY).  Uses only Python stdlib (`pty`, `os`, `fcntl`,
`select`, `struct`, `termios`) — zero external dependencies.
"""

from __future__ import annotations

import fcntl
import os
import pty
import select
import signal
import struct
import termios
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

from ..logger import get_logger

logger = get_logger(__name__)


@dataclass
class TerminalInfo:
    """Tracks a single PTY ↔ tmux session."""
    terminal_id: str
    session_id: str
    fd: int                    # master PTY file descriptor
    pid: int                   # child process PID
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    tmux_session_name: str = ""


class TerminalManager:
    """Manages PTY ↔ tmux sessions for the interactive web terminal."""

    def __init__(self):
        self._terminals: Dict[str, TerminalInfo] = {}
        # Map session_id → terminal_id for quick lookup / reconnect
        self._session_map: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_terminal(
        self,
        session_id: str,
        exec_user: str,
        exec_dir: str,
        cli_cmd: str,
        tmux_session_name: str,
    ) -> Tuple[str, int]:
        """Fork a PTY running tmux with the given CLI command.

        Returns (terminal_id, master_fd).
        """
        # If there's already a terminal for this session, reuse it
        existing_tid = self._session_map.get(session_id)
        if existing_tid and existing_tid in self._terminals:
            info = self._terminals[existing_tid]
            if self._is_alive(info.pid):
                logger.info(f"Reusing existing terminal {existing_tid} for session {session_id}")
                info.last_activity = time.time()
                return existing_tid, info.fd

            # Dead terminal — clean up
            self._cleanup_terminal(existing_tid)

        terminal_id = f"term_{session_id[:12]}_{int(time.time())}"

        # Build the full shell command
        tmux_cmd = f"tmux new-session -A -s {tmux_session_name} -c {exec_dir} '{cli_cmd}'"

        # Wrap with su if needed
        current_user = os.environ.get("USER", "root")
        if current_user != exec_user and exec_user:
            shell_cmd = f"su - {exec_user} -c {_shell_quote(f'cd {exec_dir} && {tmux_cmd}')}"
        else:
            shell_cmd = f"cd {exec_dir} && {tmux_cmd}"

        logger.info(f"Creating terminal {terminal_id}: {shell_cmd}")

        pid, fd = pty.fork()

        if pid == 0:
            # ---- Child process ----
            # Set TERM so tmux/CLI tools render correctly
            os.environ["TERM"] = "xterm-256color"
            os.execvp("/bin/sh", ["/bin/sh", "-c", shell_cmd])
            # execvp never returns; if it fails the child exits
            os._exit(1)

        # ---- Parent process ----
        # Set master fd to non-blocking
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        info = TerminalInfo(
            terminal_id=terminal_id,
            session_id=session_id,
            fd=fd,
            pid=pid,
            tmux_session_name=tmux_session_name,
        )
        self._terminals[terminal_id] = info
        self._session_map[session_id] = terminal_id

        logger.info(f"Terminal {terminal_id} created: pid={pid}, fd={fd}")
        return terminal_id, fd

    def resize_terminal(self, terminal_id: str, rows: int, cols: int) -> None:
        """Resize the PTY window."""
        info = self._terminals.get(terminal_id)
        if not info:
            return
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(info.fd, termios.TIOCSWINSZ, winsize)
        except OSError as e:
            logger.warning(f"resize_terminal({terminal_id}) failed: {e}")

    def write_terminal(self, terminal_id: str, data: str) -> None:
        """Write data (user input) to the PTY."""
        info = self._terminals.get(terminal_id)
        if not info:
            return
        try:
            os.write(info.fd, data.encode("utf-8"))
            info.last_activity = time.time()
        except OSError as e:
            logger.warning(f"write_terminal({terminal_id}) failed: {e}")

    def read_terminal(self, terminal_id: str, timeout: float = 0.05) -> Optional[bytes]:
        """Non-blocking read from the PTY.

        Returns raw bytes or None if nothing available within *timeout*.
        """
        info = self._terminals.get(terminal_id)
        if not info:
            return None
        try:
            r, _, _ = select.select([info.fd], [], [], timeout)
            if r:
                data = os.read(info.fd, 4096)
                info.last_activity = time.time()
                return data
        except (OSError, ValueError):
            # fd may have been closed / process exited
            pass
        return None

    def is_alive(self, terminal_id: str) -> bool:
        """Check if the terminal process is still running."""
        info = self._terminals.get(terminal_id)
        if not info:
            return False
        return self._is_alive(info.pid)

    def close_terminal(self, terminal_id: str) -> None:
        """Close a terminal and clean up resources."""
        self._cleanup_terminal(terminal_id)

    def get_terminal_for_session(self, session_id: str) -> Optional[str]:
        """Return terminal_id for a session, or None."""
        tid = self._session_map.get(session_id)
        if tid and tid in self._terminals:
            return tid
        return None

    def cleanup_all(self) -> None:
        """Shut down all terminals (called on application shutdown)."""
        for tid in list(self._terminals.keys()):
            try:
                self._cleanup_terminal(tid)
            except Exception as e:
                logger.warning(f"Error cleaning up terminal {tid}: {e}")
        logger.info("All terminals cleaned up")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cleanup_terminal(self, terminal_id: str) -> None:
        info = self._terminals.pop(terminal_id, None)
        if not info:
            return

        # Remove session mapping
        if self._session_map.get(info.session_id) == terminal_id:
            del self._session_map[info.session_id]

        # Close the master fd
        try:
            os.close(info.fd)
        except OSError:
            pass

        # Terminate the child process
        if self._is_alive(info.pid):
            try:
                os.kill(info.pid, signal.SIGTERM)
                # Give it a moment, then force-kill
                for _ in range(10):
                    time.sleep(0.1)
                    if not self._is_alive(info.pid):
                        break
                else:
                    os.kill(info.pid, signal.SIGKILL)
            except OSError:
                pass

        # Reap the child
        try:
            os.waitpid(info.pid, os.WNOHANG)
        except ChildProcessError:
            pass

        logger.info(f"Terminal {terminal_id} closed (pid={info.pid})")

    @staticmethod
    def _is_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)  # signal 0 = check existence
            return True
        except OSError:
            return False


def _shell_quote(s: str) -> str:
    """Single-quote a string for shell, escaping any embedded single quotes."""
    return "'" + s.replace("'", "'\"'\"'") + "'"

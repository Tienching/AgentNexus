# -*- coding: utf-8 -*-
"""Claude Code session discovery and integration.

Discovers local Claude Code sessions and provides an interface for
interacting with them.

Usage:
    from src.integrations.claude_code.sessions import ClaudeCodeSessions

    sessions = ClaudeCodeSessions()
    active = sessions.discover()
    for session in active:
        print(f"Session: {session.id}, Path: {session.path}")
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import logging

logger = logging.getLogger(__name__)


# Common Claude Code session directories
CLAUDE_DIRS = [
    "~/.claude",
    "~/.config/claude",
    "~/.local/share/claude",
]

# Claude Code session file patterns
SESSION_PATTERNS = [
    "sessions/*.jsonl",
    "projects/*/.claude/sessions/*.jsonl",
]


@dataclass
class ClaudeCodeSession:
    """A discovered Claude Code session."""
    id: str
    path: str
    project_path: Optional[str] = None
    created_at: Optional[datetime] = None
    last_active: Optional[datetime] = None
    message_count: int = 0


class ClaudeCodeSessions:
    """Discovers and manages Claude Code sessions."""

    def __init__(self, claude_dir: Optional[str] = None):
        """Initialize the session discoverer.

        Args:
            claude_dir: Optional override for Claude config directory
        """
        self._claude_dir = claude_dir or self._find_claude_dir()

    def _find_claude_dir(self) -> Optional[str]:
        """Find the Claude configuration directory."""
        for candidate in CLAUDE_DIRS:
            path = Path(candidate).expanduser()
            if path.exists():
                return str(path)
        return None

    def discover(self) -> List[ClaudeCodeSession]:
        """Discover all Claude Code sessions.

        Returns:
            List of discovered sessions
        """
        if not self._claude_dir:
            logger.warning("Claude directory not found")
            return []

        sessions = []
        claude_path = Path(self._claude_dir)

        # Look for sessions in various locations
        search_patterns = [
            claude_path / "sessions",
            claude_path / "projects",
        ]

        for base in search_patterns:
            if not base.exists():
                continue

            if base.name == "sessions":
                # Direct sessions directory
                sessions.extend(self._scan_sessions_dir(base))
            elif base.name == "projects":
                # Projects with embedded .claude directories
                for project in base.iterdir():
                    if project.is_dir():
                        session_dir = project / ".claude" / "sessions"
                        if session_dir.exists():
                            sessions.extend(self._scan_sessions_dir(session_dir, str(project)))

        # Sort by last active, newest first
        sessions.sort(key=lambda s: s.last_active or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        return sessions

    def _scan_sessions_dir(self, sessions_dir: Path, project_path: Optional[str] = None) -> List[ClaudeCodeSession]:
        """Scan a sessions directory for session files.

        Args:
            sessions_dir: Path to the sessions directory
            project_path: Optional project path

        Returns:
            List of discovered sessions
        """
        sessions = []

        try:
            for session_file in sessions_dir.glob("*.jsonl"):
                session = self._parse_session_file(session_file, project_path)
                if session:
                    sessions.append(session)
        except PermissionError:
            logger.warning(f"Permission denied accessing {sessions_dir}")

        return sessions

    def _parse_session_file(self, session_file: Path, project_path: Optional[str] = None) -> Optional[ClaudeCodeSession]:
        """Parse a session file to extract metadata.

        Args:
            session_file: Path to the session JSONL file
            project_path: Optional project path

        Returns:
            ClaudeCodeSession if valid, None otherwise
        """
        try:
            # Get file stats
            stat = session_file.stat()
            created_at = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)
            last_active = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            # Try to read session metadata from filename or first line
            session_id = session_file.stem

            # Count messages in the session
            message_count = 0
            try:
                with open(session_file, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        if line.strip():
                            message_count += 1
            except Exception:
                pass

            return ClaudeCodeSession(
                id=session_id,
                path=str(session_file),
                project_path=project_path,
                created_at=created_at,
                last_active=last_active,
                message_count=message_count,
            )
        except Exception as e:
            logger.debug(f"Failed to parse session file {session_file}: {e}")
            return None

    def get_session(self, session_id: str) -> Optional[ClaudeCodeSession]:
        """Get a specific session by ID.

        Args:
            session_id: The session ID

        Returns:
            The session if found, None otherwise
        """
        sessions = self.discover()
        for session in sessions:
            if session.id == session_id:
                return session
        return None

    def get_recent_sessions(self, limit: int = 10) -> List[ClaudeCodeSession]:
        """Get the most recent sessions.

        Args:
            limit: Maximum number of sessions to return

        Returns:
            List of recent sessions
        """
        sessions = self.discover()
        return sessions[:limit]

    def get_project_sessions(self, project_path: str) -> List[ClaudeCodeSession]:
        """Get all sessions for a specific project.

        Args:
            project_path: Path to the project

        Returns:
            List of sessions for the project
        """
        sessions = self.discover()
        return [s for s in sessions if s.project_path == project_path]


# CLI helper
def list_claude_sessions() -> None:
    """List all Claude Code sessions (CLI entry point)."""
    sessions = ClaudeCodeSessions()
    discovered = sessions.discover()

    if not discovered:
        print("No Claude Code sessions found")
        return

    print(f"Found {len(discovered)} session(s):\n")
    for session in discovered[:20]:  # Show first 20
        date = session.last_active.strftime("%Y-%m-%d %H:%M") if session.last_active else "Unknown"
        project = session.project_path or "Unknown project"
        print(f"  [{session.id}]")
        print(f"    Path: {session.path}")
        print(f"    Project: {project}")
        print(f"    Last active: {date}")
        print(f"    Messages: {session.message_count}")
        print()

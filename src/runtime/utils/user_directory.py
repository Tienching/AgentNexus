# -*- coding: utf-8 -*-
"""Runtime-safe user directory resolution helpers."""

from __future__ import annotations

import logging
import os
import pwd
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class UserDirectoryResolver:
    """Resolve per-user Nexus session paths without depending on server services."""

    def __init__(self, config=None):
        if config is None:
            raise ValueError("UserDirectoryResolver requires a config object")
        self.config = config

    def resolve_user_home(self, exec_user: str) -> Path:
        """Resolve the effective home root for the given exec_user."""
        preferred_home = Path(self.config.user_home_base) / exec_user
        current_user = pwd.getpwuid(os.getuid()).pw_name
        if current_user != exec_user and os.geteuid() != 0:
            return Path.home() / exec_user
        return preferred_home

    def resolve_sessions_root(self, exec_user: str) -> Path:
        """Resolve the sessions root for the given exec_user."""
        return self.resolve_user_home(exec_user) / ".nexus" / "sessions"

    def resolve_session_directory(self, exec_user: str, session_id: str = "default") -> Path:
        """Resolve a session directory using the standard runtime rule."""
        return self.resolve_sessions_root(exec_user) / session_id

    def resolve_task_session_directory(
        self,
        exec_user: str,
        task_id: str,
        session_id: Optional[str] = None,
    ) -> Tuple[Path, str, bool]:
        """Resolve the best-matching session directory for a task."""
        normalized_task_id = (task_id or "").strip()
        normalized_session_id = (session_id or "").strip() or None
        sessions_dir = self.resolve_sessions_root(exec_user)

        preferred_session_id = normalized_session_id or f"task_{normalized_task_id}"
        preferred_dir = sessions_dir / preferred_session_id
        if normalized_session_id and preferred_dir.exists():
            return preferred_dir, preferred_session_id, False

        if normalized_task_id and sessions_dir.exists():
            suffix = f"_{normalized_task_id}"
            try:
                for child in sessions_dir.iterdir():
                    if child.is_dir() and child.name.endswith(suffix):
                        logger.info(
                            "Resolved task session directory via suffix fallback",
                            extra={
                                "exec_user": exec_user,
                                "task_id": normalized_task_id,
                                "resolved_session_id": child.name,
                            },
                        )
                        return child, child.name, True
            except OSError as exc:
                logger.warning(
                    "Failed to scan sessions directory for legacy task session",
                    extra={
                        "exec_user": exec_user,
                        "task_id": normalized_task_id,
                        "sessions_dir": str(sessions_dir),
                        "error": str(exc),
                    },
                )

        legacy_session_id = f"task_{normalized_task_id}" if normalized_task_id else preferred_session_id
        legacy_dir = sessions_dir / legacy_session_id
        if legacy_dir.exists():
            return legacy_dir, legacy_session_id, True

        return preferred_dir, preferred_session_id, False

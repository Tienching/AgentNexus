# -*- coding: utf-8 -*-
"""Deprecated compat session abstractions.

Historically this module exposed an in-memory Session/SessionManager pair that
slowly drifted away from the canonical runtime session metadata model. Keep the
old import path alive, but back it with ``src.runtime.models.session.SessionMeta``
so old and new call-sites share one schema.
"""

from __future__ import annotations

import time
import warnings
from typing import Any, Dict, List, Optional

from pydantic import Field

from ..models.session import SessionMeta, SessionStatus


class Session(SessionMeta):
    """Compatibility session model backed by the canonical runtime SessionMeta."""

    session_id: str = Field(default="")
    workspace: Optional[str] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:  # pragma: no cover - thin normalization
        if not self.id and self.session_id:
            self.id = self.session_id
        if not self.thread_id and self.id:
            self.thread_id = self.id
        if not self.session_id:
            self.session_id = self.id
        if self.workspace and not self.exec_dir:
            self.exec_dir = self.workspace
        if self.workspace:
            self.metadata.setdefault("workspace", self.workspace)
        elif self.exec_dir:
            self.workspace = self.exec_dir
            self.metadata.setdefault("workspace", self.exec_dir)
        self.metadata.setdefault("provider", self.provider)
        if self.exec_user:
            self.metadata.setdefault("exec_user", self.exec_user)

    @property
    def updated_at_ts(self) -> float:
        return float(self.updated_at or int(time.time() * 1000)) / 1000.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.id,
            "provider": self.provider,
            "exec_user": self.exec_user,
            "workspace": self.exec_dir or self.workspace,
            "created_at": float(self.created_at or 0) / 1000.0,
            "updated_at": float(self.updated_at or 0) / 1000.0,
            "metadata": dict(self.metadata or {}),
        }


class SessionManager:
    """Deprecated in-memory compatibility manager backed by Session."""

    def __init__(self):
        warnings.warn(
            f"{__name__}.SessionManager is deprecated; use "
            "src.runtime.stores.session_storage.SessionStorage instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._sessions: Dict[str, Session] = {}

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def create(
        self,
        session_id: str,
        provider: str = "claude",
        exec_user: Optional[str] = None,
        workspace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Session:
        now_ms = int(time.time() * 1000)
        session = Session(
            id=session_id,
            session_id=session_id,
            thread_id=session_id,
            provider=provider,
            exec_user=exec_user,
            exec_dir=workspace,
            workspace=workspace,
            metadata=metadata or {},
            status=SessionStatus.IDLE,
            username=exec_user or "",
            created_at=now_ms,
            updated_at=now_ms,
        )
        self._sessions[session_id] = session
        return session

    def get_or_create(self, session_id: str, provider: str = "claude", **kwargs) -> Session:
        session = self.get(session_id)
        if session is None:
            session = self.create(session_id, provider=provider, **kwargs)
        return session

    def update(self, session_id: str, **updates) -> Optional[Session]:
        session = self.get(session_id)
        if session is None:
            return None
        for key, value in updates.items():
            if key == "workspace":
                session.workspace = value
                session.exec_dir = value
                session.metadata["workspace"] = value
            elif hasattr(session, key):
                setattr(session, key, value)
            else:
                session.metadata[key] = value
        session.updated_at = int(time.time() * 1000)
        return session

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def list_sessions(self) -> List[Session]:
        return list(self._sessions.values())


__all__ = ["Session", "SessionManager"]

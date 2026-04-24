# -*- coding: utf-8 -*-
"""Deprecated session compatibility layer.

Historically ``src.runtime.execution.session`` exposed a separate in-memory
session abstraction. Keep the import path alive, but back it with the
canonical session storage/domain objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
import warnings
from typing import Any, Dict, Optional

from ..models.session import SessionMeta, SessionStatus
from ..stores.session_storage import SessionStorage


@dataclass
class Session:
    """Compatibility view over the canonical session metadata."""

    session_id: str
    provider: str = "claude"
    exec_user: Optional[str] = None
    workspace: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_meta(cls, meta: SessionMeta) -> "Session":
        return cls(
            session_id=meta.id,
            provider=getattr(meta, "provider", None) or "claude",
            exec_user=getattr(meta, "exec_user", None),
            workspace=getattr(meta, "exec_dir", None),
            created_at=(meta.created_at or int(time.time() * 1000)) / 1000.0,
            updated_at=(meta.updated_at or int(time.time() * 1000)) / 1000.0,
            metadata={
                "thread_id": meta.thread_id,
                "title": meta.title,
                "status": meta.status.value if hasattr(meta.status, "value") else str(meta.status),
            },
        )

    def to_meta(self) -> SessionMeta:
        now_ms = int(time.time() * 1000)
        return SessionMeta(
            id=self.session_id,
            thread_id=self.session_id,
            title=str(self.metadata.get("title") or "New Session"),
            username=str(self.metadata.get("username") or self.exec_user or ""),
            exec_user=self.exec_user,
            provider=self.provider,
            status=SessionStatus(str(self.metadata.get("status") or SessionStatus.IDLE.value)),
            exec_dir=self.workspace,
            created_at=int((self.created_at or time.time()) * 1000) or now_ms,
            updated_at=int((self.updated_at or time.time()) * 1000) or now_ms,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "provider": self.provider,
            "exec_user": self.exec_user,
            "workspace": self.workspace,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


class SessionManager:
    """Deprecated compatibility facade over :class:`SessionStorage`."""

    def __init__(self, storage: Optional[SessionStorage] = None):
        warnings.warn(
            "src.runtime.execution.session.SessionManager is deprecated; use "
            "src.runtime.stores.session_storage.SessionStorage instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._storage = storage or SessionStorage()

    def get(self, session_id: str) -> Optional[Session]:
        meta = self._storage.get_session_meta(session_id)
        return Session.from_meta(meta) if meta else None

    def create(
        self,
        session_id: str,
        provider: str = "claude",
        exec_user: Optional[str] = None,
        workspace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Session:
        session = Session(
            session_id=session_id,
            provider=provider,
            exec_user=exec_user,
            workspace=workspace,
            metadata=metadata or {},
        )
        self._storage.save_session_meta(session.to_meta())
        return session

    def get_or_create(self, session_id: str, provider: str = "claude", **kwargs) -> Session:
        existing = self.get(session_id)
        if existing is not None:
            return existing
        return self.create(session_id, provider=provider, **kwargs)

    def update(self, session_id: str, **updates) -> Optional[Session]:
        session = self.get(session_id)
        if session is None:
            return None
        for key, value in updates.items():
            if hasattr(session, key):
                setattr(session, key, value)
        session.updated_at = time.time()
        self._storage.save_session_meta(session.to_meta())
        return session

    def delete(self, session_id: str) -> bool:
        return self._storage.delete_session(session_id)

    def list_sessions(self) -> list[Session]:
        sessions, _ = self._storage.get_all_sessions(page=1, page_size=100000)
        return [Session.from_meta(meta) for meta in sessions]

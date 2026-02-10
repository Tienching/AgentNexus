# -*- coding: utf-8 -*-
"""
会话管理
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import time


@dataclass
class Session:
    """会话"""
    session_id: str
    provider: str = "claude"
    exec_user: Optional[str] = None
    workspace: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
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
    """会话管理器（内存实现，可扩展为 Redis）"""
    
    def __init__(self):
        self._sessions: Dict[str, Session] = {}
    
    def get(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        return self._sessions.get(session_id)
    
    def create(
        self,
        session_id: str,
        provider: str = "claude",
        exec_user: Optional[str] = None,
        workspace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Session:
        """创建会话"""
        session = Session(
            session_id=session_id,
            provider=provider,
            exec_user=exec_user,
            workspace=workspace,
            metadata=metadata or {},
        )
        self._sessions[session_id] = session
        return session
    
    def get_or_create(
        self,
        session_id: str,
        provider: str = "claude",
        **kwargs,
    ) -> Session:
        """获取或创建会话"""
        session = self.get(session_id)
        if session is None:
            session = self.create(session_id, provider=provider, **kwargs)
        return session
    
    def update(self, session_id: str, **updates) -> Optional[Session]:
        """更新会话"""
        session = self.get(session_id)
        if session:
            for key, value in updates.items():
                if hasattr(session, key):
                    setattr(session, key, value)
            session.updated_at = time.time()
        return session
    
    def delete(self, session_id: str) -> bool:
        """删除会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False
    
    def list_sessions(self) -> list[Session]:
        """列出所有会话"""
        return list(self._sessions.values())

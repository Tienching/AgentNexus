# -*- coding: utf-8 -*-
"""Session Storage Service — SQLite implementation.

Provides CRUD operations for AGUI session data in SQLite.
Replaces the multi-key Redis structure (meta hash, messages list,
toolcalls hash, events list, streaming content with TTL) with
normalized SQLite tables.

TTL is handled via ``expires_at`` columns with periodic cleanup.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from ..models.session import (
    SessionMeta,
    SessionStatus,
    StoredMessage,
    StoredToolCall,
)
from src.runtime.stores.db import Database, get_db

logger = logging.getLogger(__name__)

# TTL constants (in seconds)
SESSION_TTL = 7 * 24 * 60 * 60  # 7 days
STREAMING_CONTENT_TTL = 60 * 60  # 1 hour for temporary streaming content

# ---------------------------------------------------------------------------
# Schema bootstrap — idempotent, called once on first access
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS core_sessions (
    id              TEXT PRIMARY KEY,
    thread_id       TEXT NOT NULL,
    run_id          TEXT,
    title           TEXT NOT NULL DEFAULT 'New Session',
    username        TEXT NOT NULL DEFAULT '',
    exec_user       TEXT,
    provider        TEXT,
    alias           TEXT,
    exec_dir        TEXT,
    status          TEXT NOT NULL DEFAULT 'idle',
    message_count   INTEGER NOT NULL DEFAULT 0,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    expires_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_core_sessions_username ON core_sessions(username);
CREATE INDEX IF NOT EXISTS idx_core_sessions_updated ON core_sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_core_sessions_status ON core_sessions(status);

CREATE TABLE IF NOT EXISTS core_session_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    msg_id      TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    msg_json    TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_core_session_messages_sid ON core_session_messages(session_id);

CREATE TABLE IF NOT EXISTS core_session_tool_calls (
    call_id     TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    tool_json   TEXT NOT NULL,
    PRIMARY KEY (session_id, call_id)
);

CREATE TABLE IF NOT EXISTS core_session_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    event_json  TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_core_session_events_sid ON core_session_events(session_id);

CREATE TABLE IF NOT EXISTS core_session_streaming (
    session_id  TEXT NOT NULL,
    message_id  TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    expires_at  REAL NOT NULL,
    PRIMARY KEY (session_id, message_id)
);
"""

_schema_initialized = False


def _ensure_schema(db: Database) -> None:
    global _schema_initialized
    if _schema_initialized:
        return
    try:
        with db.transaction() as conn:
            conn.executescript(_SCHEMA_SQL)
        _schema_initialized = True
    except Exception as e:
        logger.warning(f"Schema init (may already exist): {e}")
        _schema_initialized = True


class SessionStorage:
    """Session storage service using SQLite."""

    def __init__(self, db: Optional[Database] = None):
        self._db = db or get_db()
        _ensure_schema(self._db)

    # ============ Session Metadata Operations ============

    def save_session_meta(self, meta: SessionMeta) -> bool:
        try:
            session_id = (meta.id or "").strip()
            if not session_id:
                logger.warning("Skip saving session meta with empty id")
                return False

            now_ms = int(time.time() * 1000)
            expires_at = time.time() + SESSION_TTL

            with self._db.transaction() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO core_sessions (
                        id, thread_id, run_id, title, username, exec_user,
                        provider, alias, exec_dir, status,
                        message_count, created_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id,
                    meta.thread_id or session_id,
                    getattr(meta, "run_id", None) or None,
                    meta.title or "New Session",
                    meta.username or "",
                    getattr(meta, "exec_user", None) or None,
                    meta.provider or None,
                    getattr(meta, "alias", None) or None,
                    getattr(meta, "exec_dir", None) or None,
                    meta.status.value if isinstance(meta.status, SessionStatus) else (meta.status or "idle"),
                    getattr(meta, "message_count", 0) or 0,
                    meta.created_at or now_ms,
                    meta.updated_at or now_ms,
                    expires_at,
                ))

            logger.debug(f"Saved session meta: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save session meta: {e}")
            return False

    def get_session_meta(self, session_id: str) -> Optional[SessionMeta]:
        try:
            row = self._db.execute_fetchone(
                "SELECT * FROM core_sessions WHERE id = ?", (session_id,)
            )
            if not row:
                return None
            return self._row_to_meta(row)
        except Exception as e:
            logger.error(f"Failed to get session meta: {e}")
            return None

    def _row_to_meta(self, row: dict) -> SessionMeta:
        return SessionMeta(
            id=row["id"],
            thread_id=row.get("thread_id") or row["id"],
            run_id=row.get("run_id") or None,
            title=row.get("title") or "New Session",
            username=row.get("username") or "",
            exec_user=row.get("exec_user") or None,
            provider=row.get("provider") or None,
            alias=row.get("alias") or None,
            exec_dir=row.get("exec_dir") or None,
            status=SessionStatus(row.get("status", "idle")),
            message_count=row.get("message_count", 0) or 0,
            created_at=row.get("created_at") or 0,
            updated_at=row.get("updated_at") or 0,
        )

    # ============ Session Listing ============

    def get_user_sessions(
        self,
        username: str,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        status_filter: Optional[SessionStatus] = None,
    ) -> Tuple[List[SessionMeta], int]:
        try:
            conditions = ["username = ?"]
            params: list = [username]
            if search:
                conditions.append("title LIKE ?")
                params.append(f"%{search}%")
            if status_filter:
                conditions.append("status = ?")
                params.append(status_filter.value)
            where = " AND ".join(conditions)
            count_row = self._db.execute_fetchone(
                f"SELECT COUNT(*) as cnt FROM core_sessions WHERE {where}", params
            )
            total = count_row["cnt"] if count_row else 0
            rows = self._db.execute_fetchall(
                f"SELECT * FROM core_sessions WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                params + [page_size, (page - 1) * page_size],
            )
            return [self._row_to_meta(r) for r in rows], total
        except Exception as e:
            logger.error(f"Failed to get user sessions: {e}")
            return [], 0

    def get_all_sessions(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        status_filter: Optional[SessionStatus] = None,
    ) -> Tuple[List[SessionMeta], int]:
        try:
            conditions: list = []
            params: list = []
            if search:
                conditions.append("title LIKE ?")
                params.append(f"%{search}%")
            if status_filter:
                conditions.append("status = ?")
                params.append(status_filter.value)
            where = " AND ".join(conditions) if conditions else "1=1"
            count_row = self._db.execute_fetchone(
                f"SELECT COUNT(*) as cnt FROM core_sessions WHERE {where}", params
            )
            total = count_row["cnt"] if count_row else 0
            rows = self._db.execute_fetchall(
                f"SELECT * FROM core_sessions WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                params + [page_size, (page - 1) * page_size],
            )
            return [self._row_to_meta(r) for r in rows], total
        except Exception as e:
            logger.error(f"Failed to get all sessions: {e}")
            return [], 0

    def get_all_usernames(self) -> List[str]:
        try:
            rows = self._db.execute_fetchall(
                "SELECT DISTINCT username FROM core_sessions WHERE username IS NOT NULL AND username != ''"
            )
            return sorted([r["username"] for r in rows])
        except Exception as e:
            logger.error(f"Failed to get usernames: {e}")
            return []

    def update_session_status(
        self,
        session_id: str,
        status: SessionStatus,
        update_timestamp: bool = True,
    ) -> bool:
        try:
            if update_timestamp:
                updated_at = int(time.time() * 1000)
                with self._db.transaction() as conn:
                    conn.execute(
                        "UPDATE core_sessions SET status = ?, updated_at = ? WHERE id = ?",
                        (status.value, updated_at, session_id),
                    )
            else:
                with self._db.transaction() as conn:
                    conn.execute(
                        "UPDATE core_sessions SET status = ? WHERE id = ?",
                        (status.value, session_id),
                    )
            return True
        except Exception as e:
            logger.error(f"Failed to update session status: {e}")
            return False

    def delete_session(self, session_id: str, username: Optional[str] = None) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM core_session_messages WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM core_session_tool_calls WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM core_session_events WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM core_session_streaming WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM core_sessions WHERE id = ?", (session_id,))
            logger.info(f"Deleted session: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            return False

    # ============ Message Operations ============

    def add_session_message(self, session_id: str, message: StoredMessage) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT INTO core_session_messages (session_id, msg_id, role, content, msg_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, message.id, message.role, message.content, message.to_json(), time.time()),
                )
                conn.execute(
                    "UPDATE core_sessions SET message_count = message_count + 1, updated_at = ? WHERE id = ?",
                    (int(time.time() * 1000), session_id),
                )
            return True
        except Exception as e:
            logger.error(f"Failed to add session message: {e}")
            return False

    def update_message(self, session_id: str, message: StoredMessage) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    "UPDATE core_session_messages SET role = ?, content = ?, msg_json = ? WHERE session_id = ? AND msg_id = ?",
                    (message.role, message.content, message.to_json(), session_id, message.id),
                )
            return True
        except Exception as e:
            logger.error(f"Failed to update message: {e}")
            return False

    def get_session_messages(self, session_id: str) -> List[StoredMessage]:
        try:
            rows = self._db.execute_fetchall(
                "SELECT msg_json FROM core_session_messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            )
            messages = []
            for row in rows:
                try:
                    messages.append(StoredMessage.from_json(row["msg_json"]))
                except Exception:
                    continue
            return messages
        except Exception as e:
            logger.error(f"Failed to get session messages: {e}")
            return []

    def get_message_by_id(self, session_id: str, message_id: str) -> Optional[StoredMessage]:
        try:
            row = self._db.execute_fetchone(
                "SELECT msg_json FROM core_session_messages WHERE session_id = ? AND msg_id = ?",
                (session_id, message_id),
            )
            return StoredMessage.from_json(row["msg_json"]) if row else None
        except Exception:
            return None

    def clear_session_messages(self, session_id: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM core_session_messages WHERE session_id = ?", (session_id,))
                conn.execute("UPDATE core_sessions SET message_count = 0 WHERE id = ?", (session_id,))
            return True
        except Exception as e:
            logger.error(f"Failed to clear session messages: {e}")
            return False

    def clear_session_tool_calls(self, session_id: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM core_session_tool_calls WHERE session_id = ?", (session_id,))
            return True
        except Exception as e:
            logger.error(f"Failed to clear session tool calls: {e}")
            return False

    # ============ Tool Call Operations ============

    def save_tool_call(self, session_id: str, tool_call: StoredToolCall) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO core_session_tool_calls (call_id, session_id, tool_json) VALUES (?, ?, ?)",
                    (tool_call.id, session_id, tool_call.to_json()),
                )
            return True
        except Exception as e:
            logger.error(f"Failed to save tool call: {e}")
            return False

    def get_tool_call(self, session_id: str, tool_call_id: str) -> Optional[StoredToolCall]:
        try:
            row = self._db.execute_fetchone(
                "SELECT tool_json FROM core_session_tool_calls WHERE session_id = ? AND call_id = ?",
                (session_id, tool_call_id),
            )
            return StoredToolCall.from_json(row["tool_json"]) if row else None
        except Exception:
            return None

    def get_session_tool_calls(self, session_id: str) -> List[StoredToolCall]:
        try:
            rows = self._db.execute_fetchall(
                "SELECT tool_json FROM core_session_tool_calls WHERE session_id = ?",
                (session_id,),
            )
            tc = []
            for row in rows:
                try:
                    tc.append(StoredToolCall.from_json(row["tool_json"]))
                except Exception:
                    continue
            tc.sort(key=lambda x: x.start_time)
            return tc
        except Exception as e:
            logger.error(f"Failed to get session tool calls: {e}")
            return []

    def update_tool_call(self, session_id: str, tool_call: StoredToolCall) -> bool:
        return self.save_tool_call(session_id, tool_call)

    # ============ Streaming Content ============

    def save_streaming_content(self, session_id: str, message_id: str, content: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO core_session_streaming (session_id, message_id, content, expires_at) VALUES (?, ?, ?, ?)",
                    (session_id, message_id, content, time.time() + STREAMING_CONTENT_TTL),
                )
            return True
        except Exception as e:
            logger.error(f"Failed to save streaming content: {e}")
            return False

    def get_streaming_content(self, session_id: str, message_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone(
                "SELECT content FROM core_session_streaming WHERE session_id = ? AND message_id = ?",
                (session_id, message_id),
            )
            return row["content"] if row else None
        except Exception:
            return None

    def delete_streaming_content(self, session_id: str, message_id: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    "DELETE FROM core_session_streaming WHERE session_id = ? AND message_id = ?",
                    (session_id, message_id),
                )
            return True
        except Exception as e:
            logger.error(f"Failed to delete streaming content: {e}")
            return False

    # ============ AGUI Event Log Operations ============

    def append_agui_event(self, session_id: str, event: Dict[str, Any], max_len: int = 5000) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT INTO core_session_events (session_id, event_json, created_at) VALUES (?, ?, ?)",
                    (session_id, json.dumps(event, ensure_ascii=False), time.time()),
                )
                # Cap to max_len by deleting oldest beyond limit
                conn.execute(
                    "DELETE FROM core_session_events WHERE id IN ("
                    "  SELECT id FROM core_session_events WHERE session_id = ? ORDER BY id DESC LIMIT -1 OFFSET ?"
                    ")",
                    (session_id, max_len),
                )
            return True
        except Exception as e:
            logger.error(f"Failed to append AGUI event: {e}")
            return False

    def get_agui_event_count(self, session_id: str) -> int:
        try:
            row = self._db.execute_fetchone(
                "SELECT COUNT(*) as cnt FROM core_session_events WHERE session_id = ?",
                (session_id,),
            )
            return row["cnt"] if row else 0
        except Exception:
            return 0

    def get_agui_events(self, session_id: str, start: int = 0, end: int = -1) -> List[Dict[str, Any]]:
        try:
            if end == -1:
                rows = self._db.execute_fetchall(
                    "SELECT event_json FROM core_session_events WHERE session_id = ? ORDER BY id LIMIT -1 OFFSET ?",
                    (session_id, start),
                )
            else:
                rows = self._db.execute_fetchall(
                    "SELECT event_json FROM core_session_events WHERE session_id = ? ORDER BY id LIMIT ? OFFSET ?",
                    (session_id, end - start + 1, start),
                )
            out = []
            for row in rows:
                try:
                    evt = json.loads(row["event_json"])
                    if isinstance(evt, dict):
                        out.append(evt)
                except Exception:
                    continue
            return out
        except Exception:
            return []


# Global instance getter
_session_storage: Optional[SessionStorage] = None


def get_session_storage() -> SessionStorage:
    """Get global SessionStorage instance"""
    global _session_storage
    if _session_storage is None:
        _session_storage = SessionStorage()
    return _session_storage

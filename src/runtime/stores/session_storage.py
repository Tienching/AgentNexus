# -*- coding: utf-8 -*-
"""Session Storage Service — SQLite implementation.

Provides CRUD operations for AGUI session data in SQLite.
Replaces the multi-key Redis structure (meta hash, messages list,
toolcalls hash, events list, streaming content with TTL) with
normalized SQLite tables.

TTL is handled via ``expires_at`` columns with periodic cleanup.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..models.session import (
    SessionMeta,
    SessionStatus,
    StoredMessage,
    StoredToolCall,
)
from .db import Database, get_db

logger = logging.getLogger(__name__)

SESSION_TTL = 7 * 24 * 60 * 60
STREAMING_CONTENT_TTL = 60 * 60


class SessionStorage:
    """Session storage service using SQLite."""

    def __init__(self, db: Optional[Database] = None):
        self._db = db or get_db()

    # ============ Session Metadata Operations ============

    def save_session_meta(self, meta: SessionMeta) -> bool:
        try:
            session_id = (meta.id or "").strip()
            if not session_id:
                logger.warning("Skip saving session meta with empty id")
                return False
            meta.id = session_id
            if not (meta.thread_id or "").strip():
                meta.thread_id = session_id

            updated_at = int(time.time() * 1000)
            expires_at = time.time() + SESSION_TTL

            with self._db.transaction() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO sessions (
                        id, thread_id, title, username, agent_name, workspace,
                        exec_dir, exec_dir_override, status, message_count,
                        provider, model, cli_session_id, claude_session_id,
                        session_exec_user, exec_user_switched, session_cleared,
                        target_session_id, workspace_provider, workspace_alias,
                        persistent_mode, created_at, updated_at, expires_at
                    ) VALUES (
                        :id, :thread_id, :title, :username, :agent_name, :workspace,
                        :exec_dir, :exec_dir_override, :status, :message_count,
                        :provider, :model, :cli_session_id, :claude_session_id,
                        :session_exec_user, :exec_user_switched, :session_cleared,
                        :target_session_id, :workspace_provider, :workspace_alias,
                        :persistent_mode, :created_at, :updated_at, :expires_at
                    )
                """, {
                    "id": meta.id,
                    "thread_id": meta.thread_id or meta.id,
                    "title": meta.title or "",
                    "username": meta.username or "",
                    "agent_name": getattr(meta, "agent_name", None) or "",
                    "workspace": getattr(meta, "workspace", None) or "",
                    "exec_dir": getattr(meta, "exec_dir", None) or "",
                    "exec_dir_override": None,
                    "status": meta.status.value if isinstance(meta.status, SessionStatus) else (meta.status or "active"),
                    "message_count": getattr(meta, "message_count", 0) or 0,
                    "provider": getattr(meta, "provider", None) or "",
                    "model": getattr(meta, "model", None) or "",
                    "cli_session_id": getattr(meta, "cli_session_id", None) or "",
                    "claude_session_id": getattr(meta, "claude_session_id", None) or "",
                    "session_exec_user": getattr(meta, "exec_user", None) or getattr(meta, "username", None) or "",
                    "exec_user_switched": 0,
                    "session_cleared": 0,
                    "target_session_id": None,
                    "workspace_provider": None,
                    "workspace_alias": None,
                    "persistent_mode": 0,
                    "created_at": meta.created_at / 1000.0 if isinstance(meta.created_at, (int, float)) and meta.created_at else time.time(),
                    "updated_at": updated_at,
                    "expires_at": expires_at,
                })

            logger.debug(f"Saved session meta: {meta.id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save session meta: {e}")
            return False

    def get_session_meta(self, session_id: str) -> Optional[SessionMeta]:
        try:
            row = self._db.execute_fetchone(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            )
            if not row:
                return None
            return self._row_to_meta(row)
        except Exception as e:
            logger.error(f"Failed to get session meta: {e}")
            return None

    def _row_to_meta(self, row: dict) -> SessionMeta:
        created_ts = row.get("created_at")
        # SessionMeta.created_at is int (ms timestamp), not datetime
        created_at_ms = int(created_ts * 1000) if created_ts else int(time.time() * 1000)
        return SessionMeta(
            id=row["id"],
            thread_id=row.get("thread_id") or row["id"],
            title=row.get("title") or "",
            username=row.get("username") or "",
            agent_name=row.get("agent_name") or None,
            workspace=row.get("workspace") or None,
            exec_dir=row.get("exec_dir") or None,
            status=SessionStatus(row.get("status", "idle")),
            message_count=row.get("message_count", 0) or 0,
            provider=row.get("provider") or None,
            model=row.get("model") or None,
            cli_session_id=row.get("cli_session_id") or None,
            claude_session_id=row.get("claude_session_id") or None,
            created_at=created_at_ms,
            updated_at=row.get("updated_at") or 0,
        )

    def _update_meta_fields(self, session_id: str, fields: dict) -> bool:
        if not fields:
            return True
        set_parts = []
        values = []
        for k, v in fields.items():
            set_parts.append(f"{k} = ?")
            values.append(v)
        set_parts.append("updated_at = ?")
        values.append(int(time.time() * 1000))
        values.append(session_id)
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    f"UPDATE sessions SET {', '.join(set_parts)} WHERE id = ?",
                    values,
                )
            return True
        except Exception as e:
            logger.error(f"Failed to update session meta fields: {e}")
            return False

    # ---- History Session Hidden ----

    def _history_mapping_key(self, provider: str, history_session_id: str, project_path: str) -> str:
        project_hash = hashlib.sha1((project_path or "").encode("utf-8")).hexdigest()
        return f"{provider}:{history_session_id}:{project_hash}"

    def set_history_runtime_mapping(self, provider: str, history_session_id: str, project_path: str, runtime_session_id: str) -> bool:
        try:
            key_parts = self._history_mapping_key(provider, history_session_id, project_path).split(":")
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO history_mappings (provider, history_session_id, project_hash, runtime_session_id, expires_at) VALUES (?, ?, ?, ?, ?)",
                    (key_parts[0], key_parts[1], key_parts[2], runtime_session_id, time.time() + SESSION_TTL),
                )
            return True
        except Exception as e:
            logger.error(f"Failed to set history runtime mapping: {e}")
            return False

    def get_history_runtime_mapping(self, provider: str, history_session_id: str, project_path: str) -> Optional[str]:
        try:
            key_parts = self._history_mapping_key(provider, history_session_id, project_path).split(":")
            row = self._db.execute_fetchone(
                "SELECT runtime_session_id FROM history_mappings WHERE provider = ? AND history_session_id = ? AND project_hash = ?",
                (key_parts[0], key_parts[1], key_parts[2]),
            )
            return row["runtime_session_id"] if row else None
        except Exception as e:
            logger.error(f"Failed to get history runtime mapping: {e}")
            return None

    def hide_history_session(self, session_id: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("INSERT OR IGNORE INTO history_hidden (session_id) VALUES (?)", (session_id,))
            return True
        except Exception as e:
            logger.error(f"Failed to hide history session: {e}")
            return False

    def unhide_history_session(self, session_id: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM history_hidden WHERE session_id = ?", (session_id,))
            return True
        except Exception as e:
            logger.error(f"Failed to unhide history session: {e}")
            return False

    def is_history_session_hidden(self, session_id: str) -> bool:
        try:
            row = self._db.execute_fetchone("SELECT 1 FROM history_hidden WHERE session_id = ?", (session_id,))
            return row is not None
        except Exception:
            return False

    def get_hidden_history_sessions(self) -> set:
        try:
            rows = self._db.execute_fetchall("SELECT session_id FROM history_hidden")
            return {r["session_id"] for r in rows}
        except Exception:
            return set()

    def set_history_bootstrap_context(self, session_id: str, context: str) -> bool:
        return self._update_meta_fields(session_id, {"history_bootstrap_context": context})

    def consume_history_bootstrap_context(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT history_bootstrap_context FROM sessions WHERE id = ?", (session_id,))
            ctx = row.get("history_bootstrap_context") if row else None
            if ctx:
                self._update_meta_fields(session_id, {"history_bootstrap_context": None})
            return ctx or None
        except Exception as e:
            logger.error(f"Failed to consume history bootstrap context: {e}")
            return None

    def set_inherited_session(self, session_id: str, inherited_from: str) -> bool:
        return self._update_meta_fields(session_id, {"inherited_from": inherited_from})

    def get_inherited_session(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT inherited_from FROM sessions WHERE id = ?", (session_id,))
            return row.get("inherited_from") if row else None
        except Exception:
            return None

    def clear_inherited_session(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"inherited_from": None})

    def set_exec_dir_override(self, session_id: str, exec_dir: str) -> bool:
        return self._update_meta_fields(session_id, {"exec_dir_override": exec_dir, "exec_dir": exec_dir})

    def get_exec_dir_override(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT exec_dir_override FROM sessions WHERE id = ?", (session_id,))
            return row.get("exec_dir_override") if row else None
        except Exception:
            return None

    def clear_exec_dir_override(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"exec_dir_override": None})

    def get_session_exec_user(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT session_exec_user FROM sessions WHERE id = ?", (session_id,))
            return (row.get("session_exec_user") or "").strip() or None if row else None
        except Exception:
            return None

    def _build_default_session_exec_dir(self, user_home_base: str, exec_user: str, session_id: str) -> str:
        return str(Path(user_home_base) / exec_user / ".nexus" / "sessions" / session_id)

    def set_session_exec_user(self, session_id: str, exec_user: str, user_home_base: Optional[str] = None) -> bool:
        normalized = (exec_user or "").strip()
        if not normalized:
            return False
        fields = {"session_exec_user": normalized, "username": normalized}
        try:
            existing = self.get_session_meta(session_id)
            if existing and user_home_base:
                old_user = (existing.username or "").strip()
                current_dir = (existing.exec_dir or "").strip() if existing else ""
                default_new = self._build_default_session_exec_dir(user_home_base, normalized, session_id)
                should_update = not current_dir
                if not should_update and old_user:
                    default_old = self._build_default_session_exec_dir(user_home_base, old_user, session_id)
                    should_update = current_dir == default_old
                if should_update:
                    fields["exec_dir"] = default_new
            self._update_meta_fields(session_id, fields)
            return True
        except Exception as e:
            logger.error(f"Failed to set session exec_user: {e}")
            return False

    def set_exec_user_switched(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"exec_user_switched": 1})

    def consume_exec_user_switched(self, session_id: str) -> bool:
        try:
            row = self._db.execute_fetchone("SELECT exec_user_switched FROM sessions WHERE id = ?", (session_id,))
            if row and row.get("exec_user_switched"):
                self._update_meta_fields(session_id, {"exec_user_switched": 0})
                return True
            return False
        except Exception:
            return False

    def set_target_session_id(self, session_id: str, target_session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"target_session_id": target_session_id})

    def get_target_session_id(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT target_session_id FROM sessions WHERE id = ?", (session_id,))
            return row.get("target_session_id") if row else None
        except Exception:
            return None

    def clear_target_session_id(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"target_session_id": None})

    def set_workspace_provider(self, session_id: str, provider: str) -> bool:
        return self._update_meta_fields(session_id, {"workspace_provider": provider})

    def get_workspace_provider(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT workspace_provider FROM sessions WHERE id = ?", (session_id,))
            return row.get("workspace_provider") if row else None
        except Exception:
            return None

    def clear_workspace_provider(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"workspace_provider": None})

    def set_workspace_alias(self, session_id: str, alias: str) -> bool:
        return self._update_meta_fields(session_id, {"workspace_alias": alias})

    def get_workspace_alias(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT workspace_alias FROM sessions WHERE id = ?", (session_id,))
            return row.get("workspace_alias") if row else None
        except Exception:
            return None

    def clear_workspace_alias(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"workspace_alias": None})

    # ============ Switch Context ============

    def set_handoff_context(self, session_id: str, context: str, target_provider_or_alias: str, model: Optional[str] = None) -> bool:
        fields = {"handoff_context": context, "handoff_target_provider": target_provider_or_alias}
        fields["handoff_model"] = model
        return self._update_meta_fields(session_id, fields)

    def get_handoff_context(self, session_id: str) -> Optional[Tuple[str, str]]:
        try:
            row = self._db.execute_fetchone("SELECT handoff_context, handoff_target_provider FROM sessions WHERE id = ?", (session_id,))
            if row and row.get("handoff_target_provider"):
                return (row.get("handoff_context") or "", row["handoff_target_provider"])
            return None
        except Exception:
            return None

    def get_handoff_model(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT handoff_model FROM sessions WHERE id = ?", (session_id,))
            return row.get("handoff_model") if row else None
        except Exception:
            return None

    def clear_handoff_context(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"handoff_context": None, "handoff_target_provider": None, "handoff_model": None})

    def set_handoff_pending_summary(self, session_id: str, target_provider_or_alias: str, model: Optional[str] = None, context_mode: str = "full") -> bool:
        normalized_mode = (context_mode or "full").strip().lower()
        if normalized_mode == "summary":
            normalized_mode = "windowed"
        if normalized_mode not in ("full", "windowed"):
            normalized_mode = "full"
        fields = {"handoff_pending_summary": target_provider_or_alias, "handoff_pending_context_mode": normalized_mode, "handoff_model": model}
        return self._update_meta_fields(session_id, fields)

    def get_handoff_pending_summary(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT handoff_pending_summary FROM sessions WHERE id = ?", (session_id,))
            return row.get("handoff_pending_summary") if row else None
        except Exception:
            return None

    def get_handoff_pending_context_mode(self, session_id: str) -> str:
        try:
            row = self._db.execute_fetchone("SELECT handoff_pending_context_mode FROM sessions WHERE id = ?", (session_id,))
            mode = (row.get("handoff_pending_context_mode") or "full").strip().lower() if row else "full"
            if mode == "summary":
                mode = "windowed"
            return mode if mode in ("full", "windowed") else "full"
        except Exception:
            return "full"

    def clear_handoff_pending_summary(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"handoff_pending_summary": None, "handoff_model": None, "handoff_pending_context_mode": None})

    # ============ Model Override ============

    def set_model_override(self, session_id: str, model: str) -> bool:
        return self._update_meta_fields(session_id, {"model_override": model})

    def get_model_override(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT model_override FROM sessions WHERE id = ?", (session_id,))
            return row.get("model_override") if row else None
        except Exception:
            return None

    def clear_model_override(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"model_override": None})

    def set_active_model(self, session_id: str, model: str) -> bool:
        return self._update_meta_fields(session_id, {"active_model": model})

    def get_active_model(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT active_model FROM sessions WHERE id = ?", (session_id,))
            return row.get("active_model") if row else None
        except Exception:
            return None

    # ============ Switch Provider ============

    def set_handoff_provider(self, session_id: str, provider: str, alias: str) -> bool:
        return self._update_meta_fields(session_id, {"handoff_provider": provider, "handoff_alias": alias})

    def get_handoff_provider(self, session_id: str) -> Optional[Tuple[str, str]]:
        try:
            row = self._db.execute_fetchone("SELECT handoff_provider, handoff_alias FROM sessions WHERE id = ?", (session_id,))
            if row and row.get("handoff_provider"):
                return (row["handoff_provider"], row.get("handoff_alias") or row["handoff_provider"])
            return None
        except Exception:
            return None

    def clear_handoff_provider(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"handoff_provider": None, "handoff_alias": None})

    # ============ CLI Session ID ============

    def set_claude_session_id(self, session_id: str, claude_session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"claude_session_id": claude_session_id})

    def get_claude_session_id(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT claude_session_id FROM sessions WHERE id = ?", (session_id,))
            return row.get("claude_session_id") if row else None
        except Exception:
            return None

    def clear_claude_session_id(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"claude_session_id": None})

    def set_cli_session_id(self, session_id: str, cli_session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"cli_session_id": cli_session_id, "claude_session_id": cli_session_id})

    def get_cli_session_id(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT cli_session_id, claude_session_id FROM sessions WHERE id = ?", (session_id,))
            if row:
                return row.get("cli_session_id") or row.get("claude_session_id")
            return None
        except Exception:
            return None

    def clear_cli_session_id(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"cli_session_id": None, "claude_session_id": None})

    def set_session_cleared(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"session_cleared": 1})

    def consume_session_cleared(self, session_id: str) -> bool:
        try:
            row = self._db.execute_fetchone("SELECT session_cleared FROM sessions WHERE id = ?", (session_id,))
            if row and row.get("session_cleared"):
                self._update_meta_fields(session_id, {"session_cleared": 0})
                return True
            return False
        except Exception:
            return False

    # ============ Session Listing ============

    def get_user_sessions(self, username: str, page: int = 1, page_size: int = 20, search: Optional[str] = None, status_filter: Optional[SessionStatus] = None) -> Tuple[List[SessionMeta], int]:
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
            count_row = self._db.execute_fetchone(f"SELECT COUNT(*) as cnt FROM sessions WHERE {where}", params)
            total = count_row["cnt"] if count_row else 0
            rows = self._db.execute_fetchall(f"SELECT * FROM sessions WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?", params + [page_size, (page - 1) * page_size])
            return [self._row_to_meta(r) for r in rows], total
        except Exception as e:
            logger.error(f"Failed to get user sessions: {e}")
            return [], 0

    def get_all_sessions(self, page: int = 1, page_size: int = 20, search: Optional[str] = None, status_filter: Optional[SessionStatus] = None) -> Tuple[List[SessionMeta], int]:
        try:
            conditions = []
            params: list = []
            if search:
                conditions.append("title LIKE ?")
                params.append(f"%{search}%")
            if status_filter:
                conditions.append("status = ?")
                params.append(status_filter.value)
            where = " AND ".join(conditions) if conditions else "1=1"
            count_row = self._db.execute_fetchone(f"SELECT COUNT(*) as cnt FROM sessions WHERE {where}", params)
            total = count_row["cnt"] if count_row else 0
            rows = self._db.execute_fetchall(f"SELECT * FROM sessions WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?", params + [page_size, (page - 1) * page_size])
            return [self._row_to_meta(r) for r in rows], total
        except Exception as e:
            logger.error(f"Failed to get all sessions: {e}")
            return [], 0

    def get_all_usernames(self) -> List[str]:
        try:
            rows = self._db.execute_fetchall("SELECT DISTINCT username FROM sessions WHERE username IS NOT NULL AND username != ''")
            return sorted([r["username"] for r in rows])
        except Exception as e:
            logger.error(f"Failed to get usernames: {e}")
            return []

    def update_session_status(self, session_id: str, status: SessionStatus, update_timestamp: bool = True) -> bool:
        fields = {"status": status.value}
        if update_timestamp:
            fields["updated_at"] = int(time.time() * 1000)
        return self._update_meta_fields(session_id, fields)

    def delete_session(self, session_id: str, username: Optional[str] = None) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM session_tool_calls WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM session_events WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM session_streaming_content WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
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
                    "INSERT INTO session_messages (session_id, msg_id, role, content, msg_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, message.id, message.role, message.content, message.to_json(), time.time()),
                )
                conn.execute("UPDATE sessions SET message_count = message_count + 1, updated_at = ? WHERE id = ?", (int(time.time() * 1000), session_id))
            return True
        except Exception as e:
            logger.error(f"Failed to add session message: {e}")
            return False

    def update_message(self, session_id: str, message: StoredMessage) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("UPDATE session_messages SET role = ?, content = ?, msg_json = ? WHERE session_id = ? AND msg_id = ?", (message.role, message.content, message.to_json(), session_id, message.id))
            return True
        except Exception as e:
            logger.error(f"Failed to update message: {e}")
            return False

    def get_session_messages(self, session_id: str) -> List[StoredMessage]:
        try:
            rows = self._db.execute_fetchall("SELECT msg_json FROM session_messages WHERE session_id = ? ORDER BY id", (session_id,))
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
            row = self._db.execute_fetchone("SELECT msg_json FROM session_messages WHERE session_id = ? AND msg_id = ?", (session_id, message_id))
            return StoredMessage.from_json(row["msg_json"]) if row else None
        except Exception:
            return None

    def clear_session_messages(self, session_id: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
                conn.execute("UPDATE sessions SET message_count = 0 WHERE id = ?", (session_id,))
            return True
        except Exception as e:
            logger.error(f"Failed to clear session messages: {e}")
            return False

    def clear_session_tool_calls(self, session_id: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM session_tool_calls WHERE session_id = ?", (session_id,))
            return True
        except Exception as e:
            logger.error(f"Failed to clear session tool calls: {e}")
            return False

    # ============ Tool Call Operations ============

    def save_tool_call(self, session_id: str, tool_call: StoredToolCall) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("INSERT OR REPLACE INTO session_tool_calls (call_id, session_id, tool_json) VALUES (?, ?, ?)", (tool_call.id, session_id, tool_call.to_json()))
            return True
        except Exception as e:
            logger.error(f"Failed to save tool call: {e}")
            return False

    def get_tool_call(self, session_id: str, tool_call_id: str) -> Optional[StoredToolCall]:
        try:
            row = self._db.execute_fetchone("SELECT tool_json FROM session_tool_calls WHERE session_id = ? AND call_id = ?", (session_id, tool_call_id))
            return StoredToolCall.from_json(row["tool_json"]) if row else None
        except Exception:
            return None

    def get_session_tool_calls(self, session_id: str) -> List[StoredToolCall]:
        try:
            rows = self._db.execute_fetchall("SELECT tool_json FROM session_tool_calls WHERE session_id = ?", (session_id,))
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
                conn.execute("INSERT OR REPLACE INTO session_streaming_content (session_id, message_id, content, expires_at) VALUES (?, ?, ?, ?)", (session_id, message_id, content, time.time() + STREAMING_CONTENT_TTL))
            return True
        except Exception as e:
            logger.error(f"Failed to save streaming content: {e}")
            return False

    def get_streaming_content(self, session_id: str, message_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT content FROM session_streaming_content WHERE session_id = ? AND message_id = ?", (session_id, message_id))
            return row["content"] if row else None
        except Exception:
            return None

    def delete_streaming_content(self, session_id: str, message_id: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM session_streaming_content WHERE session_id = ? AND message_id = ?", (session_id, message_id))
            return True
        except Exception as e:
            logger.error(f"Failed to delete streaming content: {e}")
            return False

    # ============ Persistent Process State ============

    def set_persistent_mode(self, session_id: str, enabled: bool = True) -> bool:
        return self._update_meta_fields(session_id, {"persistent_mode": 1 if enabled else 0})

    def get_persistent_mode(self, session_id: str) -> bool:
        try:
            row = self._db.execute_fetchone("SELECT persistent_mode FROM sessions WHERE id = ?", (session_id,))
            return row.get("persistent_mode") == 1 if row else False
        except Exception:
            return False

    def clear_persistent_mode(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"persistent_mode": 0})

    # ============ AGUI Event Log ============

    def append_agui_event(self, session_id: str, event: Dict[str, Any], max_len: int = 5000) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("INSERT INTO session_events (session_id, event_json, created_at) VALUES (?, ?, ?)", (session_id, json.dumps(event, ensure_ascii=False), time.time()))
                conn.execute("DELETE FROM session_events WHERE id IN (SELECT id FROM session_events WHERE session_id = ? ORDER BY id DESC LIMIT -1 OFFSET ?)", (session_id, max_len))
            return True
        except Exception as e:
            logger.error(f"Failed to append AGUI event: {e}")
            return False

    def get_agui_event_count(self, session_id: str) -> int:
        try:
            row = self._db.execute_fetchone("SELECT COUNT(*) as cnt FROM session_events WHERE session_id = ?", (session_id,))
            return row["cnt"] if row else 0
        except Exception:
            return 0

    def get_agui_events(self, session_id: str, start: int = 0, end: int = -1) -> List[Dict[str, Any]]:
        try:
            if end == -1:
                rows = self._db.execute_fetchall("SELECT event_json FROM session_events WHERE session_id = ? ORDER BY id OFFSET ?", (session_id, start))
            else:
                rows = self._db.execute_fetchall("SELECT event_json FROM session_events WHERE session_id = ? ORDER BY id LIMIT ? OFFSET ?", (session_id, end - start + 1, start))
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

    # ============ DAG Chain & Interrupted Turn Recovery ============

    def get_message_chain(self, session_id: str, message_id: str) -> List[StoredMessage]:
        """Reconstruct the DAG message chain from a message back to root.

        Follows parent_uuid links to build the ancestry chain.
        Returns messages in chronological order (root → leaf).
        """
        messages = self.get_session_messages(session_id)
        if not messages:
            return []

        # Build lookup by ID
        by_id: Dict[str, StoredMessage] = {m.id: m for m in messages}

        # Walk the chain from message_id to root
        chain: List[StoredMessage] = []
        visited: set = set()
        current_id = message_id

        while current_id and current_id not in visited:
            msg = by_id.get(current_id)
            if not msg:
                break
            chain.append(msg)
            visited.add(current_id)
            current_id = msg.parent_uuid or ""

        # Reverse to get chronological order
        chain.reverse()
        return chain

    def get_interrupted_turns(self, session_id: str) -> List[Dict[str, Any]]:
        """Find all interrupted turns in a session that can be resumed.

        An interrupted turn is identified by an assistant message with
        is_interrupted=True, or a pending tool call whose result is missing.
        """
        messages = self.get_session_messages(session_id)
        tool_calls = self.get_session_tool_calls(session_id)

        # Build tool call result map
        completed_tool_ids = {tc.id for tc in tool_calls if tc.status.value == "completed"}
        pending_tool_ids = {tc.id for tc in tool_calls if tc.status.value in ("pending", "executing")}

        interrupted: List[Dict[str, Any]] = []

        for msg in messages:
            if msg.is_interrupted and msg.role == "assistant":
                # Find pending tool calls from this interrupted message
                msg_pending = []
                if msg.tool_call_ids:
                    msg_pending = [tc_id for tc_id in msg.tool_call_ids if tc_id in pending_tool_ids]

                interrupted.append({
                    "session_id": session_id,
                    "message_id": msg.id,
                    "parent_uuid": msg.parent_uuid,
                    "reason": msg.interrupted_reason or "unknown",
                    "pending_tool_calls": msg_pending,
                    "timestamp": msg.timestamp,
                    "recoverable": True,
                })

        return interrupted

    def find_orphan_tool_results(self, session_id: str) -> List[str]:
        """Find tool result messages without a preceding assistant tool_calls.

        These can occur after context compression or interrupted turns.
        Returns list of orphan message IDs.
        """
        messages = self.get_session_messages(session_id)
        orphan_ids: List[str] = []

        # Track which tool_call_ids have been declared by assistant messages
        declared_tool_ids: set = set()

        for msg in messages:
            if msg.role == "assistant" and msg.tool_call_ids:
                declared_tool_ids.update(msg.tool_call_ids)

            if msg.role == "tool":
                # A tool message should have a tool_call_id that was declared
                # Check if it matches any declared ID
                msg_tool_ids = msg.tool_call_ids or []
                if not msg_tool_ids and msg.content:
                    # Tool result without any tool_call_id reference
                    orphan_ids.append(msg.id)

        return orphan_ids

    def mark_interrupted(self, session_id: str, message_id: str, reason: str) -> bool:
        """Mark a message as part of an interrupted turn.

        Args:
            session_id: Session ID
            message_id: The message to mark
            reason: Interruption reason (e.g. 'user_cancel', 'error')
        """
        msg = self.get_message_by_id(session_id, message_id)
        if not msg:
            return False

        msg.is_interrupted = True
        msg.interrupted_reason = reason
        return self.update_message(session_id, msg)

    def recover_interrupted_turn(self, session_id: str, message_id: str) -> Optional[List[StoredMessage]]:
        """Attempt to recover an interrupted turn by replaying the DAG chain.

        Returns the chain of messages from root to the interrupted point,
        or None if recovery is not possible.
        """
        chain = self.get_message_chain(session_id, message_id)
        if not chain:
            return None

        # Verify the last message is actually interrupted
        last = chain[-1]
        if not last.is_interrupted:
            return None

        # Check for pending tool calls that need results
        tool_calls = self.get_session_tool_calls(session_id)
        pending = [tc for tc in tool_calls
                   if tc.parent_message_id == message_id and tc.status.value in ("pending", "executing")]

        if pending:
            # Some tool calls never completed — chain is broken
            # Recovery is still possible but tool results will be missing
            logger.warning(
                "Recovering interrupted turn %s with %d pending tool calls",
                message_id, len(pending),
            )

        return chain


_session_storage: Optional[SessionStorage] = None


def get_session_storage() -> SessionStorage:
    global _session_storage
    if _session_storage is None:
        _session_storage = SessionStorage()
    return _session_storage

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from ..models.execution_binding import ExecutionBinding
from ..models.session import SessionMeta, SessionStatus, StoredMessage, StoredToolCall

logger = logging.getLogger(__name__)


class SessionExecutionBindingRepository:
    def __init__(self, db):
        self._db = db

    def defaults(
        self,
        session_id: str,
        cli_session_id: Optional[str] = None,
        provider: Optional[str] = None,
        alias: Optional[str] = None,
        exec_user: Optional[str] = None,
        work_dir: Optional[str] = None,
        source_type: Optional[str] = None,
        source_session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        session_kind: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expires_at: Optional[float] = None,
    ) -> ExecutionBinding:
        return ExecutionBinding(
            session_id=session_id,
            cli_session_id=cli_session_id,
            provider=provider,
            alias=alias,
            exec_user=exec_user,
            work_dir=work_dir,
            source_type=source_type,
            source_session_id=source_session_id,
            task_id=task_id,
            session_kind=session_kind,
            metadata=metadata or {},
            expires_at=expires_at,
        )

    def from_row(self, row: dict) -> ExecutionBinding:
        metadata: Dict[str, Any] = {}
        raw = row.get("metadata_json")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    metadata = parsed
            except Exception:
                metadata = {}
        created_at = row.get("created_at")
        updated_at = row.get("updated_at")
        return ExecutionBinding(
            session_id=row.get("session_id") or "",
            cli_session_id=row.get("cli_session_id") or None,
            session_kind=row.get("session_kind") or None,
            provider=row.get("provider") or None,
            alias=row.get("alias") or None,
            exec_user=row.get("exec_user") or None,
            work_dir=row.get("work_dir") or None,
            source_type=row.get("source_type") or None,
            source_session_id=row.get("source_session_id") or None,
            task_id=row.get("task_id") or None,
            metadata=metadata,
            created_at=int((created_at or 0) * 1000) if created_at and created_at < 1e12 else int(created_at or time.time() * 1000),
            updated_at=int((updated_at or 0) * 1000) if updated_at and updated_at < 1e12 else int(updated_at or time.time() * 1000),
            expires_at=row.get("expires_at") or None,
        )

    def get(self, session_id: str) -> Optional[ExecutionBinding]:
        try:
            row = self._db.execute_fetchone(
                "SELECT * FROM execution_bindings WHERE session_id = ?",
                (session_id,),
            )
            if not row:
                return None
            return self.from_row(row)
        except Exception as e:
            logger.debug("Failed to load execution binding for %s: %s", session_id, e)
            return None

    def upsert(self, conn, binding: ExecutionBinding) -> bool:
        if not binding.session_id:
            return False
        metadata_json = json.dumps(binding.metadata or {}, ensure_ascii=False) if binding.metadata else None
        conn.execute(
            """
            INSERT OR REPLACE INTO execution_bindings (
                session_id, cli_session_id, session_kind, provider, alias,
                exec_user, work_dir, source_type, source_session_id, task_id,
                metadata_json, created_at, updated_at, expires_at
            ) VALUES (
                :session_id, :cli_session_id, :session_kind, :provider, :alias,
                :exec_user, :work_dir, :source_type, :source_session_id, :task_id,
                :metadata_json, :created_at, :updated_at, :expires_at
            )
            """,
            {
                "session_id": binding.session_id,
                "cli_session_id": binding.cli_session_id or "",
                "session_kind": binding.session_kind or "",
                "provider": binding.provider or "",
                "alias": binding.alias or "",
                "exec_user": binding.exec_user or "",
                "work_dir": binding.work_dir or "",
                "source_type": binding.source_type or "",
                "source_session_id": binding.source_session_id or "",
                "task_id": binding.task_id or "",
                "metadata_json": metadata_json or "",
                "created_at": binding.created_at / 1000.0 if binding.created_at else time.time(),
                "updated_at": binding.updated_at / 1000.0 if binding.updated_at else time.time(),
                "expires_at": binding.expires_at,
            },
        )
        return True


class SessionMetaRepository:
    def __init__(self, db, bindings: SessionExecutionBindingRepository):
        self._db = db
        self._bindings = bindings

    def ensure_row(self, session_id: str) -> None:
        row = self._db.execute_fetchone("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if row:
            return
        now_ms = int(time.time() * 1000)
        self.save(
            SessionMeta(
                id=session_id,
                thread_id=session_id,
                title="New Session",
                username="",
                status=SessionStatus.IDLE,
                created_at=now_ms,
                updated_at=now_ms,
            )
        )

    def from_row(self, row: dict) -> SessionMeta:
        created_ts = row.get("created_at")
        created_at_ms = int(created_ts * 1000) if created_ts else int(time.time() * 1000)
        meta = SessionMeta(
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
            archived_at=int(row.get("archived_at")) if row.get("archived_at") not in (None, "") else None,
            created_at=created_at_ms,
            updated_at=row.get("updated_at") or 0,
            task_id=row.get("task_id") or None,
            prior_session_id=row.get("inherited_from") or None,
            prior_work_dir=row.get("exec_dir_override") or row.get("exec_dir") or None,
        )
        binding = self._bindings.get(row["id"])
        if binding:
            meta.execution_binding = binding
            if binding.source_session_id and not meta.source_session_id:
                meta.source_session_id = binding.source_session_id
            if binding.source_type and not meta.source:
                meta.source = binding.source_type
            if binding.session_kind and not meta.session_kind:
                meta.session_kind = binding.session_kind
            if binding.task_id and not meta.task_id:
                meta.task_id = binding.task_id
            if binding.cli_session_id and not getattr(meta, "cli_session_id", None):
                meta.cli_session_id = binding.cli_session_id
            if binding.cli_session_id and not getattr(meta, "claude_session_id", None):
                meta.claude_session_id = binding.cli_session_id
            if binding.provider and not getattr(meta, "provider", None):
                meta.provider = binding.provider
            if binding.alias and not getattr(meta, "alias", None):
                meta.alias = binding.alias
            if binding.exec_user and not getattr(meta, "exec_user", None):
                meta.exec_user = binding.exec_user
            if binding.work_dir and not getattr(meta, "exec_dir", None):
                meta.exec_dir = binding.work_dir
        if not meta.session_kind:
            if str(meta.id).startswith("task_") or meta.source == "task" or meta.task_id:
                meta.session_kind = "task"
            elif meta.source == "history" or str(row.get("inherited_from") or "").startswith("history:"):
                meta.session_kind = "chat"
            else:
                meta.session_kind = "chat"
        if not getattr(meta, "prior_session_id", None) and getattr(meta, "source_session_id", None):
            meta.prior_session_id = meta.source_session_id
        if not getattr(meta, "prior_work_dir", None) and getattr(meta, "exec_dir", None):
            meta.prior_work_dir = meta.exec_dir
        return meta

    def get(self, session_id: str) -> Optional[SessionMeta]:
        row = self._db.execute_fetchone("SELECT * FROM sessions WHERE id = ?", (session_id,))
        return self.from_row(row) if row else None

    def save(self, meta: SessionMeta) -> bool:
        session_id = (meta.id or "").strip()
        if not session_id:
            logger.warning("Skip saving session meta with empty id")
            return False
        meta.id = session_id
        if not (meta.thread_id or "").strip():
            meta.thread_id = session_id
        if getattr(meta, "prior_session_id", None) and not getattr(meta, "source_session_id", None):
            meta.source_session_id = meta.prior_session_id
        if getattr(meta, "prior_work_dir", None) and not getattr(meta, "exec_dir", None):
            meta.exec_dir = meta.prior_work_dir

        updated_at = int(getattr(meta, "updated_at", 0) or int(time.time() * 1000))
        expires_at = time.time() + 7 * 24 * 60 * 60

        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions (
                    id, thread_id, title, username, agent_name, workspace,
                    exec_dir, exec_dir_override, status, message_count,
                    provider, model, cli_session_id, claude_session_id,
                    session_exec_user, exec_user_switched, session_cleared,
                    target_session_id, workspace_provider, workspace_alias,
                    task_id, persistent_mode, archived_at,
                    created_at, updated_at, expires_at
                ) VALUES (
                    :id, :thread_id, :title, :username, :agent_name, :workspace,
                    :exec_dir, :exec_dir_override, :status, :message_count,
                    :provider, :model, :cli_session_id, :claude_session_id,
                    :session_exec_user, :exec_user_switched, :session_cleared,
                    :target_session_id, :workspace_provider, :workspace_alias,
                    :task_id, :persistent_mode, :archived_at,
                    :created_at, :updated_at, :expires_at
                )
                """,
                {
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
                    "task_id": getattr(meta, "task_id", None) or None,
                    "persistent_mode": 0,
                    "archived_at": getattr(meta, "archived_at", None),
                    "created_at": meta.created_at / 1000.0 if isinstance(meta.created_at, (int, float)) and meta.created_at else time.time(),
                    "updated_at": updated_at,
                    "expires_at": expires_at,
                },
            )
            try:
                binding = meta.to_execution_binding()
                existing_binding = self._bindings.get(meta.id)
                if existing_binding:
                    for field in (
                        "cli_session_id",
                        "provider",
                        "alias",
                        "exec_user",
                        "work_dir",
                        "source_type",
                        "source_session_id",
                        "task_id",
                        "expires_at",
                    ):
                        if not getattr(binding, field, None) and getattr(existing_binding, field, None):
                            setattr(binding, field, getattr(existing_binding, field))
                    if meta.session_kind is None and not meta.task_id and existing_binding.session_kind:
                        binding.session_kind = existing_binding.session_kind
                    if not binding.metadata and existing_binding.metadata:
                        binding.metadata = existing_binding.metadata
                    binding.created_at = existing_binding.created_at or binding.created_at
                self._bindings.upsert(conn, binding)
            except Exception as binding_err:
                logger.debug("Failed to persist execution binding for session %s: %s", meta.id, binding_err)
        return True

    def update_fields(self, session_id: str, fields: dict) -> bool:
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
                conn.execute(f"UPDATE sessions SET {', '.join(set_parts)} WHERE id = ?", values)
            return True
        except Exception as e:
            logger.error("Failed to update session meta fields: %s", e)
            return False

    def list_sessions(
        self,
        *,
        username: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        status_filter: Optional[SessionStatus] = None,
    ) -> Tuple[List[SessionMeta], int]:
        conditions = []
        params: List[Any] = []
        if username is not None:
            conditions.append("username = ?")
            params.append(username)
        if search:
            conditions.append("title LIKE ?")
            params.append(f"%{search}%")
        if status_filter:
            conditions.append("status = ?")
            params.append(status_filter.value)
        where = " AND ".join(conditions) if conditions else "1=1"
        count_row = self._db.execute_fetchone(f"SELECT COUNT(*) as cnt FROM sessions WHERE {where}", tuple(params))
        total = count_row["cnt"] if count_row else 0
        rows = self._db.execute_fetchall(
            f"SELECT * FROM sessions WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            tuple(params + [page_size, (page - 1) * page_size]),
        )
        return [self.from_row(r) for r in rows], total

    def list_archived(self, page: int = 1, page_size: int = 20, search: Optional[str] = None) -> Tuple[List[SessionMeta], int]:
        return self.list_sessions(
            page=page,
            page_size=page_size,
            search=search,
            status_filter=SessionStatus.ARCHIVED,
        )

    def get_all_usernames(self) -> List[str]:
        try:
            rows = self._db.execute_fetchall("SELECT DISTINCT username FROM sessions WHERE username IS NOT NULL AND username != ''")
            return sorted([r["username"] for r in rows])
        except Exception as e:
            logger.error("Failed to get usernames: %s", e)
            return []

    def delete(self, session_id: str) -> bool:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM session_tool_calls WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM session_events WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM session_streaming_content WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM execution_bindings WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return True


class SessionHistoryRepository:
    def __init__(self, db):
        self._db = db

    def _history_mapping_key(self, provider: str, history_session_id: str, project_path: str) -> tuple[str, str, str]:
        project_hash = hashlib.sha1((project_path or "").encode("utf-8")).hexdigest()
        return provider, history_session_id, project_hash

    def set_runtime_mapping(self, provider: str, history_session_id: str, project_path: str, runtime_session_id: str, ttl_seconds: int) -> bool:
        try:
            key_parts = self._history_mapping_key(provider, history_session_id, project_path)
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO history_mappings (provider, history_session_id, project_hash, runtime_session_id, expires_at) VALUES (?, ?, ?, ?, ?)",
                    (*key_parts, runtime_session_id, time.time() + ttl_seconds),
                )
            return True
        except Exception as e:
            logger.error("Failed to set history runtime mapping: %s", e)
            return False

    def get_runtime_mapping(self, provider: str, history_session_id: str, project_path: str) -> Optional[str]:
        try:
            key_parts = self._history_mapping_key(provider, history_session_id, project_path)
            row = self._db.execute_fetchone(
                "SELECT runtime_session_id FROM history_mappings WHERE provider = ? AND history_session_id = ? AND project_hash = ?",
                key_parts,
            )
            return row["runtime_session_id"] if row else None
        except Exception as e:
            logger.error("Failed to get history runtime mapping: %s", e)
            return None

    def hide(self, session_id: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("INSERT OR IGNORE INTO history_hidden (session_id) VALUES (?)", (session_id,))
            return True
        except Exception as e:
            logger.error("Failed to hide history session: %s", e)
            return False

    def unhide(self, session_id: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM history_hidden WHERE session_id = ?", (session_id,))
            return True
        except Exception as e:
            logger.error("Failed to unhide history session: %s", e)
            return False

    def is_hidden(self, session_id: str) -> bool:
        try:
            row = self._db.execute_fetchone("SELECT 1 FROM history_hidden WHERE session_id = ?", (session_id,))
            return row is not None
        except Exception:
            return False

    def list_hidden(self) -> set:
        try:
            rows = self._db.execute_fetchall("SELECT session_id FROM history_hidden")
            return {r["session_id"] for r in rows}
        except Exception:
            return set()


class SessionMessageRepository:
    def __init__(self, db):
        self._db = db

    def add(self, session_id: str, message: StoredMessage) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT INTO session_messages (session_id, msg_id, role, content, msg_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, message.id, message.role, message.content, message.to_json(), time.time()),
                )
                conn.execute("UPDATE sessions SET message_count = message_count + 1, updated_at = ? WHERE id = ?", (int(time.time() * 1000), session_id))
            return True
        except Exception as e:
            logger.error("Failed to add session message: %s", e)
            return False

    def update(self, session_id: str, message: StoredMessage) -> bool:
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    "UPDATE session_messages SET role = ?, content = ?, msg_json = ? WHERE session_id = ? AND msg_id = ?",
                    (message.role, message.content, message.to_json(), session_id, message.id),
                )
            return bool(getattr(cursor, "rowcount", 0))
        except Exception as e:
            logger.error("Failed to update message: %s", e)
            return False

    def list(self, session_id: str) -> List[StoredMessage]:
        try:
            rows = self._db.execute_fetchall("SELECT msg_json FROM session_messages WHERE session_id = ? ORDER BY id", (session_id,))
            messages: List[StoredMessage] = []
            for row in rows:
                try:
                    messages.append(StoredMessage.from_json(row["msg_json"]))
                except Exception:
                    continue
            return messages
        except Exception as e:
            logger.error("Failed to get session messages: %s", e)
            return []

    def get(self, session_id: str, message_id: str) -> Optional[StoredMessage]:
        try:
            row = self._db.execute_fetchone("SELECT msg_json FROM session_messages WHERE session_id = ? AND msg_id = ?", (session_id, message_id))
            return StoredMessage.from_json(row["msg_json"]) if row else None
        except Exception:
            return None

    def clear(self, session_id: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
                conn.execute("UPDATE sessions SET message_count = 0 WHERE id = ?", (session_id,))
            return True
        except Exception as e:
            logger.error("Failed to clear session messages: %s", e)
            return False


class SessionToolCallRepository:
    def __init__(self, db):
        self._db = db

    def save(self, session_id: str, tool_call: StoredToolCall) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("INSERT OR REPLACE INTO session_tool_calls (call_id, session_id, tool_json) VALUES (?, ?, ?)", (tool_call.id, session_id, tool_call.to_json()))
            return True
        except Exception as e:
            logger.error("Failed to save tool call: %s", e)
            return False

    def get(self, session_id: str, tool_call_id: str) -> Optional[StoredToolCall]:
        try:
            row = self._db.execute_fetchone("SELECT tool_json FROM session_tool_calls WHERE session_id = ? AND call_id = ?", (session_id, tool_call_id))
            return StoredToolCall.from_json(row["tool_json"]) if row else None
        except Exception:
            return None

    def list(self, session_id: str) -> List[StoredToolCall]:
        try:
            rows = self._db.execute_fetchall("SELECT tool_json FROM session_tool_calls WHERE session_id = ?", (session_id,))
            calls: List[StoredToolCall] = []
            for row in rows:
                try:
                    calls.append(StoredToolCall.from_json(row["tool_json"]))
                except Exception:
                    continue
            calls.sort(key=lambda x: x.start_time)
            return calls
        except Exception as e:
            logger.error("Failed to get session tool calls: %s", e)
            return []

    def clear(self, session_id: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM session_tool_calls WHERE session_id = ?", (session_id,))
            return True
        except Exception as e:
            logger.error("Failed to clear session tool calls: %s", e)
            return False


class SessionStreamingContentRepository:
    def __init__(self, db):
        self._db = db

    def save(self, session_id: str, message_id: str, content: str, ttl_seconds: int) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO session_streaming_content (session_id, message_id, content, expires_at) VALUES (?, ?, ?, ?)",
                    (session_id, message_id, content, time.time() + ttl_seconds),
                )
            return True
        except Exception as e:
            logger.error("Failed to save streaming content: %s", e)
            return False

    def get(self, session_id: str, message_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT content FROM session_streaming_content WHERE session_id = ? AND message_id = ?", (session_id, message_id))
            return row["content"] if row else None
        except Exception:
            return None

    def delete(self, session_id: str, message_id: str) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM session_streaming_content WHERE session_id = ? AND message_id = ?", (session_id, message_id))
            return True
        except Exception as e:
            logger.error("Failed to delete streaming content: %s", e)
            return False


class SessionEventRepository:
    def __init__(self, db):
        self._db = db

    def append(self, session_id: str, event: Dict[str, Any], max_len: int = 5000) -> bool:
        try:
            with self._db.transaction() as conn:
                conn.execute("INSERT INTO session_events (session_id, event_json, created_at) VALUES (?, ?, ?)", (session_id, json.dumps(event, ensure_ascii=False), time.time()))
                conn.execute("DELETE FROM session_events WHERE id IN (SELECT id FROM session_events WHERE session_id = ? ORDER BY id DESC LIMIT -1 OFFSET ?)", (session_id, max_len))
            return True
        except Exception as e:
            logger.error("Failed to append AGUI event: %s", e)
            return False

    def count(self, session_id: str) -> int:
        try:
            row = self._db.execute_fetchone("SELECT COUNT(*) as cnt FROM session_events WHERE session_id = ?", (session_id,))
            return row["cnt"] if row else 0
        except Exception:
            return 0

    def list(self, session_id: str, start: int = 0, end: int = -1) -> List[Dict[str, Any]]:
        try:
            if end == -1:
                rows = self._db.execute_fetchall("SELECT event_json FROM session_events WHERE session_id = ? ORDER BY id LIMIT -1 OFFSET ?", (session_id, start))
            else:
                rows = self._db.execute_fetchall("SELECT event_json FROM session_events WHERE session_id = ? ORDER BY id LIMIT ? OFFSET ?", (session_id, end - start + 1, start))
            out: List[Dict[str, Any]] = []
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

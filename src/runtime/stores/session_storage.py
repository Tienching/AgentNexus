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
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from contextlib import contextmanager

from ..models.session import (
    SessionMeta,
    SessionStatus,
    StoredMessage,
    StoredToolCall,
)
from ..models.execution_binding import ExecutionBinding
from .db import Database, get_db
from .session_repositories import (
    SessionEventRepository,
    SessionExecutionBindingRepository,
    SessionHistoryRepository,
    SessionMessageRepository,
    SessionMetaRepository,
    SessionStreamingContentRepository,
    SessionToolCallRepository,
)

logger = logging.getLogger(__name__)

SESSION_TTL = 7 * 24 * 60 * 60
STREAMING_CONTENT_TTL = 60 * 60


def _emit_session_domain_event(
    event_type: str,
    meta: SessionMeta,
    *,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        from src.server.services.domain_events import record_domain_event

        record_domain_event(
            event_type=event_type,
            aggregate_type="session",
            aggregate_id=str(meta.id),
            actor=str(getattr(meta, "exec_user", None) or getattr(meta, "username", None) or "system"),
            payload=payload or {},
            workspace_id=str(getattr(meta, "workspace", None) or "") or None,
            tenant_id=str(getattr(meta, "tenant_id", None) or "") or None,
            session_id=str(meta.id),
        )
    except Exception:
        pass


class _EphemeralSessionDatabase:
    """Small per-instance SQLite wrapper used for legacy mock-Redis tests."""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._run_migrations()

    @contextmanager
    def conn(self):
        yield self._conn

    @contextmanager
    def transaction(self):
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def execute_fetchall(self, sql: str, params: tuple = ()) -> List[dict]:
        cursor = self._conn.execute(sql, params)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def execute_fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        cursor = self._conn.execute(sql, params)
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return dict(zip(columns, row))

    def _run_migrations(self) -> None:
        from .migrations import get_all_migrations

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _schema_version (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at REAL NOT NULL
            )
            """
        )
        applied = {
            row[0]
            for row in self._conn.execute("SELECT version FROM _schema_version").fetchall()
        }
        for migration in sorted(get_all_migrations(), key=lambda m: m["version"]):
            if migration["version"] in applied:
                continue
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                migration["up"](self._conn)
                self._conn.execute(
                    "INSERT INTO _schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                    (migration["version"], migration["name"], time.time()),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise


class SessionStorage:
    """Session storage service using SQLite."""

    def __init__(self, db: Optional[Database] = None, redis_client=None):
        if db is not None:
            self._db = db
        elif redis_client is not None:
            # Unit tests that inject a mock Redis client historically expected
            # a fresh isolated backing store for each SessionStorage instance.
            self._db = _EphemeralSessionDatabase()
        else:
            self._db = get_db()
        # Optional legacy compatibility backend used by older tests and
        # transitional call-sites that still inspect Redis-style side effects.
        self._redis = redis_client
        self.bindings = SessionExecutionBindingRepository(self._db)
        self.sessions = SessionMetaRepository(self._db, self.bindings)
        self.history = SessionHistoryRepository(self._db)
        self.messages = SessionMessageRepository(self._db)
        self.tool_calls = SessionToolCallRepository(self._db)
        self.streaming = SessionStreamingContentRepository(self._db)
        self.events = SessionEventRepository(self._db)
        self._ensure_optional_columns()

    def _ensure_optional_columns(self) -> None:
        """Best-effort column migrations for older databases."""
        try:
            rows = self._db.execute_fetchall("PRAGMA table_info(sessions)")
        except Exception:
            rows = []
        columns = {row.get("name") for row in rows}
        if "archived_at" not in columns:
            try:
                self._db.execute("ALTER TABLE sessions ADD COLUMN archived_at INTEGER")
            except Exception:
                pass

    def _redis_session_meta_key(self, session_id: str) -> str:
        return f"session:{session_id}:meta"

    def _redis_user_sessions_key(self, username: str) -> str:
        return f"user:{username}:sessions"

    def _redis_all_sessions_key(self) -> str:
        return "sessions:all"

    def _sync_redis_session_meta(
        self,
        meta: SessionMeta,
        *,
        previous_username: Optional[str] = None,
    ) -> None:
        """Mirror session metadata into the optional legacy Redis layout."""
        if self._redis is None or not meta.id:
            return

        try:
            payload = meta.to_redis_hash()
            key = self._redis_session_meta_key(meta.id)
            self._redis.hset(key, mapping=payload)
            try:
                self._redis.expire(key, SESSION_TTL)
            except Exception:
                pass

            score = float(payload.get("updated_at") or payload.get("created_at") or int(time.time() * 1000))
            self._redis.zadd(self._redis_all_sessions_key(), {meta.id: score})

            username = (meta.username or "").strip()
            if previous_username and previous_username != username:
                try:
                    self._redis.zrem(self._redis_user_sessions_key(previous_username), meta.id)
                except Exception:
                    pass
            if username:
                self._redis.zadd(self._redis_user_sessions_key(username), {meta.id: score})
        except Exception as e:
            logger.debug(f"Failed to sync legacy Redis meta for {meta.id}: {e}")

    def _cleanup_legacy_redis_session_indexes(self) -> None:
        """Best-effort cleanup of malformed compatibility entries."""
        if self._redis is None:
            return
        try:
            self._redis.zrem(self._redis_all_sessions_key(), "")
        except Exception:
            pass
        try:
            self._redis.delete(self._redis_session_meta_key(""))
        except Exception:
            pass

    def _load_meta_from_redis_compat(self, session_id: str) -> Optional[SessionMeta]:
        """Read a session from the legacy Redis layout when SQLite misses."""
        if self._redis is None or not session_id:
            return None
        try:
            raw = self._redis.hgetall(self._redis_session_meta_key(session_id)) or {}
        except Exception:
            raw = {}
        if not raw:
            return None

        if not raw.get("id"):
            raw["id"] = session_id
        if not raw.get("thread_id"):
            raw["thread_id"] = session_id

        try:
            meta = SessionMeta.from_redis_hash(raw)
        except Exception:
            return None

        # Self-heal both the SQLite row and the Redis hash.
        self.save_session_meta(meta)
        return meta

    def _delete_redis_compat_session(self, session_id: str, username: Optional[str] = None) -> None:
        if self._redis is None or not session_id:
            return
        try:
            resolved_username = (username or "").strip()
            if not resolved_username:
                try:
                    raw = self._redis.hgetall(self._redis_session_meta_key(session_id)) or {}
                    resolved_username = (raw.get("username") or "").strip()
                except Exception:
                    resolved_username = ""
            self._redis.delete(
                self._redis_session_meta_key(session_id),
                f"session:{session_id}:messages",
                f"session:{session_id}:events",
                f"session:{session_id}:streaming",
            )
            self._redis.zrem(self._redis_all_sessions_key(), session_id)
            if resolved_username:
                self._redis.zrem(self._redis_user_sessions_key(resolved_username), session_id)
        except Exception as e:
            logger.debug(f"Failed to delete legacy Redis session compat keys for {session_id}: {e}")

    def _ensure_session_row(self, session_id: str) -> None:
        self.sessions.ensure_row(session_id)

    def _merge_execution_binding(self, binding: Optional[ExecutionBinding], meta: Optional[SessionMeta]) -> Optional[ExecutionBinding]:
        """Merge legacy session columns into an execution binding."""
        if not binding and not meta:
            return None

        if binding is None and meta is not None:
            try:
                binding = meta.to_execution_binding()
            except Exception:
                binding = self._execution_binding_defaults(session_id=meta.id)

        if binding is None:
            return None

        if meta is not None:
            if not binding.cli_session_id and getattr(meta, "cli_session_id", None):
                binding.cli_session_id = meta.cli_session_id
            if not binding.provider and getattr(meta, "provider", None):
                binding.provider = meta.provider
            if not binding.alias and getattr(meta, "alias", None):
                binding.alias = meta.alias
            if not binding.exec_user and getattr(meta, "exec_user", None):
                binding.exec_user = meta.exec_user
            if not binding.work_dir and getattr(meta, "exec_dir", None):
                binding.work_dir = meta.exec_dir
            if not binding.source_session_id and getattr(meta, "source_session_id", None):
                binding.source_session_id = meta.source_session_id
            if not binding.source_type and getattr(meta, "source", None):
                binding.source_type = meta.source
            if not binding.task_id and getattr(meta, "task_id", None):
                binding.task_id = meta.task_id
            if not binding.session_kind and getattr(meta, "session_kind", None):
                binding.session_kind = meta.session_kind
        return binding

    def get_effective_execution_binding(self, session_id: str) -> Optional[ExecutionBinding]:
        """Return the best available execution binding for a session."""
        try:
            meta = self.get_session_meta(session_id)
        except Exception:
            meta = None

        try:
            binding = self.get_execution_binding(session_id)
        except Exception:
            binding = None

        return self._merge_execution_binding(binding, meta)

    def _execution_binding_defaults(
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
        return self.bindings.defaults(
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
            metadata=metadata,
            expires_at=expires_at,
        )

    def _binding_row_to_model(self, row: dict) -> ExecutionBinding:
        return self.bindings.from_row(row)

    def _get_execution_binding_row(self, session_id: str) -> Optional[ExecutionBinding]:
        return self.bindings.get(session_id)

    def _upsert_execution_binding(self, conn, binding: ExecutionBinding) -> bool:
        return self.bindings.upsert(conn, binding)

    def upsert_execution_binding(
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
    ) -> bool:
        try:
            now_ms = int(time.time() * 1000)
            existing = self._get_execution_binding_row(session_id)
            binding = self._execution_binding_defaults(
                session_id=session_id,
                cli_session_id=cli_session_id if cli_session_id is not None else getattr(existing, "cli_session_id", None),
                provider=provider if provider is not None else getattr(existing, "provider", None),
                alias=alias if alias is not None else getattr(existing, "alias", None),
                exec_user=exec_user if exec_user is not None else getattr(existing, "exec_user", None),
                work_dir=work_dir if work_dir is not None else getattr(existing, "work_dir", None),
                source_type=source_type if source_type is not None else getattr(existing, "source_type", None),
                source_session_id=source_session_id if source_session_id is not None else getattr(existing, "source_session_id", None),
                task_id=task_id if task_id is not None else getattr(existing, "task_id", None),
                session_kind=session_kind if session_kind is not None else getattr(existing, "session_kind", None),
                metadata=metadata if metadata is not None else getattr(existing, "metadata", None) or {},
                expires_at=expires_at if expires_at is not None else getattr(existing, "expires_at", None),
            )
            binding.created_at = getattr(existing, "created_at", now_ms) or now_ms
            binding.updated_at = now_ms
            with self._db.transaction() as conn:
                self._upsert_execution_binding(conn, binding)
            return True
        except Exception as e:
            logger.error(f"Failed to upsert execution binding for {session_id}: {e}")
            return False

    def bind_execution_context(
        self,
        session_id: str,
        *,
        cli_session_id: Optional[str] = None,
        provider: Optional[str] = None,
        alias: Optional[str] = None,
        exec_user: Optional[str] = None,
        work_dir: Optional[str] = None,
        exec_dir_override: Optional[str] = None,
        source_type: Optional[str] = None,
        source_session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        session_kind: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expires_at: Optional[float] = None,
    ) -> bool:
        """Bind a session to a CLI execution context."""
        try:
            self._ensure_session_row(session_id)

            fields: Dict[str, Any] = {}
            if cli_session_id is not None:
                fields["cli_session_id"] = cli_session_id
                fields["claude_session_id"] = cli_session_id
            if provider is not None:
                fields["provider"] = provider
            if exec_user is not None:
                fields["session_exec_user"] = exec_user
                fields["username"] = exec_user
            if work_dir is not None:
                fields["exec_dir"] = work_dir
            if exec_dir_override is not None:
                fields["exec_dir_override"] = exec_dir_override
            if source_session_id is not None:
                if source_type == "history":
                    fields["inherited_from"] = f"history:{provider or alias or ''}:{source_session_id}"
                else:
                    fields["inherited_from"] = source_session_id
            if task_id is not None:
                fields["task_id"] = task_id

            if fields:
                updated = self._update_meta_fields(session_id, fields)
                if not updated:
                    return False

            binding_updated = self.upsert_execution_binding(
                session_id,
                cli_session_id=cli_session_id,
                provider=provider,
                alias=alias,
                exec_user=exec_user,
                work_dir=work_dir if work_dir is not None else exec_dir_override,
                source_type=source_type,
                source_session_id=source_session_id,
                task_id=task_id,
                session_kind=session_kind,
                metadata=metadata,
                expires_at=expires_at,
            )
            return bool(binding_updated)
        except Exception as e:
            logger.error(f"Failed to bind execution context for {session_id}: {e}")
            return False

    def get_execution_binding(self, session_id: str) -> Optional[ExecutionBinding]:
        return self._get_execution_binding_row(session_id)

    def clear_execution_binding_fields(self, session_id: str, *fields: str) -> bool:
        allowed_columns = {
            "cli_session_id": "cli_session_id",
            "provider": "provider",
            "alias": "alias",
            "work_dir": "work_dir",
            "source_type": "source_type",
            "source_session_id": "source_session_id",
            "task_id": "task_id",
            "metadata": "metadata_json",
        }
        columns = [allowed_columns[field] for field in dict.fromkeys(fields) if field in allowed_columns]
        if not columns:
            return True
        try:
            assignments = ", ".join(f"{column} = ''" for column in columns)
            with self._db.transaction() as conn:
                conn.execute(
                    f"UPDATE execution_bindings SET {assignments}, updated_at = ? WHERE session_id = ?",
                    (time.time(), session_id),
                )
            return True
        except Exception as e:
            logger.error(f"Failed to clear execution binding fields for {session_id}: {e}")
            return False

    # ============ Session Metadata Operations ============

    def save_session_meta(self, meta: SessionMeta) -> bool:
        try:
            session_id = (meta.id or "").strip()
            existing = None
            try:
                existing = self.get_session_meta(session_id)
            except Exception:
                existing = None
            if not self.sessions.save(meta):
                return False

            previous_username = (getattr(existing, "username", None) or "").strip() or None
            self._sync_redis_session_meta(meta, previous_username=previous_username)
            if getattr(meta, "prior_session_id", None):
                prior_session_id = str(meta.prior_session_id).strip()
                if prior_session_id:
                    self.set_inherited_session(session_id, prior_session_id)
            if getattr(meta, "prior_work_dir", None):
                self.set_exec_dir_override(session_id, meta.prior_work_dir)
            logger.debug(f"Saved session meta: {meta.id}")
            _emit_session_domain_event(
                "session.created" if existing is None else "session.updated",
                meta,
                payload={
                    "title": meta.title,
                    "status": meta.status.value if isinstance(meta.status, SessionStatus) else str(meta.status),
                    "prior_session_id": getattr(meta, "prior_session_id", None),
                    "prior_work_dir": getattr(meta, "prior_work_dir", None),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save session meta: {e}")
            return False

    def get_session_meta(self, session_id: str) -> Optional[SessionMeta]:
        try:
            meta = self.sessions.get(session_id)
            if not meta:
                return self._load_meta_from_redis_compat(session_id)
            return meta
        except Exception as e:
            logger.error(f"Failed to get session meta: {e}")
            return None

    def _row_to_meta(self, row: dict) -> SessionMeta:
        return self.sessions.from_row(row)

    def _update_meta_fields(self, session_id: str, fields: dict) -> bool:
        return self.sessions.update_fields(session_id, fields)

    # ---- History Session Hidden ----

    def _history_mapping_key(self, provider: str, history_session_id: str, project_path: str) -> str:
        project_hash = hashlib.sha1((project_path or "").encode("utf-8")).hexdigest()
        return f"{provider}:{history_session_id}:{project_hash}"

    def set_history_runtime_mapping(self, provider: str, history_session_id: str, project_path: str, runtime_session_id: str) -> bool:
        return self.history.set_runtime_mapping(provider, history_session_id, project_path, runtime_session_id, SESSION_TTL)

    def get_history_runtime_mapping(self, provider: str, history_session_id: str, project_path: str) -> Optional[str]:
        return self.history.get_runtime_mapping(provider, history_session_id, project_path)

    def hide_history_session(self, session_id: str) -> bool:
        return self.history.hide(session_id)

    def unhide_history_session(self, session_id: str) -> bool:
        return self.history.unhide(session_id)

    def is_history_session_hidden(self, session_id: str) -> bool:
        return self.history.is_hidden(session_id)

    def get_hidden_history_sessions(self) -> set:
        return self.history.list_hidden()

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
        updated = self._update_meta_fields(session_id, {"inherited_from": inherited_from})
        source_session_id = inherited_from
        source_type = "runtime"
        if inherited_from.startswith("history:"):
            parts = inherited_from.split(":", 2)
            if len(parts) >= 3:
                source_session_id = parts[2]
            source_type = "history"
        self.upsert_execution_binding(session_id, source_session_id=source_session_id, source_type=source_type)
        return updated

    def get_inherited_session(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT inherited_from FROM sessions WHERE id = ?", (session_id,))
            return row.get("inherited_from") if row else None
        except Exception:
            return None

    def clear_inherited_session(self, session_id: str) -> bool:
        updated = self._update_meta_fields(session_id, {"inherited_from": None})
        self.clear_execution_binding_fields(session_id, "source_session_id", "source_type")
        return updated

    def set_exec_dir_override(self, session_id: str, exec_dir: str) -> bool:
        updated = self._update_meta_fields(session_id, {"exec_dir_override": exec_dir, "exec_dir": exec_dir})
        self.upsert_execution_binding(session_id, work_dir=exec_dir)
        return updated

    def get_exec_dir_override(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT exec_dir_override FROM sessions WHERE id = ?", (session_id,))
            if row and row.get("exec_dir_override"):
                return row.get("exec_dir_override")
            binding = self.get_effective_execution_binding(session_id)
            if binding and binding.work_dir:
                return binding.work_dir
            return None
        except Exception:
            return None

    def clear_exec_dir_override(self, session_id: str) -> bool:
        updated = self._update_meta_fields(session_id, {"exec_dir_override": None, "exec_dir": None})
        self.clear_execution_binding_fields(session_id, "work_dir")
        return updated

    def get_session_exec_user(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT session_exec_user FROM sessions WHERE id = ?", (session_id,))
            if row:
                user = (row.get("session_exec_user") or "").strip()
                if user:
                    return user
            binding = self.get_effective_execution_binding(session_id)
            if binding and binding.exec_user:
                return (binding.exec_user or "").strip() or None
            return None
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
            self.upsert_execution_binding(session_id, exec_user=normalized)
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
        updated = self._update_meta_fields(session_id, {"workspace_provider": provider})
        self.upsert_execution_binding(session_id, provider=provider)
        return updated

    def get_workspace_provider(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT workspace_provider FROM sessions WHERE id = ?", (session_id,))
            if row and row.get("workspace_provider"):
                return row.get("workspace_provider")
            binding = self.get_effective_execution_binding(session_id)
            if binding and binding.provider:
                return binding.provider
            return None
        except Exception:
            return None

    def clear_workspace_provider(self, session_id: str) -> bool:
        updated = self._update_meta_fields(session_id, {"workspace_provider": None})
        self.clear_execution_binding_fields(session_id, "provider")
        return updated

    def set_workspace_alias(self, session_id: str, alias: str) -> bool:
        updated = self._update_meta_fields(session_id, {"workspace_alias": alias})
        self.upsert_execution_binding(session_id, alias=alias)
        return updated

    def get_workspace_alias(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT workspace_alias FROM sessions WHERE id = ?", (session_id,))
            if row and row.get("workspace_alias"):
                return row.get("workspace_alias")
            binding = self.get_effective_execution_binding(session_id)
            if binding and binding.alias:
                return binding.alias
            return None
        except Exception:
            return None

    def clear_workspace_alias(self, session_id: str) -> bool:
        updated = self._update_meta_fields(session_id, {"workspace_alias": None})
        self.clear_execution_binding_fields(session_id, "alias")
        return updated

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
        self._ensure_session_row(session_id)
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
        self._ensure_session_row(session_id)
        updated = self._update_meta_fields(session_id, {"cli_session_id": cli_session_id, "claude_session_id": cli_session_id})
        self.upsert_execution_binding(session_id, cli_session_id=cli_session_id)
        return updated

    def get_cli_session_id(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT cli_session_id, claude_session_id FROM sessions WHERE id = ?", (session_id,))
            if row:
                cli_session_id = row.get("cli_session_id") or row.get("claude_session_id")
                if cli_session_id:
                    return cli_session_id
            binding = self.get_effective_execution_binding(session_id)
            if binding and binding.cli_session_id:
                return binding.cli_session_id
            return None
        except Exception:
            return None

    def clear_cli_session_id(self, session_id: str) -> bool:
        updated = self._update_meta_fields(session_id, {"cli_session_id": None, "claude_session_id": None})
        self.clear_execution_binding_fields(session_id, "cli_session_id")
        return updated

    def set_task_id(self, session_id: str, task_id: str) -> bool:
        self._ensure_session_row(session_id)
        updated = self._update_meta_fields(session_id, {"task_id": task_id})
        self.upsert_execution_binding(session_id, task_id=task_id)
        return updated

    def get_task_id(self, session_id: str) -> Optional[str]:
        try:
            row = self._db.execute_fetchone("SELECT task_id FROM sessions WHERE id = ?", (session_id,))
            if row and row.get("task_id"):
                return str(row["task_id"])
            binding = self.get_effective_execution_binding(session_id)
            if binding and binding.task_id:
                return binding.task_id
            return None
        except Exception:
            return None

    def clear_task_id(self, session_id: str) -> bool:
        updated = self._update_meta_fields(session_id, {"task_id": None})
        self.clear_execution_binding_fields(session_id, "task_id")
        return updated

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
            self._cleanup_legacy_redis_session_indexes()
            return self.sessions.list_sessions(
                username=username,
                page=page,
                page_size=page_size,
                search=search,
                status_filter=status_filter,
            )
        except Exception as e:
            logger.error(f"Failed to get user sessions: {e}")
            return [], 0

    def get_all_sessions(self, page: int = 1, page_size: int = 20, search: Optional[str] = None, status_filter: Optional[SessionStatus] = None) -> Tuple[List[SessionMeta], int]:
        try:
            self._cleanup_legacy_redis_session_indexes()
            return self.sessions.list_sessions(
                page=page,
                page_size=page_size,
                search=search,
                status_filter=status_filter,
            )
        except Exception as e:
            logger.error(f"Failed to get all sessions: {e}")
            return [], 0

    def get_all_usernames(self) -> List[str]:
        return self.sessions.get_all_usernames()

    def update_session_status(self, session_id: str, status: SessionStatus, update_timestamp: bool = True) -> bool:
        fields = {"status": status.value}
        if status == SessionStatus.ARCHIVED:
            fields["archived_at"] = int(time.time() * 1000)
        elif status in (SessionStatus.IDLE, SessionStatus.RUNNING, SessionStatus.COMPLETED, SessionStatus.ERROR):
            fields["archived_at"] = None
        if update_timestamp:
            fields["updated_at"] = int(time.time() * 1000)
        ok = self._update_meta_fields(session_id, fields)
        if ok:
            try:
                meta = self.get_session_meta(session_id)
                if meta:
                    _emit_session_domain_event(
                        "session.status_changed",
                        meta,
                        payload={"status": status.value},
                    )
            except Exception:
                pass
        return ok

    def archive_session(self, session_id: str) -> bool:
        """Mark a session as archived."""
        return self.update_session_status(session_id, SessionStatus.ARCHIVED)

    def restore_session(self, session_id: str) -> bool:
        """Restore an archived session back to idle."""
        return self.update_session_status(session_id, SessionStatus.IDLE)

    def get_archived_sessions(self, page: int = 1, page_size: int = 20, search: Optional[str] = None) -> Tuple[List[SessionMeta], int]:
        """List archived sessions."""
        try:
            return self.sessions.list_archived(page=page, page_size=page_size, search=search)
        except Exception as e:
            logger.error(f"Failed to get archived sessions: {e}")
            return [], 0

    def delete_session(self, session_id: str, username: Optional[str] = None) -> bool:
        try:
            meta = self.get_session_meta(session_id)
            self.sessions.delete(session_id)
            self._delete_redis_compat_session(session_id, username=username)
            logger.info(f"Deleted session: {session_id}")
            if meta:
                _emit_session_domain_event("session.deleted", meta, payload={"deleted": True})
            return True
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            return False

    # ============ Message Operations ============

    def add_session_message(self, session_id: str, message: StoredMessage) -> bool:
        try:
            self._ensure_session_row(session_id)
            return self.messages.add(session_id, message)
        except Exception as e:
            logger.error(f"Failed to add session message: {e}")
            return False

    def update_message(self, session_id: str, message: StoredMessage) -> bool:
        return self.messages.update(session_id, message)

    def get_session_messages(self, session_id: str) -> List[StoredMessage]:
        return self.messages.list(session_id)

    def get_message_by_id(self, session_id: str, message_id: str) -> Optional[StoredMessage]:
        return self.messages.get(session_id, message_id)

    def clear_session_messages(self, session_id: str) -> bool:
        return self.messages.clear(session_id)

    def clear_session_tool_calls(self, session_id: str) -> bool:
        return self.tool_calls.clear(session_id)

    # ============ Tool Call Operations ============

    def save_tool_call(self, session_id: str, tool_call: StoredToolCall) -> bool:
        try:
            self._ensure_session_row(session_id)
            return self.tool_calls.save(session_id, tool_call)
        except Exception as e:
            logger.error(f"Failed to save tool call: {e}")
            return False

    def get_tool_call(self, session_id: str, tool_call_id: str) -> Optional[StoredToolCall]:
        return self.tool_calls.get(session_id, tool_call_id)

    def get_session_tool_calls(self, session_id: str) -> List[StoredToolCall]:
        return self.tool_calls.list(session_id)

    def update_tool_call(self, session_id: str, tool_call: StoredToolCall) -> bool:
        return self.save_tool_call(session_id, tool_call)

    # ============ Streaming Content ============

    def save_streaming_content(self, session_id: str, message_id: str, content: str) -> bool:
        try:
            self._ensure_session_row(session_id)
            return self.streaming.save(session_id, message_id, content, STREAMING_CONTENT_TTL)
        except Exception as e:
            logger.error(f"Failed to save streaming content: {e}")
            return False

    def get_streaming_content(self, session_id: str, message_id: str) -> Optional[str]:
        return self.streaming.get(session_id, message_id)

    def delete_streaming_content(self, session_id: str, message_id: str) -> bool:
        return self.streaming.delete(session_id, message_id)

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

    def clear_active_model(self, session_id: str) -> bool:
        return self._update_meta_fields(session_id, {"active_model": None})

    # ============ AGUI Event Log ============

    def append_agui_event(self, session_id: str, event: Dict[str, Any], max_len: int = 5000) -> bool:
        return self.events.append(session_id, event, max_len=max_len)

    def get_agui_event_count(self, session_id: str) -> int:
        return self.events.count(session_id)

    def get_agui_events(self, session_id: str, start: int = 0, end: int = -1) -> List[Dict[str, Any]]:
        return self.events.list(session_id, start=start, end=end)

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

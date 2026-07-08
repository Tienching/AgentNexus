# -*- coding: utf-8 -*-
"""SQLite task storage for slash commands

Provides TaskQueue class for managing tasks in SQLite.
Replaces the multi-key Redis structure with a single `tasks` table
plus SQL indexes for status, project, workspace, session lookups.

Queue semantics (LPUSH/RPOP) are replaced by SELECT ... ORDER BY
with status-based filtering and atomic UPDATE within transactions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import time
import uuid
from typing import List, Optional, Dict, Any

import logging

from ..models.task_models import Task, TaskPriority, TaskStatus
from ..models.execution_binding import ExecutionBinding
from .db import Database, get_db

logger = logging.getLogger(__name__)


# Netharness layout: active = non-archived (6 statuses), terminal = completed/failed/cancelled/archived
ACTIVE_TASK_STATUSES = (
    TaskStatus.PENDING.value,
    TaskStatus.RUNNING.value,
    TaskStatus.IN_REVIEW.value,
    TaskStatus.COMPLETED.value,
    TaskStatus.FAILED.value,
    TaskStatus.CANCELLED.value,
)

TERMINAL_TASK_STATUSES = (
    TaskStatus.COMPLETED.value,
    TaskStatus.FAILED.value,
    TaskStatus.CANCELLED.value,
    TaskStatus.ARCHIVED.value,
)


class TaskLifecycleError(RuntimeError):
    """Base error for storage-level lifecycle guard violations."""


class DuplicatePendingTaskError(TaskLifecycleError):
    """Raised when an active task would duplicate an existing active session binding."""


class InvalidTaskTransitionError(TaskLifecycleError):
    """Raised when a task status transition is not allowed."""


class TaskLifecycleRaceError(TaskLifecycleError):
    """Raised when a compare-and-set lifecycle update loses a race."""


def _emit_task_domain_event(
    event_type: str,
    task: Task,
    *,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort domain event emission for task lifecycle changes."""
    try:
        from src.server.services.domain_events import record_domain_event

        record_domain_event(
            event_type=event_type,
            aggregate_type="task",
            aggregate_id=str(task.id),
            actor=str(task.exec_user or "system"),
            payload=payload or {},
            workspace_id=str(task.workspace or "") or None,
            session_id=str(getattr(task, "session_id", None) or "") or None,
            task_id=str(task.id),
        )
    except Exception:
        pass


def get_redis_client():
    """Compatibility shim for legacy tests/mocks expecting Redis client accessor."""
    return None


class _EphemeralTaskDatabase:
    """Per-instance SQLite wrapper for legacy mock-Redis tests."""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._run_migrations()

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
                    (migration["version"], migration["name"], datetime.now(timezone.utc).timestamp()),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise


def _dt_to_ts(dt) -> Optional[float]:
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _ts_to_dt(ts) -> Optional[datetime]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _task_to_row(task: Task) -> dict:
    """Convert Task model to SQLite row dict."""
    ws_hash = ""
    if task.workspace:
        ws_hash = hashlib.md5(task.workspace.encode("utf-8")).hexdigest()[:8]

    context_payload = dict(task.context or {})
    reserved_context_fields = {
        "source_session_id": task.source_session_id,
        "prior_session_id": task.prior_session_id,
        "prior_work_dir": task.prior_work_dir,
        "repo_url": task.repo_url,
        "repo_root": task.repo_root,
        "worktree_path": task.worktree_path,
        "depends_on": list(task.depends_on or []),
        "cli_session_id": task.cli_session_id,
        "session_kind": task.session_kind,
    }
    for key, value in reserved_context_fields.items():
        if value in (None, "", [], {}):
            context_payload.pop(key, None)
            continue
        context_payload[key] = value

    return {
        "id": task.id,
        "exec_user": task.exec_user or "default",
        "description": task.description,
        "priority": task.priority if isinstance(task.priority, str) else task.priority.value,
        "status": task.status if isinstance(task.status, str) else task.status.value,
        "assigned_to": task.assigned_to,
        "tags_json": json.dumps(task.tags, ensure_ascii=False) if task.tags else None,
        "due_date": _dt_to_ts(task.due_date),
        "ticket_ref": task.ticket_ref,
        "project_id": task.project_id,
        "project_name": task.project_name,
        "workspace": task.workspace,
        "workspace_hash": ws_hash,
        "session_id": task.session_id,
        "source_session_id": task.source_session_id,
        "provider": task.provider,
        "alias": task.alias,
        "model": task.model,
        "context_json": json.dumps(context_payload, ensure_ascii=False) if context_payload else None,
        "attempt_count": task.attempt_count,
        "error_message": task.error_message,
        "runtime_status": task.runtime_status if isinstance(task.runtime_status, str) else task.runtime_status.value,
        "runtime_orphaned": 1 if task.runtime_orphaned else 0,
        "runtime_orphaned_at": _dt_to_ts(task.runtime_orphaned_at),
        "runtime_last_heartbeat": _dt_to_ts(task.runtime_last_heartbeat),
        "outcome": task.outcome,
        "resolution": task.resolution,
        "feedback_rating": task.feedback_rating,
        "feedback_notes": task.feedback_notes,
        "response_url": task.response_url,
        "callback_msg_id": task.callback_msg_id,
        "callback_user": task.callback_user,
        "notification_sink_type": task.notification_sink_type,
        "notification_channel": task.notification_channel,
        "notification_chat_id": task.notification_chat_id,
        "notification_message_id": getattr(task, "notification_message_id", None),
        "loop_enabled": 1 if task.loop_enabled else 0,
        "loop_max_iterations": task.loop_max_iterations,
        "loop_iteration": task.loop_iteration,
        "loop_keywords_json": json.dumps(task.loop_keywords) if task.loop_keywords else None,
        "loop_keyword_found": 1 if task.loop_keyword_found else 0,
        "schedule_id": getattr(task, "schedule_id", None),
        "created_at": _dt_to_ts(task.created_at),
        "started_at": _dt_to_ts(task.started_at),
        "completed_at": _dt_to_ts(task.completed_at),
        "archived_at": _dt_to_ts(task.archived_at),
        "deleted_at": _dt_to_ts(task.deleted_at),
    }


def _row_to_task(row: dict) -> Task:
    """Convert SQLite row dict to Task model."""
    ctx = None
    if row.get("context_json"):
        try:
            ctx = json.loads(row["context_json"])
        except Exception:
            pass
    ctx = ctx or {}

    def _ctx_value(*keys: str):
        for key in keys:
            value = ctx.get(key)
            if value not in (None, "", [], {}):
                return value
        return None

    loop_kw = []
    if row.get("loop_keywords_json"):
        try:
            loop_kw = json.loads(row["loop_keywords_json"])
        except Exception:
            pass

    tags = []
    if row.get("tags_json"):
        try:
            tags = json.loads(row["tags_json"])
        except Exception:
            pass

    return Task(
        id=row["id"],
        description=row["description"] or "",
        priority=TaskPriority(row.get("priority", "thought")),
        status=TaskStatus.from_legacy(row.get("status", "pending")),
        assigned_to=row.get("assigned_to"),
        tags=tags,
        due_date=_ts_to_dt(row.get("due_date")),
        ticket_ref=row.get("ticket_ref"),
        project_id=row.get("project_id"),
        project_name=row.get("project_name"),
        workspace=row.get("workspace"),
        exec_user=row.get("exec_user", "default"),
        provider=row.get("provider") or "claude",
        alias=row.get("alias"),
        model=row.get("model"),
        session_id=row.get("session_id"),
        source_session_id=row.get("source_session_id") or _ctx_value("source_session_id", "prior_session_id", "inherited_from"),
        prior_session_id=_ctx_value("prior_session_id", "source_session_id", "inherited_from"),
        prior_work_dir=_ctx_value("prior_work_dir", "exec_dir_override"),
        repo_url=_ctx_value("repo_url", "github_repo"),
        repo_root=_ctx_value("repo_root"),
        worktree_path=_ctx_value("worktree_path", "workspace"),
        session_kind=_ctx_value("session_kind") or "task",
        depends_on=list(_ctx_value("depends_on") or []),
        cli_session_id=_ctx_value("cli_session_id"),
        context=ctx or None,
        attempt_count=row.get("attempt_count", 0),
        error_message=row.get("error_message"),
        runtime_status=row.get("runtime_status") or "queued",
        runtime_orphaned=bool(row.get("runtime_orphaned", 0)),
        runtime_orphaned_at=_ts_to_dt(row.get("runtime_orphaned_at")),
        runtime_last_heartbeat=_ts_to_dt(row.get("runtime_last_heartbeat")),
        outcome=row.get("outcome"),
        resolution=row.get("resolution"),
        feedback_rating=row.get("feedback_rating"),
        feedback_notes=row.get("feedback_notes"),
        response_url=row.get("response_url"),
        callback_msg_id=row.get("callback_msg_id"),
        callback_user=row.get("callback_user"),
        notification_sink_type=row.get("notification_sink_type"),
        notification_channel=row.get("notification_channel"),
        notification_chat_id=row.get("notification_chat_id"),
        loop_enabled=bool(row.get("loop_enabled", 0)),
        loop_max_iterations=row.get("loop_max_iterations", 1),
        loop_iteration=row.get("loop_iteration", 0),
        loop_keywords=loop_kw,
        loop_keyword_found=bool(row.get("loop_keyword_found", 0)),
        schedule_id=row.get("schedule_id"),
        created_at=_ts_to_dt(row.get("created_at")) or datetime.now(timezone.utc),
        started_at=_ts_to_dt(row.get("started_at")),
        completed_at=_ts_to_dt(row.get("completed_at")),
        archived_at=_ts_to_dt(row.get("archived_at")),
        deleted_at=_ts_to_dt(row.get("deleted_at")),
        execution_binding=ExecutionBinding(
            session_id=row.get("session_id") or f"task_{row['id']}",
            cli_session_id=_ctx_value("cli_session_id"),
            session_kind=_ctx_value("session_kind") or "task",
            provider=row.get("provider") or "claude",
            alias=row.get("alias"),
            exec_user=row.get("exec_user") or "default",
            work_dir=_ctx_value("worktree_path", "prior_work_dir") or row.get("workspace"),
            source_type="task",
            source_session_id=row.get("source_session_id") or _ctx_value("source_session_id", "prior_session_id", "inherited_from"),
            task_id=row["id"],
        ),
    )


_TASK_FIELDS = list(_task_to_row(Task(id="__schema__", description="__schema__")).keys())
_TASK_COLUMNS = ", ".join(_TASK_FIELDS)
_TASK_PLACEHOLDERS = ", ".join(["?"] * len(_TASK_FIELDS))


class TaskRepository:
    """Focused repository for task row CRUD and CAS-style updates."""

    def __init__(self, db: Database, *, exec_user: str):
        self._db = db
        self.exec_user = exec_user

    def insert(self, task: Task) -> Task:
        row = _task_to_row(task)
        values = [row[k] for k in _TASK_FIELDS]
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    f"INSERT INTO tasks ({_TASK_COLUMNS}) VALUES ({_TASK_PLACEHOLDERS})",
                    values,
                )
        except sqlite3.IntegrityError as exc:
            if "ux_tasks_active_session" in str(exc) or "tasks.exec_user, tasks.session_id" in str(exc):
                raise DuplicatePendingTaskError(
                    f"Active task already exists for session_id={task.session_id!r}"
                ) from exc
            raise
        return task

    def get(self, task_id: str) -> Optional[Task]:
        row = self._db.execute_fetchone(
            "SELECT * FROM tasks WHERE exec_user = ? AND id = ? LIMIT 1",
            (self.exec_user, str(task_id)),
        )
        return _row_to_task(row) if row else None

    def find_by_session_id(self, session_id: str) -> Optional[Task]:
        row = self._db.execute_fetchone(
            "SELECT * FROM tasks WHERE exec_user = ? AND session_id = ? LIMIT 1",
            (self.exec_user, session_id),
        )
        return _row_to_task(row) if row else None

    def update(self, task: Task) -> bool:
        row = _task_to_row(task)
        update_cols = [k for k in _TASK_FIELDS if k not in ("id", "exec_user")]
        set_clause = ", ".join(f"{k} = ?" for k in update_cols)
        values = [row[k] for k in update_cols] + [task.exec_user or self.exec_user, task.id]
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    f"UPDATE tasks SET {set_clause} WHERE exec_user = ? AND id = ?",
                    values,
                )
            return bool(getattr(cursor, "rowcount", 0))
        except sqlite3.IntegrityError as exc:
            if "invalid_task_status_transition" in str(exc):
                raise InvalidTaskTransitionError(str(exc)) from exc
            if "ux_tasks_active_session" in str(exc) or "tasks.exec_user, tasks.session_id" in str(exc):
                raise DuplicatePendingTaskError(
                    f"Active task already exists for session_id={task.session_id!r}"
                ) from exc
            raise

    def compare_and_swap(self, task: Task, *, expected_statuses: List[str]) -> bool:
        row = _task_to_row(task)
        update_cols = [k for k in _TASK_FIELDS if k not in ("id", "exec_user")]
        set_clause = ", ".join(f"{k} = ?" for k in update_cols)
        placeholders = ", ".join(["?"] * len(expected_statuses))
        values = [row[k] for k in update_cols] + [task.exec_user or self.exec_user, task.id] + list(expected_statuses)
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    f"UPDATE tasks SET {set_clause} "
                    f"WHERE exec_user = ? AND id = ? AND status IN ({placeholders})",
                    values,
                )
            return bool(getattr(cursor, "rowcount", 0))
        except sqlite3.IntegrityError as exc:
            if "invalid_task_status_transition" in str(exc):
                raise InvalidTaskTransitionError(str(exc)) from exc
            if "ux_tasks_active_session" in str(exc) or "tasks.exec_user, tasks.session_id" in str(exc):
                raise DuplicatePendingTaskError(
                    f"Active task already exists for session_id={task.session_id!r}"
                ) from exc
            raise

    def delete(self, task_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM tasks WHERE exec_user = ? AND id = ?", (self.exec_user, str(task_id)))


class TaskReadRepository:
    """Focused repository for task list/read-model queries."""

    def __init__(self, db: Database, *, exec_user: str):
        self._db = db
        self.exec_user = exec_user

    def _fetch_many(self, sql: str, params: tuple) -> List[Task]:
        rows = self._db.execute_fetchall(sql, params)
        return [_row_to_task(row) for row in rows if row]

    def pending(self, limit: int = 10) -> List[Task]:
        return self._fetch_many(
            "SELECT * FROM tasks WHERE exec_user = ? AND status = 'pending' "
            "ORDER BY CASE priority WHEN 'project' THEN 0 WHEN 'serious' THEN 1 ELSE 2 END, created_at ASC "
            "LIMIT ?",
            (self.exec_user, limit),
        )

    def running(self) -> List[Task]:
        return self._fetch_many(
            "SELECT * FROM tasks WHERE exec_user = ? AND status = 'running'",
            (self.exec_user,),
        )

    def recent(self, limit: int = 10) -> List[Task]:
        return self._fetch_many(
            "SELECT * FROM tasks WHERE exec_user = ? ORDER BY created_at DESC LIMIT ?",
            (self.exec_user, limit),
        )

    def failed(self, limit: int = 10) -> List[Task]:
        return self._fetch_many(
            "SELECT * FROM tasks WHERE exec_user = ? AND status = 'failed' ORDER BY created_at DESC LIMIT ?",
            (self.exec_user, limit),
        )

    def orphans(self, limit: int = 100) -> List[Task]:
        return self._fetch_many(
            "SELECT * FROM tasks WHERE exec_user = ? AND (runtime_orphaned = 1 OR runtime_status = 'orphaned') "
            "ORDER BY created_at DESC LIMIT ?",
            (self.exec_user, limit),
        )


class TaskQueue:
    """Task queue manager with SQLite backend.

    The constructor signature is backward-compatible with the Redis version:
    ``db_path`` is accepted but ignored, ``redis_client`` is ignored.
    """

    def __init__(
        self,
        db_path: str = None,
        exec_user: str = "default",
        redis_client=None,
        db: Optional[Database] = None,
    ):
        self.exec_user = (exec_user or "default").strip() or "default"
        self._redis = redis_client or get_redis_client()
        if db is not None:
            self._db = db
        else:
            self._db = get_db(db_path)
        self.tasks = TaskRepository(self._db, exec_user=self.exec_user)
        self.reads = TaskReadRepository(self._db, exec_user=self.exec_user)
        logger.info(f"TaskQueue initialized for exec_user: {self.exec_user}")

    def _ws_hash(self, workspace: Optional[str]) -> str:
        if not workspace:
            return ""
        return hashlib.md5(workspace.encode("utf-8")).hexdigest()[:8]

    # Legacy Redis-style key helpers kept for compatibility tests/debugging.
    def _task_key(self, task_id: str) -> str:
        return f"task:{self.exec_user}:{task_id}"

    def _all_tasks_key(self) -> str:
        return f"tasks:{self.exec_user}:all"

    def _session_index_key(self, session_id: str) -> str:
        return f"tasks:{self.exec_user}:session:{session_id}"

    def _status_key(self, status) -> str:
        raw = status.value if hasattr(status, "value") else str(status)
        try:
            normalized = TaskStatus.from_legacy(raw).value
        except Exception:
            normalized = raw
        return f"tasks:{self.exec_user}:status:{normalized}"

    def _queue_key(self, workspace: Optional[str] = None) -> str:
        return f"tasks:{self.exec_user}:queue:{workspace or 'default'}"

    def _executing_key(self, workspace: Optional[str] = None) -> str:
        return f"tasks:{self.exec_user}:executing:{workspace or 'default'}"

    def _sync_redis_task(
        self,
        task: Task,
        *,
        previous_status: Optional[str] = None,
        previous_session_id: Optional[str] = None,
    ) -> None:
        if self._redis is None:
            return
        status_val = task.status if isinstance(task.status, str) else task.status.value
        ws = task.workspace or "default"
        task_key = self._task_key(task.id)
        new_hash = task.to_redis_hash()
        try:
            existing_hash = self._redis.hgetall(task_key) or {}
        except Exception:
            existing_hash = {}
        stale_fields = [field for field in existing_hash.keys() if field not in new_hash]
        if stale_fields:
            try:
                self._redis.hdel(task_key, *stale_fields)
            except Exception:
                pass
        self._redis.hset(task_key, new_hash)
        self._redis.sadd(self._status_key(status_val), task.id)
        if previous_status and previous_status != status_val:
            self._redis.srem(self._status_key(previous_status), task.id)
        try:
            self._redis.zadd(self._all_tasks_key(), {task.id: time.time()})
        except Exception:
            pass
        try:
            if status_val == TaskStatus.PENDING.value:
                self._redis.rpush(self._queue_key(ws), task.id)
            else:
                self._redis.lrem(self._queue_key(ws), 0, task.id)
        except Exception:
            pass
        try:
            if status_val == TaskStatus.RUNNING.value:
                self._redis.sadd(self._executing_key(ws), task.id)
            else:
                self._redis.srem(self._executing_key(ws), task.id)
        except Exception:
            pass
        try:
            if previous_session_id and previous_session_id != getattr(task, "session_id", None):
                self._redis.delete(self._session_index_key(previous_session_id))
        except Exception:
            pass
        try:
            if getattr(task, "session_id", None):
                self._redis.set(self._session_index_key(task.session_id), task.id)
        except Exception:
            pass

    def add_task(
        self,
        description: str,
        priority: TaskPriority = TaskPriority.THOUGHT,
        context: Optional[dict] = None,
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
        workspace: Optional[str] = None,
        provider: Optional[str] = None,
        alias: Optional[str] = None,
        model: Optional[str] = None,
        task_id: Optional[str] = None,
        source_session_id: Optional[str] = None,
        prior_session_id: Optional[str] = None,
        prior_work_dir: Optional[str] = None,
        repo_url: Optional[str] = None,
        repo_root: Optional[str] = None,
        worktree_path: Optional[str] = None,
        session_id: Optional[str] = None,
        exec_user: Optional[str] = None,
        assigned_to: Optional[str] = None,
        tags: Optional[list] = None,
        due_date: Optional[datetime] = None,
        ticket_ref: Optional[str] = None,
        depends_on: Optional[list] = None,
        response_url: Optional[str] = None,
        callback_msg_id: Optional[str] = None,
        callback_user: Optional[str] = None,
        notification_sink_type: Optional[str] = None,
        notification_channel: Optional[str] = None,
        notification_chat_id: Optional[str] = None,
        loop_enabled: bool = False,
        loop_max_iterations: int = 1,
        loop_keywords: Optional[list] = None,
    ) -> Task:
        """Add new task to queue."""
        actual_task_id = str(task_id) if task_id else str(uuid.uuid4())[:8]
        effective_exec_user = exec_user or self.exec_user

        from src.runtime.utils.ids import gen_session_id
        resolved_session_id = (session_id or "").strip() or gen_session_id()

        default_provider = "claude"
        normalized_provider = (provider or "").strip().lower() or default_provider
        alias_value = (alias or "").strip() or normalized_provider

        ctx = dict(context or {})
        for key, value in {
            "source_session_id": source_session_id,
            "prior_session_id": prior_session_id or source_session_id,
            "prior_work_dir": prior_work_dir,
            "repo_url": repo_url,
            "repo_root": repo_root,
            "worktree_path": worktree_path,
        }.items():
            if value not in (None, "", [], {}):
                ctx[key] = value

        task = Task(
            id=actual_task_id,
            description=description,
            priority=priority,
            context=ctx or None,
            project_id=project_id,
            project_name=project_name,
            workspace=workspace,
            exec_user=effective_exec_user,
            assigned_to=(assigned_to or "").strip() or None,
            tags=tags or [],
            due_date=due_date,
            ticket_ref=(ticket_ref or "").strip() or None,
            provider=normalized_provider,
            alias=alias_value,
            model=(model or "").strip() or None,
            session_id=resolved_session_id,
            source_session_id=source_session_id,
            prior_session_id=prior_session_id or source_session_id,
            prior_work_dir=prior_work_dir,
            repo_url=repo_url,
            repo_root=repo_root,
            worktree_path=worktree_path,
            session_kind="task",
            depends_on=depends_on or [],
            response_url=response_url,
            callback_msg_id=callback_msg_id,
            callback_user=callback_user,
            notification_sink_type=notification_sink_type or None,
            notification_channel=notification_channel or None,
            notification_chat_id=notification_chat_id or None,
            loop_enabled=loop_enabled,
            loop_max_iterations=loop_max_iterations,
            loop_keywords=loop_keywords or [],
        )
        task.execution_binding = task.to_execution_binding()

        self.tasks.insert(task)

        project_info = f" [Project: {project_name}]" if project_name else ""
        workspace_info = f" [Workspace: {workspace}]" if workspace else ""
        self._sync_redis_task(task)
        logger.info(f"Added task {task.id}: {description[:50]}...{project_info}{workspace_info}")
        _emit_task_domain_event(
            "task.created",
            task,
            payload={
                "description": task.description,
                "priority": task.priority if isinstance(task.priority, str) else task.priority.value,
                "status": task.status if isinstance(task.status, str) else task.status.value,
            },
        )
        return task

    def enqueue_chat_continue(
        self,
        task_id: str,
        message: str,
        model: Optional[str] = None,
        response_url: Optional[str] = None,
        callback_msg_id: Optional[str] = None,
        callback_user: Optional[str] = None,
        notification_sink_type: Optional[str] = None,
        notification_channel: Optional[str] = None,
        notification_chat_id: Optional[str] = None,
    ) -> Optional[Task]:
        """Re-enqueue an existing task as a background chat-continue run."""
        task_id = str(task_id)
        task = self.get_task(task_id)
        if not task:
            return None

        status_val = task.status if isinstance(task.status, str) else task.status.value
        if status_val == TaskStatus.RUNNING.value:
            return task
        if status_val == TaskStatus.ARCHIVED.value:
            raise ValueError("Task is cancelled")

        msg = (message or "").strip()
        if not msg:
            raise ValueError("Empty message")

        ctx: Dict[str, Any] = task.context or {}
        ctx["next_user_message"] = msg
        ctx["next_user_message_id"] = f"continue-{uuid.uuid4().hex[:8]}"
        ctx["next_run_kind"] = "chat_continue"
        task.context = ctx

        if response_url:
            task.response_url = response_url
        if callback_msg_id:
            task.callback_msg_id = callback_msg_id
        if callback_user:
            task.callback_user = callback_user
        if notification_sink_type:
            task.notification_sink_type = notification_sink_type
        if notification_channel:
            task.notification_channel = notification_channel
        if notification_chat_id:
            task.notification_chat_id = notification_chat_id

        effective_model = (model or "").strip()
        if effective_model:
            task.model = effective_model

        try:
            self._update_task_status(task, TaskStatus.PENDING)
        except (InvalidTaskTransitionError, TaskLifecycleRaceError):
            return None
        except Exception:
            pass

        self.update_task(task)
        logger.info(f"Enqueued chat_continue for task {task.id}")
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        task_id = str(task_id)
        task = self.tasks.get(task_id)
        if task is None:
            if self._redis is not None:
                data = self._redis.hgetall(self._task_key(task_id))
                if data:
                    try:
                        return Task.from_redis_hash(data)
                    except Exception as e:
                        logger.error(f"Failed to parse redis task {task_id}: {e}")
            return None
        return task

    def find_task_by_session_id(self, session_id: str) -> Optional[Task]:
        """Find a task whose session_id matches the given value."""
        if not session_id:
            return None
        if self._redis is not None:
            try:
                indexed_task_id = self._redis.get(self._session_index_key(session_id))
            except Exception:
                indexed_task_id = None
            if indexed_task_id:
                task = self.get_task(str(indexed_task_id))
                if task is not None and getattr(task, "session_id", None) == session_id:
                    return task
                try:
                    self._redis.delete(self._session_index_key(session_id))
                except Exception:
                    pass
        task = self.tasks.find_by_session_id(session_id)
        if task is not None:
            if self._redis is not None:
                try:
                    self._redis.set(self._session_index_key(session_id), task.id)
                except Exception:
                    pass
            return task
        if self._redis is not None:
            try:
                all_task_ids = self._redis.zrange(self._all_tasks_key(), 0, -1)
            except Exception:
                all_task_ids = []
            for task_id in all_task_ids:
                task = self.get_task(str(task_id))
                if task is None:
                    continue
                if getattr(task, "session_id", None) == session_id:
                    try:
                        self._redis.set(self._session_index_key(session_id), task.id)
                    except Exception:
                        pass
                    return task
        return None

    def get_pending_tasks(self, limit: int = 10) -> List[Task]:
        """Get ready-to-run pending tasks sorted by priority."""
        return self.reads.pending(limit)

    def get_running_tasks(self) -> List[Task]:
        """Get all running tasks."""
        rows = self._db.execute_fetchall(
            "SELECT * FROM tasks WHERE exec_user = ? AND status = 'running'",
            (self.exec_user,),
        )
        tasks: Dict[str, Task] = {}
        for row in rows:
            if not row:
                continue
            try:
                task = _row_to_task(row)
            except Exception:
                continue
            tasks[task.id] = task

        if self._redis is not None:
            try:
                redis_ids = self._redis.smembers(self._status_key(TaskStatus.RUNNING)) or set()
            except Exception:
                redis_ids = set()
            for task_id in redis_ids:
                task_id = str(task_id)
                if not task_id or task_id in tasks:
                    continue
                task = self.get_task(task_id)
                if task is not None:
                    tasks[task.id] = task

        return list(tasks.values())

    def _update_task_status(self, task: Task, new_status: TaskStatus) -> None:
        """Update collaboration status and keep runtime layer in sync."""
        now = datetime.now(timezone.utc)
        old_status = TaskStatus.from_legacy(task.status if isinstance(task.status, str) else task.status.value).value
        task.status = new_status

        if new_status == TaskStatus.RUNNING:
            task.started_at = now
            task.runtime_status = "running"
            task.runtime_orphaned = False
            task.runtime_orphaned_at = None
            task.runtime_last_heartbeat = now
        elif new_status == TaskStatus.FAILED:
            if not task.completed_at:
                task.completed_at = now
            task.runtime_status = "failed"
        elif new_status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.ARCHIVED):
            if new_status == TaskStatus.COMPLETED and not task.completed_at:
                task.completed_at = now
            if new_status == TaskStatus.CANCELLED and not task.deleted_at:
                task.deleted_at = now
            if new_status == TaskStatus.ARCHIVED:
                task.archived_at = now
            if new_status == TaskStatus.ARCHIVED and not task.deleted_at:
                task.deleted_at = now
            task.runtime_status = "idle"
            task.runtime_orphaned = False
            task.runtime_orphaned_at = None
            task.runtime_last_heartbeat = None
        else:
            if str(getattr(task, "runtime_status", "")) != "orphaned":
                task.runtime_status = "queued"
                task.runtime_last_heartbeat = None

        updated = self.tasks.compare_and_swap(task, expected_statuses=[old_status])
        if not updated:
            if self._redis is not None and self.tasks.get(task.id) is None:
                self._sync_redis_task(task, previous_status=old_status, previous_session_id=getattr(task, "session_id", None))
                return
            raise TaskLifecycleRaceError(
                f"Task {task.id} changed concurrently while transitioning {old_status} -> {new_status.value}"
            )
        self._sync_redis_task(task, previous_status=old_status, previous_session_id=getattr(task, "session_id", None))

    def cancel_task(self, task_id: str) -> Optional[Task]:
        """Cancel PENDING task (soft delete)"""
        task_id = str(task_id)
        task = self.get_task(task_id)
        if not task:
            return None
        status_val = task.status if isinstance(task.status, str) else task.status.value
        if status_val == TaskStatus.PENDING.value:
            try:
                self._update_task_status(task, TaskStatus.CANCELLED)
            except (InvalidTaskTransitionError, TaskLifecycleRaceError):
                return None
            logger.info(f"Task {task_id} cancelled and moved to trash")
        return task

    def update_task_status(self, task_id: str, new_status: TaskStatus) -> Optional[Task]:
        """Manually update task status."""
        task_id = str(task_id)
        task = self.get_task(task_id)
        if not task:
            return None
        old_status = TaskStatus.from_legacy(task.status if isinstance(task.status, str) else task.status.value)
        if not TaskStatus.can_transition(old_status, new_status):
            logger.warning(f"Invalid task status transition: {task_id} {old_status.value} -> {new_status.value}")
            return None
        try:
            self._update_task_status(task, new_status)
        except (InvalidTaskTransitionError, TaskLifecycleRaceError):
            return None
        logger.info(f"Task {task_id} status manually updated: {old_status.value} -> {new_status.value}")
        _emit_task_domain_event(
            "task.status_changed",
            task,
            payload={"from": old_status.value, "to": new_status.value},
        )
        return task

    def get_queue_status(self) -> dict:
        """Get overall queue status"""
        rows = self._db.execute_fetchall(
            "SELECT status, COUNT(*) as cnt FROM tasks WHERE exec_user = ? GROUP BY status",
            (self.exec_user,),
        )
        counts = {r["status"]: r["cnt"] for r in rows}
        pending = counts.get("pending", 0)
        running = counts.get("running", 0)
        in_review = counts.get("in_review", 0)
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)
        archived = counts.get("archived", 0)
        return {
            "total": pending + running + in_review + completed + failed + cancelled + archived,
            "pending": pending,
            "running": running,
            "in_review": in_review,
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
            "archived": archived,
        }

    def update_task(self, task: Task) -> bool:
        """Update task data in SQLite."""
        existing = self.get_task(task.id)
        previous_status = None
        previous_session_id = None
        if existing is not None:
            previous_status = existing.status if isinstance(existing.status, str) else existing.status.value
            previous_session_id = getattr(existing, "session_id", None)
        try:
            updated = self.tasks.update(task)
        except InvalidTaskTransitionError:
            raise
        if not updated:
            logger.warning(f"Task {task.id} not found for update")
            self._sync_redis_task(task, previous_status=previous_status, previous_session_id=previous_session_id)
            return False
        self._sync_redis_task(task, previous_status=previous_status, previous_session_id=previous_session_id)
        logger.debug(f"Updated task {task.id}")
        _emit_task_domain_event(
            "task.updated",
            task,
            payload={
                "priority": task.priority if isinstance(task.priority, str) else task.priority.value,
                "workspace": task.workspace,
                "session_id": task.session_id,
                "source_session_id": task.source_session_id,
            },
        )
        return True

    def get_projects(self) -> List[dict]:
        """Get all projects with task counts and status"""
        rows = self._db.execute_fetchall(
            "SELECT project_id, project_name, status, COUNT(*) as cnt "
            "FROM tasks WHERE exec_user = ? AND project_id IS NOT NULL "
            "GROUP BY project_id, project_name, status",
            (self.exec_user,),
        )
        projects: Dict[str, dict] = {}
        for r in rows:
            pid = r["project_id"]
            if pid not in projects:
                projects[pid] = {
                    "project_id": pid,
                    "project_name": r["project_name"] or pid,
                    "total_tasks": 0,
                    "pending": 0,
                    "running": 0,
                    "in_review": 0,
                    "completed": 0,
                    "failed": 0,
                }
            projects[pid]["total_tasks"] += r["cnt"]
            st = r["status"]
            if st in projects[pid]:
                projects[pid][st] += r["cnt"]
        return sorted(projects.values(), key=lambda x: x["project_id"])

    def get_project_by_id(self, project_id: str) -> Optional[dict]:
        """Get project info by ID"""
        rows = self._db.execute_fetchall(
            "SELECT * FROM tasks WHERE exec_user = ? AND project_id = ?",
            (self.exec_user, project_id),
        )
        if not rows:
            return None
        tasks = [_row_to_task(r) for r in rows]
        first_task = tasks[0]
        pending = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "pending")
        running = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "running")
        in_review = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "in_review")
        completed = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "completed")
        failed = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "failed")
        return {
            "project_id": project_id,
            "project_name": first_task.project_name or project_id,
            "total_tasks": len(tasks),
            "pending": pending,
            "running": running,
            "in_review": in_review,
            "completed": completed,
            "failed": failed,
            "created_at": min(t.created_at for t in tasks),
            "tasks": [
                {
                    "id": t.id, "description": t.description[:50],
                    "status": t.status if isinstance(t.status, str) else t.status.value,
                    "priority": t.priority if isinstance(t.priority, str) else t.priority.value,
                    "created_at": t.created_at.isoformat(),
                }
                for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)[:5]
            ],
        }

    def get_recent_tasks(self, limit: int = 10) -> List[Task]:
        """Get the most recent tasks"""
        return self.reads.recent(limit)

    def list_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        workspace: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[List[Task], int]:
        """List tasks with server-side filtering and pagination."""
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20

        conditions = ["exec_user = ?"]
        params: list = [self.exec_user]

        if status:
            normalized_status = status.lower().strip()
            try:
                normalized_status = TaskStatus.from_legacy(normalized_status).value
            except Exception:
                pass
            conditions.append("status = ?")
            params.append(normalized_status)
        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id.strip())
        if workspace:
            ws_hash = self._ws_hash(workspace.strip())
            conditions.append("workspace_hash = ?")
            params.append(ws_hash)
        if search:
            conditions.append("(description LIKE ? OR id LIKE ? OR project_name LIKE ?)")
            s = f"%{search.lower().strip()}%"
            params.extend([s, s, s])

        where = " AND ".join(conditions)
        count_row = self._db.execute_fetchone(
            f"SELECT COUNT(*) as cnt FROM tasks WHERE {where}", params
        )
        total = count_row["cnt"] if count_row else 0

        rows = self._db.execute_fetchall(
            f"SELECT * FROM tasks WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        )
        tasks = []
        for r in rows:
            try:
                tasks.append(_row_to_task(r))
            except Exception as e:
                logger.error(f"Failed to parse task in list: {e}")
        return tasks, total

    def get_failed_tasks(self, limit: int = 10) -> List[Task]:
        """Get the most recent failed tasks"""
        return self.reads.failed(limit)

    def delete_project(self, project_id: str) -> int:
        """Soft delete all tasks in a project."""
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE tasks SET status = 'cancelled', deleted_at = ? "
                "WHERE exec_user = ? AND project_id = ? AND status = 'pending'",
                (datetime.now(timezone.utc).timestamp(), self.exec_user, project_id),
            )
            count = cursor.rowcount
        if count:
            logger.info(f"Soft deleted project {project_id}: {count} tasks moved to trash")
        return count

    def archive_tasks(self, task_ids: List[str]) -> Dict[str, Any]:
        """Batch archive COMPLETED tasks."""
        archived, skipped = [], {}
        for raw_id in task_ids or []:
            task_id = str(raw_id)
            task = self.get_task(task_id)
            if not task:
                skipped[task_id] = "not_found"
                continue
            status_val = task.status if isinstance(task.status, str) else task.status.value
            if status_val != TaskStatus.COMPLETED.value:
                skipped[task_id] = f"invalid_status:{status_val}"
                continue
            self._update_task_status(task, TaskStatus.ARCHIVED)
            archived.append(task_id)
        return {"count": len(archived), "archived": archived, "skipped": skipped}

    def unarchive_tasks(self, task_ids: List[str]) -> Dict[str, Any]:
        """Batch unarchive ARCHIVED tasks back to COMPLETED."""
        unarchived, skipped = [], {}
        for raw_id in task_ids or []:
            task_id = str(raw_id)
            task = self.get_task(task_id)
            if not task:
                skipped[task_id] = "not_found"
                continue
            status_val = task.status if isinstance(task.status, str) else task.status.value
            if status_val != TaskStatus.ARCHIVED.value:
                skipped[task_id] = f"invalid_status:{status_val}"
                continue
            task.archived_at = None
            try:
                self._update_task_status(task, TaskStatus.COMPLETED)
            except (InvalidTaskTransitionError, TaskLifecycleRaceError):
                skipped[task_id] = "race_or_invalid_transition"
                continue
            unarchived.append(task_id)
        return {"count": len(unarchived), "unarchived": unarchived, "skipped": skipped}

    def clear_tasks(self, task_ids: List[str]) -> Dict[str, Any]:
        """Batch hard delete ARCHIVED tasks."""
        cleared, skipped = [], {}
        for raw_id in task_ids or []:
            task_id = str(raw_id)
            task = self.get_task(task_id)
            if not task:
                skipped[task_id] = "not_found"
                continue
            status_val = task.status if isinstance(task.status, str) else task.status.value
            if status_val != TaskStatus.ARCHIVED.value:
                skipped[task_id] = f"invalid_status:{status_val}"
                continue
            try:
                self.delete_task_hard(task_id)
                cleared.append(task_id)
            except Exception as e:
                skipped[task_id] = f"error:{e}"
        return {"count": len(cleared), "cleared": cleared, "skipped": skipped}

    def delete_task_hard(self, task_id: str) -> bool:
        """Hard delete a task."""
        task_id = str(task_id)
        existing = self.get_task(task_id)
        self.tasks.delete(task_id)
        if self._redis is not None:
            try:
                self._redis.delete(self._task_key(task_id))
            except Exception:
                pass
            try:
                self._redis.zrem(self._all_tasks_key(), task_id)
            except Exception:
                pass
            try:
                if existing is not None:
                    status_val = existing.status if isinstance(existing.status, str) else existing.status.value
                    self._redis.srem(self._status_key(status_val), task_id)
                    self._redis.srem(self._executing_key(existing.workspace or "default"), task_id)
                    if getattr(existing, "session_id", None):
                        self._redis.delete(self._session_index_key(existing.session_id))
            except Exception:
                pass
        logger.info(f"Hard deleted task {task_id}")
        if existing is not None:
            _emit_task_domain_event(
                "task.deleted",
                existing,
                payload={"hard_delete": True},
            )
        return True

    # ============ Executor Support Methods ============

    def get_next_todo_task(self, workspace: Optional[str] = None) -> Optional[Task]:
        """Get next TODO task from queue for execution"""
        if workspace is not None:
            ws_hash = self._ws_hash(workspace)
            row = self._db.execute_fetchone(
                "SELECT * FROM tasks WHERE exec_user = ? AND workspace_hash = ? AND status = 'pending' "
                "ORDER BY CASE priority WHEN 'project' THEN 0 WHEN 'serious' THEN 1 ELSE 2 END, created_at ASC LIMIT 1",
                (self.exec_user, ws_hash),
            )
        else:
            row = self._db.execute_fetchone(
            "SELECT * FROM tasks WHERE exec_user = ? AND status = 'pending' "
            "ORDER BY CASE priority WHEN 'project' THEN 0 WHEN 'serious' THEN 1 ELSE 2 END, created_at ASC LIMIT 1",
                (self.exec_user,),
            )
        return _row_to_task(row) if row else None

    def start_task(self, task_id: str) -> Optional[Task]:
        """Mark task as running."""
        task = self.get_task(task_id)
        if not task:
            return None
        status_val = task.status if isinstance(task.status, str) else task.status.value
        if status_val != TaskStatus.PENDING.value:
            logger.warning(f"Task {task_id} is not ready to start, cannot start")
            return None
        task.attempt_count += 1
        try:
            self._update_task_status(task, TaskStatus.RUNNING)
        except (InvalidTaskTransitionError, TaskLifecycleRaceError):
            logger.warning(f"Task {task_id} lost start race or failed lifecycle guard")
            return None
        logger.info(f"Task {task_id} started (attempt {task.attempt_count})")
        _emit_task_domain_event("task.started", task, payload={"attempt_count": task.attempt_count})
        return task

    def complete_task(self, task_id: str, error_message: Optional[str] = None) -> Optional[Task]:
        """Mark task as COMPLETED or FAILED"""
        task = self.get_task(task_id)
        if not task:
            return None
        if error_message:
            return self.fail_task(task_id, error_message=error_message)
        self._update_task_status(task, TaskStatus.COMPLETED)
        logger.info(f"Task {task_id} completed successfully")
        _emit_task_domain_event("task.completed", task, payload={"outcome": task.outcome or "success"})
        return task

    def requeue_task(self, task_id: str, error_message: Optional[str] = None, attempt_count: Optional[int] = None) -> Optional[Task]:
        """Move a task back to TODO."""
        task = self.get_task(task_id)
        if not task:
            return None
        if attempt_count is not None:
            task.attempt_count = attempt_count
        if error_message is not None:
            task.error_message = error_message
        self._update_task_status(task, TaskStatus.PENDING)
        _emit_task_domain_event(
            "task.requeued",
            task,
            payload={"attempt_count": task.attempt_count, "error_message": task.error_message},
        )
        return task

    def fail_task(self, task_id: str, error_message: Optional[str], attempt_count: Optional[int] = None) -> Optional[Task]:
        """Move a task to FAILED."""
        task = self.get_task(task_id)
        if not task:
            return None
        if attempt_count is not None:
            task.attempt_count = attempt_count
        if error_message is not None:
            task.error_message = error_message
        try:
            self._update_task_status(task, TaskStatus.FAILED)
        except (InvalidTaskTransitionError, TaskLifecycleRaceError):
            return None
        _emit_task_domain_event(
            "task.failed",
            task,
            payload={"attempt_count": task.attempt_count, "error_message": task.error_message},
        )
        return task

    def requeue_stale_task(self, task_id: str, attempt_count: int, error_message: str) -> Optional[Task]:
        return self.requeue_task(task_id, error_message=error_message, attempt_count=attempt_count)

    def fail_stale_task(self, task_id: str, attempt_count: int, error_message: str) -> Optional[Task]:
        return self.fail_task(task_id, error_message=error_message, attempt_count=attempt_count)

    def mark_runtime_heartbeat(self, task_id: str) -> Optional[Task]:
        """Refresh runtime heartbeat for a running task."""
        task = self.get_task(task_id)
        if not task:
            return None
        task.runtime_last_heartbeat = datetime.now(timezone.utc)
        if str(getattr(task, "runtime_status", "")) != "orphaned":
            task.runtime_status = "running"
        self.update_task(task)
        return task

    def mark_task_orphaned(self, task_id: str, reason: Optional[str] = None) -> Optional[Task]:
        """Mark a task as orphaned in runtime layer without losing collaboration status."""
        task = self.get_task(task_id)
        if not task:
            return None
        now = datetime.now(timezone.utc)
        task.runtime_status = "orphaned"
        task.runtime_orphaned = True
        task.runtime_orphaned_at = now
        task.runtime_last_heartbeat = None
        if reason:
            task.error_message = reason
        self.update_task(task)
        _emit_task_domain_event(
            "task.orphaned",
            task,
            payload={"reason": reason or ""},
        )
        return task

    def requeue_orphan_task(self, task_id: str, reason: Optional[str] = None) -> Optional[Task]:
        """Requeue an orphan task back to inbox and clear orphan runtime state."""
        task = self.get_task(task_id)
        if not task:
            return None
        if not bool(getattr(task, "runtime_orphaned", False)) and str(getattr(task, "runtime_status", "")) != "orphaned":
            return None

        if reason:
            task.error_message = reason
        task.runtime_orphaned = False
        task.runtime_orphaned_at = None
        task.runtime_status = "queued"
        task.runtime_last_heartbeat = None
        self._update_task_status(task, TaskStatus.PENDING)
        _emit_task_domain_event(
            "task.orphan_requeued",
            task,
            payload={"reason": reason or ""},
        )
        return task

    def list_orphan_tasks(self, limit: int = 100) -> List[Task]:
        return self.reads.orphans(limit)

    def get_executing_count(self, workspace: Optional[str] = None) -> int:
        """Get count of currently executing tasks for a workspace"""
        if workspace:
            ws_hash = self._ws_hash(workspace)
            row = self._db.execute_fetchone(
                "SELECT COUNT(*) as cnt FROM tasks WHERE exec_user = ? AND workspace_hash = ? AND status = 'running'",
                (self.exec_user, ws_hash),
            )
        else:
            row = self._db.execute_fetchone(
                "SELECT COUNT(*) as cnt FROM tasks WHERE exec_user = ? AND status = 'running'",
                (self.exec_user,),
            )
        return row["cnt"] if row else 0

    def get_all_workspaces(self) -> List[str]:
        """Get all unique workspace hashes with tasks"""
        rows = self._db.execute_fetchall(
            "SELECT DISTINCT workspace_hash FROM tasks WHERE exec_user = ? AND workspace_hash != ''",
            (self.exec_user,),
        )
        return [r["workspace_hash"] for r in rows]

    MAX_DISPATCH_RETRIES: int = 5

    def requeue_stuck_tasks(self, timeout_seconds: int = 3600) -> int:
        """Requeue tasks that have been in progress for too long."""
        if self._redis is not None:
            requeued, failed = 0, 0
            active_ids = set(self._redis.smembers(self._status_key(TaskStatus.RUNNING)))
            cutoff = datetime.now(timezone.utc).timestamp() - timeout_seconds
            for task_id in list(active_ids):
                data = self._redis.hgetall(self._task_key(task_id)) or {}
                if not data:
                    continue
                try:
                    task = Task.from_redis_hash(data)
                except Exception:
                    continue
                started_at = getattr(task, "started_at", None)
                if not started_at or started_at.timestamp() >= cutoff:
                    continue
                new_attempts = (task.attempt_count or 0) + 1
                orphan_reason = f"Orphan runtime detected after {timeout_seconds}s without completion"
                self.mark_task_orphaned(task.id, reason=orphan_reason)
                if new_attempts >= self.MAX_DISPATCH_RETRIES:
                    self.fail_task(task.id, error_message=f"Permanently failed after orphan retries ({new_attempts}).", attempt_count=new_attempts)
                    failed += 1
                else:
                    self.requeue_task(
                        task.id,
                        error_message=f"Requeued orphan attempt {new_attempts}/{self.MAX_DISPATCH_RETRIES}.",
                        attempt_count=new_attempts,
                    )
                    requeued += 1
            total = requeued + failed
            if total:
                logger.info(f"requeue_stuck_tasks: requeued={requeued}, failed={failed}")
            return total
        cutoff = datetime.now(timezone.utc).timestamp() - timeout_seconds
        rows = self._db.execute_fetchall(
            "SELECT * FROM tasks WHERE exec_user = ? AND status = 'running' AND started_at < ?",
            (self.exec_user, cutoff),
        )
        requeued, failed = 0, 0
        for row in rows:
            task = _row_to_task(row)
            new_attempts = (task.attempt_count or 0) + 1
            orphan_reason = f"Orphan runtime detected after {timeout_seconds}s without completion"
            self.mark_task_orphaned(task.id, reason=orphan_reason)
            if new_attempts >= self.MAX_DISPATCH_RETRIES:
                self.fail_task(task.id, error_message=f"Permanently failed after orphan retries ({new_attempts}).", attempt_count=new_attempts)
                failed += 1
            else:
                self.requeue_task(
                    task.id,
                    error_message=f"Requeued orphan attempt {new_attempts}/{self.MAX_DISPATCH_RETRIES}.",
                    attempt_count=new_attempts,
                )
                requeued += 1
        total = requeued + failed
        if total:
            logger.info(f"requeue_stuck_tasks: requeued={requeued}, failed={failed}")
        return total



def get_task_queue(exec_user: str = "default", db_path: Optional[str] = None) -> TaskQueue:
    """Compatibility factory for the canonical runtime task queue."""
    return TaskQueue(db_path=db_path, exec_user=exec_user)

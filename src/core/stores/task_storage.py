# -*- coding: utf-8 -*-
"""SQLite task storage for slash commands

Provides TaskQueue class for managing tasks in SQLite.
Replaces the previous Redis implementation while keeping the same public API.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import uuid
from typing import List, Optional, Dict, Any

import logging

from ..models.task_models import Task, TaskPriority, TaskStatus
from src.runtime.stores.db import Database, get_db

logger = logging.getLogger(__name__)


# Keep importable for backward compat (callers that import RedisClient from here)
def get_redis_client():
    """Compatibility shim — returns None since storage is now SQLite."""
    return None


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


def _ws_hash(workspace: Optional[str]) -> str:
    if not workspace:
        return ""
    return hashlib.md5(workspace.encode("utf-8")).hexdigest()[:8]


_TABLE_CREATED = False


def _ensure_core_tasks_table(db: Database):
    """Create the core_tasks table if it doesn't already exist.
    
    If core_tasks is a VIEW (pointing to tasks table), skip table/index creation.
    """
    global _TABLE_CREATED
    if _TABLE_CREATED:
        return
    
    # Check if core_tasks is a view (created by migration to unify tasks/core_tasks)
    try:
        row = db.execute_fetchone(
            "SELECT type FROM sqlite_master WHERE name = 'core_tasks'"
        )
        if row and row.get("type") == "view":
            logger.info("core_tasks is a VIEW — skipping table/index creation")
            _TABLE_CREATED = True
            return
    except Exception:
        pass
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS core_tasks (
            id TEXT PRIMARY KEY,
            exec_user TEXT NOT NULL DEFAULT 'default',
            description TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'thought',
            status TEXT NOT NULL DEFAULT 'inbox',
            context_json TEXT,
            project_id TEXT,
            project_name TEXT,
            workspace TEXT,
            workspace_hash TEXT,
            provider TEXT DEFAULT 'claude',
            alias TEXT,
            session_id TEXT,
            attempt_count INTEGER DEFAULT 0,
            error_message TEXT,
            depends_on_json TEXT,
            created_at REAL,
            started_at REAL,
            completed_at REAL,
            archived_at REAL,
            deleted_at REAL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_core_tasks_exec_user ON core_tasks (exec_user)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_core_tasks_status ON core_tasks (exec_user, status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_core_tasks_project ON core_tasks (exec_user, project_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_core_tasks_workspace ON core_tasks (exec_user, workspace_hash)")
    _TABLE_CREATED = True


def _task_to_row(task: Task, exec_user: str) -> dict:
    ctx = None
    if task.context:
        ctx = json.dumps(task.context, ensure_ascii=False)
    deps = None
    deps_list = getattr(task, "depends_on", None)
    if deps_list:
        deps = json.dumps(deps_list)
    return {
        "id": task.id,
        "exec_user": exec_user,
        "description": task.description,
        "priority": task.priority if isinstance(task.priority, str) else task.priority.value,
        "status": task.status if isinstance(task.status, str) else task.status.value,
        "context_json": ctx,
        "project_id": task.project_id,
        "project_name": task.project_name,
        "workspace": task.workspace,
        "workspace_hash": _ws_hash(task.workspace),
        "provider": task.provider,
        "alias": task.alias,
        "session_id": task.session_id,
        "attempt_count": task.attempt_count,
        "error_message": task.error_message,
        "depends_on_json": deps,
        "created_at": _dt_to_ts(task.created_at),
        "started_at": _dt_to_ts(task.started_at),
        "completed_at": _dt_to_ts(task.completed_at),
        "archived_at": _dt_to_ts(task.archived_at),
        "deleted_at": _dt_to_ts(task.deleted_at),
    }


def _row_to_task(row: dict) -> Task:
    ctx = None
    if row.get("context_json"):
        try:
            ctx = json.loads(row["context_json"])
        except Exception:
            pass
    deps = []
    if row.get("depends_on_json"):
        try:
            deps = json.loads(row["depends_on_json"])
        except Exception:
            pass
    return Task(
        id=row["id"],
        description=row.get("description") or "",
        priority=TaskPriority(row.get("priority", "thought")),
        status=TaskStatus.from_legacy(row.get("status", "todo")),
        context=ctx,
        project_id=row.get("project_id"),
        project_name=row.get("project_name"),
        workspace=row.get("workspace"),
        exec_user=row.get("exec_user", "default"),
        provider=row.get("provider", "claude"),
        alias=row.get("alias"),
        session_id=row.get("session_id"),
        attempt_count=row.get("attempt_count", 0),
        error_message=row.get("error_message"),
        created_at=_ts_to_dt(row.get("created_at")) or datetime.now(timezone.utc),
        started_at=_ts_to_dt(row.get("started_at")),
        completed_at=_ts_to_dt(row.get("completed_at")),
        archived_at=_ts_to_dt(row.get("archived_at")),
        deleted_at=_ts_to_dt(row.get("deleted_at")),
    )


class TaskQueue:
    """Task queue manager with SQLite backend

    Constructor signature is backward-compatible with the Redis version:
    ``db_path`` and ``redis_client`` are accepted but ignored.
    """

    def __init__(
        self,
        db_path: str = None,
        exec_user: str = "default",
        redis_client=None,
    ):
        self.exec_user = exec_user
        self._db = get_db()
        _ensure_core_tasks_table(self._db)
        logger.info(f"TaskQueue initialized for exec_user: {exec_user}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _save_task(self, task: Task) -> None:
        """INSERT a new task row."""
        row = _task_to_row(task, self.exec_user)
        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO core_tasks ({cols}) VALUES ({placeholders})",
                list(row.values()),
            )

    def _update_task(self, task: Task) -> None:
        """UPDATE an existing task row."""
        row = _task_to_row(task, self.exec_user)
        update_cols = [k for k in row if k not in ("id", "exec_user")]
        set_clause = ", ".join(f"{k} = ?" for k in update_cols)
        values = [row[k] for k in update_cols] + [self.exec_user, task.id]
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE core_tasks SET {set_clause} WHERE exec_user = ? AND id = ?",
                values,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        task_id: Optional[str] = None,
        source_session_id: Optional[str] = None,
        exec_user: Optional[str] = None,
        depends_on: Optional[list] = None,
    ) -> Task:
        """Add new task to queue"""
        actual_task_id = str(task_id) if task_id else str(uuid.uuid4())[:8]
        effective_exec_user = exec_user or self.exec_user

        from src.server.utils.ids import gen_session_id
        logger.info(f"add_task called with source_session_id={source_session_id!r}, task_id={actual_task_id}, exec_user={effective_exec_user!r}")
        session_id = gen_session_id()
        logger.info(f"Generated session_id={session_id}")

        normalized_provider = (provider or "").strip().lower() or "claude"
        alias_value = (alias or "").strip() or normalized_provider

        task = Task(
            id=actual_task_id,
            description=description,
            priority=priority,
            context=context,
            project_id=project_id,
            project_name=project_name,
            workspace=workspace,
            exec_user=effective_exec_user,
            provider=normalized_provider,
            alias=alias_value,
            session_id=session_id,
            depends_on=depends_on or [],
        )

        self._save_task(task)

        project_info = f" [Project: {project_name}]" if project_name else ""
        workspace_info = f" [Workspace: {workspace}]" if workspace else ""
        logger.info(f"Added task {task.id}: {description[:50]}...{project_info}{workspace_info}")
        return task

    def enqueue_chat_continue(self, task_id: str, message: str) -> Optional[Task]:
        """Re-enqueue an existing task as a background chat-continue run."""
        task_id = str(task_id)
        task = self.get_task(task_id)
        if not task:
            return None

        status_val = task.status if isinstance(task.status, str) else task.status.value
        if status_val == TaskStatus.IN_PROGRESS.value:
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

        try:
            self._update_task_status(task, TaskStatus.INBOX)
        except Exception:
            pass

        self._update_task(task)
        logger.info(f"Enqueued chat_continue for task {task.id}")
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        task_id = str(task_id)
        row = self._db.execute_fetchone(
            "SELECT * FROM core_tasks WHERE exec_user = ? AND id = ?",
            (self.exec_user, task_id),
        )
        if not row:
            return None
        try:
            return _row_to_task(row)
        except Exception as e:
            logger.error(f"Failed to parse task {task_id}: {e}")
            return None

    def get_pending_tasks(self, limit: int = 10) -> List[Task]:
        """Get TODO tasks sorted by priority (PROJECT first, then by creation time)"""
        rows = self._db.execute_fetchall(
            "SELECT * FROM core_tasks WHERE exec_user = ? AND status = 'todo' "
            "ORDER BY CASE priority WHEN 'project' THEN 0 ELSE 1 END, created_at ASC "
            "LIMIT ?",
            (self.exec_user, limit),
        )
        return [_row_to_task(r) for r in rows if r]

    def get_in_progress_tasks(self) -> List[Task]:
        """Get all DOING tasks"""
        rows = self._db.execute_fetchall(
            "SELECT * FROM core_tasks WHERE exec_user = ? AND status = 'doing'",
            (self.exec_user,),
        )
        return [_row_to_task(r) for r in rows if r]

    def _update_task_status(self, task: Task, new_status: TaskStatus) -> None:
        """Update task status and timestamps."""
        task.status = new_status
        now = datetime.now(timezone.utc)
        if new_status == TaskStatus.IN_PROGRESS:
            task.started_at = now
        elif new_status in (TaskStatus.DONE, TaskStatus.FAILED):
            if not task.completed_at:
                task.completed_at = now
        elif new_status == TaskStatus.ARCHIVED:
            task.archived_at = now
        elif new_status == TaskStatus.ARCHIVED:
            if not task.deleted_at:
                task.deleted_at = now
        self._update_task(task)

    def cancel_task(self, task_id: str) -> Optional[Task]:
        """Cancel TODO task (soft delete)"""
        task_id = str(task_id)
        task = self.get_task(task_id)
        if not task:
            return None
        status_val = task.status if isinstance(task.status, str) else task.status.value
        if status_val == TaskStatus.INBOX.value:
            self._update_task_status(task, TaskStatus.ARCHIVED)
            logger.info(f"Task {task_id} cancelled and moved to trash")
        return task

    def update_task_status(self, task_id: str, new_status: TaskStatus) -> Optional[Task]:
        """Manually update task status."""
        task_id = str(task_id)
        task = self.get_task(task_id)
        if not task:
            return None
        old_status_val = task.status if isinstance(task.status, str) else task.status.value
        self._update_task_status(task, new_status)
        logger.info(f"Task {task_id} status manually updated: {old_status_val} -> {new_status.value}")
        return task

    def update_task(self, task_id: str, updates: dict) -> Optional[Task]:
        """Update arbitrary task fields (priority, assignee, position, description, etc).

        Allowed fields: priority, assignee, position, description, title, due_date, labels, metadata.
        Status changes should use update_task_status() instead.
        """
        task_id = str(task_id)
        task = self.get_task(task_id)
        if not task:
            return None

        allowed = {"priority", "assignee", "position", "description", "title", "due_date", "labels", "metadata"}
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return task

        set_clauses = []
        params = []
        for key, value in filtered.items():
            if isinstance(value, (dict, list)):
                set_clauses.append(f"{key} = ?")
                params.append(json.dumps(value))
            else:
                set_clauses.append(f"{key} = ?")
                params.append(str(value) if value is not None else None)

        params.append(task_id)
        params.append(self.exec_user)
        sql = f"UPDATE core_tasks SET {', '.join(set_clauses)} WHERE task_id = ? AND exec_user = ?"
        self._db.execute(sql, params)

        return self.get_task(task_id)

    def get_queue_status(self) -> dict:
        """Get overall queue status"""
        rows = self._db.execute_fetchall(
            "SELECT status, COUNT(*) as cnt FROM core_tasks WHERE exec_user = ? GROUP BY status",
            (self.exec_user,),
        )
        counts = {r["status"]: r["cnt"] for r in rows}
        inbox = counts.get("inbox", 0) + counts.get("todo", 0)
        in_progress = counts.get("in_progress", 0) + counts.get("doing", 0)
        in_review = counts.get("in_review", 0)
        done = counts.get("done", 0)
        failed = counts.get("failed", 0)
        archived = counts.get("archived", 0) + counts.get("cancelled", 0)
        return {
            "total": inbox + in_progress + in_review + done + failed + archived,
            "inbox": inbox,
            "in_progress": in_progress,
            "in_review": in_review,
            "done": done,
            "failed": failed,
            "archived": archived,
            # Legacy aliases
            "todo": inbox,
            "doing": in_progress,
            "pending": inbox,
            "completed": done,
            "cancelled": archived,
        }

    def get_projects(self) -> List[dict]:
        """Get all projects with task counts and status"""
        rows = self._db.execute_fetchall(
            "SELECT project_id, project_name, status, COUNT(*) as cnt "
            "FROM core_tasks WHERE exec_user = ? AND project_id IS NOT NULL "
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
                    "pending": 0, "todo": 0,
                    "in_progress": 0, "doing": 0,
                    "completed": 0, "done": 0,
                }
            projects[pid]["total_tasks"] += r["cnt"]
            st = r["status"]
            if st == "todo":
                projects[pid]["todo"] += r["cnt"]
                projects[pid]["pending"] += r["cnt"]
            elif st == "doing":
                projects[pid]["doing"] += r["cnt"]
                projects[pid]["in_progress"] += r["cnt"]
            elif st == "done":
                projects[pid]["done"] += r["cnt"]
                projects[pid]["completed"] += r["cnt"]
        return sorted(projects.values(), key=lambda x: x["project_id"])

    def get_project_by_id(self, project_id: str) -> Optional[dict]:
        """Get project info by ID"""
        rows = self._db.execute_fetchall(
            "SELECT * FROM core_tasks WHERE exec_user = ? AND project_id = ?",
            (self.exec_user, project_id),
        )
        if not rows:
            return None
        tasks = [_row_to_task(r) for r in rows]
        first_task = tasks[0]
        todo = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "todo")
        doing = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "doing")
        done = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "done")
        failed = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "failed")
        return {
            "project_id": project_id,
            "project_name": first_task.project_name or project_id,
            "total_tasks": len(tasks),
            "pending": todo, "todo": todo,
            "in_progress": doing, "doing": doing,
            "completed": done, "done": done,
            "failed": failed,
            "created_at": min(t.created_at for t in tasks),
            "tasks": [
                {
                    "id": t.id,
                    "description": t.description[:50],
                    "status": t.status if isinstance(t.status, str) else t.status.value,
                    "priority": t.priority if isinstance(t.priority, str) else t.priority.value,
                    "created_at": t.created_at.isoformat(),
                }
                for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)[:5]
            ],
        }

    def get_recent_tasks(self, limit: int = 10) -> List[Task]:
        """Get the most recent tasks"""
        rows = self._db.execute_fetchall(
            "SELECT * FROM core_tasks WHERE exec_user = ? ORDER BY created_at DESC LIMIT ?",
            (self.exec_user, limit),
        )
        return [_row_to_task(r) for r in rows if r]

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
            conditions.append("status = ?")
            params.append(status.lower().strip())
        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id.strip())
        if workspace:
            wh = _ws_hash(workspace.strip())
            conditions.append("workspace_hash = ?")
            params.append(wh)
        if search:
            conditions.append("(description LIKE ? OR id LIKE ? OR project_name LIKE ?)")
            s = f"%{search.lower().strip()}%"
            params.extend([s, s, s])

        where = " AND ".join(conditions)
        count_row = self._db.execute_fetchone(
            f"SELECT COUNT(*) as cnt FROM core_tasks WHERE {where}", params
        )
        total = count_row["cnt"] if count_row else 0

        rows = self._db.execute_fetchall(
            f"SELECT * FROM core_tasks WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
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
        rows = self._db.execute_fetchall(
            "SELECT * FROM core_tasks WHERE exec_user = ? AND status = 'failed' ORDER BY created_at DESC LIMIT ?",
            (self.exec_user, limit),
        )
        return [_row_to_task(r) for r in rows if r]

    def delete_project(self, project_id: str) -> int:
        """Soft delete all tasks in a project."""
        now_ts = datetime.now(timezone.utc).timestamp()
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE core_tasks SET status = 'cancelled', deleted_at = ? "
                "WHERE exec_user = ? AND project_id = ? AND status = 'todo'",
                (now_ts, self.exec_user, project_id),
            )
            count = cursor.rowcount
        if count:
            logger.info(f"Soft deleted project {project_id}: {count} tasks moved to trash")
        return count

    def archive_tasks(self, task_ids: List[str]) -> Dict[str, Any]:
        """Batch archive DONE tasks."""
        archived, skipped = [], {}
        for raw_id in task_ids or []:
            task_id = str(raw_id)
            task = self.get_task(task_id)
            if not task:
                skipped[task_id] = "not_found"; continue
            status_val = task.status if isinstance(task.status, str) else task.status.value
            if status_val != TaskStatus.DONE.value:
                skipped[task_id] = f"invalid_status:{status_val}"; continue
            self._update_task_status(task, TaskStatus.ARCHIVED)
            archived.append(task_id)
        return {"count": len(archived), "archived": archived, "skipped": skipped}

    def unarchive_tasks(self, task_ids: List[str]) -> Dict[str, Any]:
        """Batch unarchive ARCHIVED tasks back to DONE."""
        unarchived, skipped = [], {}
        for raw_id in task_ids or []:
            task_id = str(raw_id)
            task = self.get_task(task_id)
            if not task:
                skipped[task_id] = "not_found"; continue
            status_val = task.status if isinstance(task.status, str) else task.status.value
            if status_val != TaskStatus.ARCHIVED.value:
                skipped[task_id] = f"invalid_status:{status_val}"; continue
            task.archived_at = None
            self._update_task_status(task, TaskStatus.DONE)
            unarchived.append(task_id)
        return {"count": len(unarchived), "unarchived": unarchived, "skipped": skipped}

    def clear_tasks(self, task_ids: List[str]) -> Dict[str, Any]:
        """Batch hard delete ARCHIVED tasks."""
        cleared, skipped = [], {}
        for raw_id in task_ids or []:
            task_id = str(raw_id)
            task = self.get_task(task_id)
            if not task:
                skipped[task_id] = "not_found"; continue
            status_val = task.status if isinstance(task.status, str) else task.status.value
            if status_val != TaskStatus.ARCHIVED.value:
                skipped[task_id] = f"invalid_status:{status_val}"; continue
            try:
                self.delete_task_hard(task_id)
                cleared.append(task_id)
            except Exception as e:
                skipped[task_id] = f"error:{e}"
        return {"count": len(cleared), "cleared": cleared, "skipped": skipped}

    def delete_task_hard(self, task_id: str) -> bool:
        """Hard delete a task."""
        task_id = str(task_id)
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM core_tasks WHERE id = ?", (task_id,))
        logger.info(f"Hard deleted task {task_id}")
        return True

    # ============ Executor Support Methods ============

    def get_next_todo_task(self, workspace: Optional[str] = None) -> Optional[Task]:
        """Get next TODO task from queue for execution"""
        if workspace is not None:
            wh = _ws_hash(workspace)
            row = self._db.execute_fetchone(
                "SELECT * FROM core_tasks WHERE exec_user = ? AND workspace_hash = ? AND status = 'todo' "
                "ORDER BY CASE priority WHEN 'project' THEN 0 ELSE 1 END, created_at ASC LIMIT 1",
                (self.exec_user, wh),
            )
        else:
            row = self._db.execute_fetchone(
                "SELECT * FROM core_tasks WHERE exec_user = ? AND status = 'todo' "
                "ORDER BY CASE priority WHEN 'project' THEN 0 ELSE 1 END, created_at ASC LIMIT 1",
                (self.exec_user,),
            )
        return _row_to_task(row) if row else None

    def start_task(self, task_id: str) -> Optional[Task]:
        """Mark task as DOING"""
        task = self.get_task(task_id)
        if not task:
            return None
        status_val = task.status if isinstance(task.status, str) else task.status.value
        if status_val != TaskStatus.INBOX.value:
            logger.warning(f"Task {task_id} is not in TODO status, cannot start")
            return None
        task.attempt_count += 1
        self._update_task_status(task, TaskStatus.IN_PROGRESS)
        logger.info(f"Task {task_id} started (attempt {task.attempt_count})")
        return task

    def complete_task(self, task_id: str, error_message: Optional[str] = None) -> Optional[Task]:
        """Mark task as DONE or FAILED"""
        task = self.get_task(task_id)
        if not task:
            return None
        if error_message:
            task.error_message = error_message
            self._update_task_status(task, TaskStatus.FAILED)
            logger.error(f"Task {task_id} failed: {error_message}")
        else:
            self._update_task_status(task, TaskStatus.DONE)
            logger.info(f"Task {task_id} completed successfully")
        return task

    def get_executing_count(self, workspace: Optional[str] = None) -> int:
        """Get count of currently executing tasks for a workspace"""
        if workspace:
            wh = _ws_hash(workspace)
            row = self._db.execute_fetchone(
                "SELECT COUNT(*) as cnt FROM core_tasks WHERE exec_user = ? AND workspace_hash = ? AND status = 'doing'",
                (self.exec_user, wh),
            )
        else:
            row = self._db.execute_fetchone(
                "SELECT COUNT(*) as cnt FROM core_tasks WHERE exec_user = ? AND status = 'doing'",
                (self.exec_user,),
            )
        return row["cnt"] if row else 0

    def get_all_workspaces(self) -> List[str]:
        """Get all unique workspace hashes with tasks"""
        rows = self._db.execute_fetchall(
            "SELECT DISTINCT workspace_hash FROM core_tasks WHERE exec_user = ? AND workspace_hash != ''",
            (self.exec_user,),
        )
        return [r["workspace_hash"] for r in rows]

    def requeue_stuck_tasks(self, timeout_seconds: int = 3600) -> int:
        """Requeue tasks that have been DOING for too long"""
        cutoff = datetime.now(timezone.utc).timestamp() - timeout_seconds
        rows = self._db.execute_fetchall(
            "SELECT * FROM core_tasks WHERE exec_user = ? AND status = 'doing' AND started_at < ?",
            (self.exec_user, cutoff),
        )
        count = 0
        for row in rows:
            task = _row_to_task(row)
            self._update_task_status(task, TaskStatus.INBOX)
            logger.warning(f"Task {task.id} requeued after timeout")
            count += 1
        return count

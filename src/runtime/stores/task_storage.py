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
import hashlib
import json
import uuid
from typing import List, Optional, Dict, Any

import logging

from ..models.task_models import Task, TaskPriority, TaskStatus
from .db import Database, get_db

logger = logging.getLogger(__name__)


def get_redis_client():
    """Compatibility shim for legacy tests/mocks expecting Redis client accessor."""
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


def _task_to_row(task: Task) -> dict:
    """Convert Task model to SQLite row dict."""
    ws_hash = ""
    if task.workspace:
        ws_hash = hashlib.md5(task.workspace.encode("utf-8")).hexdigest()[:8]

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
        "context_json": json.dumps(task.context, ensure_ascii=False) if task.context else None,
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
        status=TaskStatus.from_legacy(row.get("status", "inbox")),
        assigned_to=row.get("assigned_to"),
        tags=tags,
        due_date=_ts_to_dt(row.get("due_date")),
        ticket_ref=row.get("ticket_ref"),
        project_id=row.get("project_id"),
        project_name=row.get("project_name"),
        workspace=row.get("workspace"),
        exec_user=row.get("exec_user", "default"),
        provider=row.get("provider", "claude"),
        alias=row.get("alias"),
        model=row.get("model"),
        session_id=row.get("session_id"),
        source_session_id=row.get("source_session_id"),
        context=ctx,
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
    )


_TASK_FIELDS = list(_task_to_row(Task(id="__schema__", description="__schema__")).keys())
_TASK_COLUMNS = ", ".join(_TASK_FIELDS)
_TASK_PLACEHOLDERS = ", ".join(["?"] * len(_TASK_FIELDS))


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
        self.exec_user = exec_user
        self._db = db or get_db()
        logger.info(f"TaskQueue initialized for exec_user: {exec_user}")

    def _ws_hash(self, workspace: Optional[str]) -> str:
        if not workspace:
            return ""
        return hashlib.md5(workspace.encode("utf-8")).hexdigest()[:8]

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

        from src.server.utils.ids import gen_session_id
        session_id = gen_session_id()

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
            assigned_to=(assigned_to or "").strip() or None,
            tags=tags or [],
            due_date=due_date,
            ticket_ref=(ticket_ref or "").strip() or None,
            provider=normalized_provider,
            alias=alias_value,
            model=(model or "").strip() or None,
            session_id=session_id,
            source_session_id=source_session_id,
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

        row = _task_to_row(task)
        values = [row[k] for k in _TASK_FIELDS]

        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO tasks ({_TASK_COLUMNS}) VALUES ({_TASK_PLACEHOLDERS})",
                values,
            )

        project_info = f" [Project: {project_name}]" if project_name else ""
        workspace_info = f" [Workspace: {workspace}]" if workspace else ""
        logger.info(f"Added task {task.id}: {description[:50]}...{project_info}{workspace_info}")
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
            self._update_task_status(task, TaskStatus.INBOX)
        except Exception:
            pass

        self.update_task(task)
        logger.info(f"Enqueued chat_continue for task {task.id}")
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        task_id = str(task_id)
        row = self._db.execute_fetchone(
            "SELECT * FROM tasks WHERE id = ? LIMIT 1",
            (task_id,),
        )
        if not row:
            return None
        try:
            return _row_to_task(row)
        except Exception as e:
            logger.error(f"Failed to parse task {task_id}: {e}")
            return None

    def find_task_by_session_id(self, session_id: str) -> Optional[Task]:
        """Find a task whose session_id matches the given value."""
        if not session_id:
            return None
        row = self._db.execute_fetchone(
            "SELECT * FROM tasks WHERE session_id = ? LIMIT 1",
            (session_id,),
        )
        if row:
            try:
                return _row_to_task(row)
            except Exception:
                pass
        return None

    def get_pending_tasks(self, limit: int = 10) -> List[Task]:
        """Get ready-to-run inbox tasks sorted by priority."""
        rows = self._db.execute_fetchall(
            "SELECT * FROM tasks WHERE exec_user = ? AND status = 'inbox' "
            "ORDER BY CASE priority WHEN 'project' THEN 0 WHEN 'serious' THEN 1 ELSE 2 END, created_at ASC "
            "LIMIT ?",
            (self.exec_user, limit),
        )
        return [_row_to_task(r) for r in rows if r]

    def get_in_progress_tasks(self) -> List[Task]:
        """Get all in-progress tasks."""
        rows = self._db.execute_fetchall(
            "SELECT * FROM tasks WHERE exec_user = ? AND status = 'in_progress'",
            (self.exec_user,),
        )
        return [_row_to_task(r) for r in rows if r]

    def _update_task_status(self, task: Task, new_status: TaskStatus) -> None:
        """Update collaboration status and keep runtime layer in sync."""
        now = datetime.now(timezone.utc)
        task.status = new_status

        if new_status == TaskStatus.IN_PROGRESS:
            task.started_at = now
            task.runtime_status = "running"
            task.runtime_orphaned = False
            task.runtime_orphaned_at = None
            task.runtime_last_heartbeat = now
        elif new_status == TaskStatus.FAILED:
            if not task.completed_at:
                task.completed_at = now
            task.runtime_status = "failed"
        elif new_status in (TaskStatus.DONE, TaskStatus.ARCHIVED, TaskStatus.ARCHIVED):
            if new_status == TaskStatus.DONE and not task.completed_at:
                task.completed_at = now
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

        self.update_task(task)

    def cancel_task(self, task_id: str) -> Optional[Task]:
        """Cancel TODO task (soft delete)"""
        task_id = str(task_id)
        task = self.get_task(task_id)
        if not task:
            return None
        status_val = task.status if isinstance(task.status, str) else task.status.value
        if status_val in (TaskStatus.INBOX.value, TaskStatus.ASSIGNED.value, TaskStatus.AWAITING_OWNER.value):
            self._update_task_status(task, TaskStatus.ARCHIVED)
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
        self._update_task_status(task, new_status)
        logger.info(f"Task {task_id} status manually updated: {old_status.value} -> {new_status.value}")
        return task

    def get_queue_status(self) -> dict:
        """Get overall queue status"""
        rows = self._db.execute_fetchall(
            "SELECT status, COUNT(*) as cnt FROM tasks WHERE exec_user = ? GROUP BY status",
            (self.exec_user,),
        )
        counts = {r["status"]: r["cnt"] for r in rows}
        inbox = counts.get("inbox", 0)
        assigned = counts.get("assigned", 0)
        awaiting_owner = counts.get("awaiting_owner", 0)
        in_progress = counts.get("in_progress", 0)
        review = counts.get("review", 0)
        quality_review = counts.get("quality_review", 0)
        done = counts.get("done", 0)
        failed = counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)
        archived = counts.get("archived", 0)
        return {
            "total": inbox + assigned + awaiting_owner + in_progress + review + quality_review + done + failed + cancelled + archived,
            "inbox": inbox,
            "assigned": assigned,
            "awaiting_owner": awaiting_owner,
            "in_progress": in_progress,
            "review": review,
            "quality_review": quality_review,
            "done": done,
            "failed": failed,
            "cancelled": cancelled,
            "archived": archived,
            # backward-compatible aliases
            "todo": inbox,
            "doing": in_progress,
            "pending": inbox,
            "completed": done,
        }

    def update_task(self, task: Task) -> bool:
        """Update task data in SQLite."""
        row = _task_to_row(task)
        update_cols = [k for k in _TASK_FIELDS if k not in ("id", "exec_user")]
        set_clause = ", ".join(f"{k} = ?" for k in update_cols)
        values = [row[k] for k in update_cols] + [task.exec_user or self.exec_user, task.id]

        with self._db.transaction() as conn:
            cursor = conn.execute(
                f"UPDATE tasks SET {set_clause} WHERE exec_user = ? AND id = ?",
                values,
            )
            if cursor.rowcount == 0:
                logger.warning(f"Task {task.id} not found for update")
                return False
        logger.debug(f"Updated task {task.id}")
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
                    "inbox": 0,
                    "assigned": 0,
                    "awaiting_owner": 0,
                    "in_progress": 0,
                    "review": 0,
                    "quality_review": 0,
                    "done": 0,
                    # backward-compatible aliases
                    "todo": 0,
                    "doing": 0,
                    "pending": 0,
                    "completed": 0,
                }
            projects[pid]["total_tasks"] += r["cnt"]
            st = r["status"]
            if st in projects[pid]:
                projects[pid][st] += r["cnt"]
            if st == "inbox":
                projects[pid]["todo"] += r["cnt"]
                projects[pid]["pending"] += r["cnt"]
            elif st == "in_progress":
                projects[pid]["doing"] += r["cnt"]
            elif st == "done":
                projects[pid]["completed"] += r["cnt"]
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
        inbox = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "inbox")
        assigned = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "assigned")
        awaiting_owner = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "awaiting_owner")
        in_progress = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "in_progress")
        review = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "review")
        quality_review = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "quality_review")
        done = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "done")
        failed = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == "failed")
        return {
            "project_id": project_id,
            "project_name": first_task.project_name or project_id,
            "total_tasks": len(tasks),
            "inbox": inbox,
            "assigned": assigned,
            "awaiting_owner": awaiting_owner,
            "in_progress": in_progress,
            "review": review,
            "quality_review": quality_review,
            "done": done,
            "pending": inbox, "todo": inbox,
            "doing": in_progress,
            "completed": done,
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
        rows = self._db.execute_fetchall(
            "SELECT * FROM tasks WHERE exec_user = ? ORDER BY created_at DESC LIMIT ?",
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
        rows = self._db.execute_fetchall(
            "SELECT * FROM tasks WHERE exec_user = ? AND status = 'failed' ORDER BY created_at DESC LIMIT ?",
            (self.exec_user, limit),
        )
        return [_row_to_task(r) for r in rows if r]

    def delete_project(self, project_id: str) -> int:
        """Soft delete all tasks in a project."""
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE tasks SET status = 'cancelled', deleted_at = ? "
                "WHERE exec_user = ? AND project_id = ? AND status IN ('inbox', 'assigned', 'awaiting_owner')",
                (datetime.now(timezone.utc).timestamp(), self.exec_user, project_id),
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
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        logger.info(f"Hard deleted task {task_id}")
        return True

    # ============ Executor Support Methods ============

    def get_next_todo_task(self, workspace: Optional[str] = None) -> Optional[Task]:
        """Get next TODO task from queue for execution"""
        if workspace is not None:
            ws_hash = self._ws_hash(workspace)
            row = self._db.execute_fetchone(
                "SELECT * FROM tasks WHERE exec_user = ? AND workspace_hash = ? AND status = 'inbox' "
                "ORDER BY CASE priority WHEN 'project' THEN 0 WHEN 'serious' THEN 1 ELSE 2 END, created_at ASC LIMIT 1", 
                (self.exec_user, ws_hash),
            )
        else:
            row = self._db.execute_fetchone(
                "SELECT * FROM tasks WHERE exec_user = ? AND status = 'inbox' "
                "ORDER BY CASE priority WHEN 'project' THEN 0 WHEN 'serious' THEN 1 ELSE 2 END, created_at ASC LIMIT 1", 
                (self.exec_user,),
            )
        return _row_to_task(row) if row else None

    def start_task(self, task_id: str) -> Optional[Task]:
        """Mark task as in progress."""
        task = self.get_task(task_id)
        if not task:
            return None
        status_val = task.status if isinstance(task.status, str) else task.status.value
        if status_val not in (TaskStatus.INBOX.value, TaskStatus.ASSIGNED.value):
            logger.warning(f"Task {task_id} is not ready to start, cannot start")
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
            return self.fail_task(task_id, error_message=error_message)
        self._update_task_status(task, TaskStatus.DONE)
        logger.info(f"Task {task_id} completed successfully")
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
        self._update_task_status(task, TaskStatus.INBOX)
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
        self._update_task_status(task, TaskStatus.FAILED)
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
        self._update_task_status(task, TaskStatus.INBOX)
        return task

    def list_orphan_tasks(self, limit: int = 100) -> List[Task]:
        rows = self._db.execute_fetchall(
            "SELECT * FROM tasks WHERE exec_user = ? AND (runtime_orphaned = 1 OR runtime_status = 'orphaned') ORDER BY created_at DESC LIMIT ?",
            (self.exec_user, limit),
        )
        return [_row_to_task(r) for r in rows if r]

    def get_executing_count(self, workspace: Optional[str] = None) -> int:
        """Get count of currently executing tasks for a workspace"""
        if workspace:
            ws_hash = self._ws_hash(workspace)
            row = self._db.execute_fetchone(
                "SELECT COUNT(*) as cnt FROM tasks WHERE exec_user = ? AND workspace_hash = ? AND status = 'in_progress'",
                (self.exec_user, ws_hash),
            )
        else:
            row = self._db.execute_fetchone(
                "SELECT COUNT(*) as cnt FROM tasks WHERE exec_user = ? AND status = 'in_progress'",
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
        cutoff = datetime.now(timezone.utc).timestamp() - timeout_seconds
        rows = self._db.execute_fetchall(
            "SELECT * FROM tasks WHERE exec_user = ? AND status = 'in_progress' AND started_at < ?",
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

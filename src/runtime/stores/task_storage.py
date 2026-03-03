# -*- coding: utf-8 -*-
"""Redis task storage for slash commands

Provides TaskQueue class for managing tasks in Redis.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid
from typing import List, Optional, Dict, Any

import logging

from ..models.task_models import Task, TaskPriority, TaskStatus
from .redis_client import get_redis_client, RedisClient

logger = logging.getLogger(__name__)


class TaskQueue:
    """Task queue manager with Redis backend
    
    Redis key structure:
    - task:{exec_user}:{task_id} - Task hash data
    - tasks:{exec_user}:all - Sorted set of all task IDs (score = created_at timestamp)
    - tasks:{exec_user}:by_status:{status} - Set of task IDs by status
    - tasks:{exec_user}:by_project:{project_id} - Set of task IDs by project
    - tasks:{exec_user}:by_workspace:{workspace_hash} - Set of task IDs by workspace
    - queue:{exec_user}:{workspace_hash}:todo - List of TODO task IDs (queue for execution)
    - executing:{exec_user}:{workspace_hash} - Set of currently executing task IDs
    """

    def __init__(
        self,
        db_path: str = None,
        exec_user: str = "default",
        redis_client: Optional[RedisClient] = None,
    ):
        """Initialize task queue with Redis

        Args:
            db_path: Ignored, kept for backward compatibility
            exec_user: Exec user name for task isolation
            redis_client: Optional injected Redis client (for tests/hosts)
        """
        self.exec_user = exec_user
        self._redis: RedisClient = redis_client or get_redis_client()
        logger.info(f"TaskQueue initialized for exec_user: {exec_user}")

    def _task_key(self, task_id: str) -> str:
        """Get Redis key for task data"""
        return f"task:{self.exec_user}:{task_id}"
    
    def _all_tasks_key(self) -> str:
        """Get Redis key for all tasks sorted set"""
        return f"tasks:{self.exec_user}:all"
    
    def _status_key(self, status: TaskStatus) -> str:
        """Get Redis key for tasks by status"""
        return f"tasks:{self.exec_user}:by_status:{status.value}"
    
    def _project_key(self, project_id: str) -> str:
        """Get Redis key for tasks by project"""
        return f"tasks:{self.exec_user}:by_project:{project_id}"
    
    def _workspace_key(self, workspace: str) -> str:
        """Get Redis key for tasks by workspace"""
        # Use stable hash for shorter keys
        import hashlib
        ws_str = (workspace or "default").encode("utf-8")
        workspace_hash = hashlib.md5(ws_str).hexdigest()[:8]
        return f"tasks:{self.exec_user}:by_workspace:{workspace_hash}"

    def _queue_key(self, workspace: str) -> str:
        """Get Redis key for workspace TODO queue"""
        import hashlib
        ws_str = (workspace or "default").encode("utf-8")
        workspace_hash = hashlib.md5(ws_str).hexdigest()[:8]
        return f"queue:{self.exec_user}:{workspace_hash}:todo"

    def _executing_key(self, workspace: str) -> str:
        """Get Redis key for executing tasks set"""
        import hashlib
        ws_str = (workspace or "default").encode("utf-8")
        workspace_hash = hashlib.md5(ws_str).hexdigest()[:8]
        return f"executing:{self.exec_user}:{workspace_hash}"

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
        depends_on: Optional[list] = None,
        response_url: Optional[str] = None,
        callback_msg_id: Optional[str] = None,
        callback_user: Optional[str] = None,
    ) -> Task:
        """Add new task to queue

        Args:
            source_session_id: Optional session ID from the source context (e.g., chat session).
                              If provided, task session_id will be {source_session_id}_{task_id}.
                              Otherwise, defaults to task_{task_id}.
            exec_user: Optional exec_user for task execution.
                       If not provided, uses self.exec_user (the queue's default exec_user).
            response_url: Optional callback URL for task completion notification.
            callback_msg_id: Optional message ID to pass back in callback.
            callback_user: Optional user identifier for callback.
        """
        # Generate task_id first if not provided
        actual_task_id = str(task_id) if task_id else str(uuid.uuid4())[:8]
        
        # Use provided exec_user or fallback to queue's default
        effective_exec_user = exec_user or self.exec_user
        
        # Generate session_id based on source_session_id
        logger.info(f"add_task called with source_session_id={source_session_id!r}, task_id={actual_task_id}, exec_user={effective_exec_user}")
        if source_session_id:
            session_id = f"{source_session_id}_{actual_task_id}"
        else:
            session_id = f"task_{actual_task_id}"
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
            model=(model or "").strip() or None,
            session_id=session_id,
            source_session_id=source_session_id,
            depends_on=depends_on or [],
            response_url=response_url,
            callback_msg_id=callback_msg_id,
            callback_user=callback_user,
        )
        
        # Store task data
        self._redis.hset(self._task_key(task.id), task.to_redis_hash())
        
        # Add to all tasks sorted set (score = timestamp for ordering)
        timestamp = task.created_at.timestamp()
        self._redis.zadd(self._all_tasks_key(), {task.id: timestamp})
        
        # Add to status index
        self._redis.sadd(self._status_key(TaskStatus.TODO), task.id)
        
        # Add to project index if applicable
        if project_id:
            self._redis.sadd(self._project_key(project_id), task.id)
        
        # Add to workspace index
        self._redis.sadd(self._workspace_key(workspace), task.id)
        
        # Add to TODO queue for execution
        # Priority: PROJECT tasks go to front, others to back
        if priority == TaskPriority.PROJECT:
            self._redis.lpush(self._queue_key(workspace), task.id)
        else:
            self._redis.rpush(self._queue_key(workspace), task.id)
        
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
    ) -> Optional[Task]:
        """Re-enqueue an existing task as a background chat-continue run.

        This keeps the same task id and session id (`task_<id>`), but updates task.context
        with the latest user message for the next run.

        Rules:
        - If task is DOING, do not enqueue.
        - If task is CANCELLED, do not enqueue.
        - Avoid duplicating task id in the TODO queue.

        Args:
            response_url: Optional callback URL for completion notification.
            callback_msg_id: Optional message ID to pass back in callback.
            callback_user: Optional user identifier for callback.
        """
        task_id = str(task_id)
        task = self.get_task(task_id)
        if not task:
            return None

        status_val = task.status if isinstance(task.status, str) else task.status.value
        if status_val == TaskStatus.DOING.value:
            return task
        if status_val == TaskStatus.CANCELLED.value:
            raise ValueError("Task is cancelled")

        msg = (message or "").strip()
        if not msg:
            raise ValueError("Empty message")

        # Update context for next run
        ctx: Dict[str, Any] = task.context or {}
        ctx["next_user_message"] = msg
        ctx["next_user_message_id"] = f"continue-{uuid.uuid4().hex[:8]}"
        ctx["next_run_kind"] = "chat_continue"
        task.context = ctx

        # Update callback info for this run (may differ from original task creation)
        updates: Dict[str, str] = {"context": json.dumps(ctx, ensure_ascii=False)}
        if response_url:
            task.response_url = response_url
            updates["response_url"] = response_url
        if callback_msg_id:
            task.callback_msg_id = callback_msg_id
            updates["callback_msg_id"] = callback_msg_id
        if callback_user:
            task.callback_user = callback_user
            updates["callback_user"] = callback_user

        # Update model if specified (allows switching model on continue)
        effective_model = (model or "").strip()
        if effective_model:
            task.model = effective_model
            updates["model"] = effective_model

        self._redis.hset(self._task_key(task.id), updates)

        # Move status to TODO (from DONE/FAILED/etc.)
        try:
            self._update_task_status(task, TaskStatus.TODO)
        except Exception:
            # best-effort
            pass

        # Ensure task appears only once in the queue
        try:
            self._redis.lrem(self._queue_key(task.workspace), 0, task.id)
        except Exception:
            pass

        try:
            if task.priority == TaskPriority.SERIOUS:
                self._redis.lpush(self._queue_key(task.workspace), task.id)
            else:
                self._redis.rpush(self._queue_key(task.workspace), task.id)
            logger.info(f"Enqueued chat_continue for task {task.id}", extra={
                "task_id": task.id,
                "workspace": task.workspace,
                "user_message": message[:50] if message else "",
            })
        except Exception as e:
            logger.error(f"Failed to enqueue chat_continue for task {task.id}: {e}")

        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        # Support both string and int IDs for backward compatibility
        task_id = str(task_id)
        data = self._redis.hgetall(self._task_key(task_id))
        if not data:
            return None
        try:
            return Task.from_redis_hash(data)
        except Exception as e:
            logger.error(f"Failed to parse task {task_id}: {e}")
            return None

    def find_task_by_session_id(self, session_id: str) -> Optional[Task]:
        """Find a task whose session_id matches the given value.

        Task session_id formats:
          - ``task_{task_id}``  (standalone task)
          - ``{source_session_id}_{task_id}``  (task derived from a chat session)

        For ``task_`` prefixed session IDs we can look up the task directly.
        Otherwise we scan all tasks for a matching ``session_id`` field.

        Returns:
            The matching Task, or None.
        """
        # Fast path: task_ prefix → direct lookup
        if session_id.startswith("task_"):
            task_id = session_id[len("task_"):]
            task = self.get_task(task_id)
            if task:
                return task

        # Slow path: scan all tasks and match session_id field
        all_task_ids = self._redis.zrange(self._all_tasks_key(), 0, -1)
        for task_id in all_task_ids:
            try:
                # Quick check via Redis hash field to avoid full deserialization
                stored_sid = self._redis.hget(self._task_key(task_id), "session_id")
                if stored_sid == session_id:
                    task = self.get_task(task_id)
                    if task:
                        return task
            except Exception:
                continue
        return None

    def get_pending_tasks(self, limit: int = 10) -> List[Task]:
        """Get TODO tasks sorted by priority (SERIOUS first, then by creation time)"""
        task_ids = self._redis.smembers(self._status_key(TaskStatus.TODO))
        if not task_ids:
            return []
        
        tasks = []
        for task_id in task_ids:
            task = self.get_task(task_id)
            if task:
                tasks.append(task)
        
        # Sort: SERIOUS first, then by created_at
        def sort_key(t: Task):
            priority_order = 0 if t.priority == TaskPriority.SERIOUS else 1
            return (priority_order, t.created_at)
        
        tasks.sort(key=sort_key)
        return tasks[:limit]

    def get_in_progress_tasks(self) -> List[Task]:
        """Get all DOING tasks"""
        task_ids = self._redis.smembers(self._status_key(TaskStatus.DOING))
        tasks = []
        for task_id in task_ids:
            task = self.get_task(task_id)
            if task:
                tasks.append(task)
        return tasks

    def _update_task_status(self, task: Task, new_status: TaskStatus) -> None:
        """Update task status and related indexes"""
        old_status = TaskStatus(task.status) if isinstance(task.status, str) else task.status
        
        # Remove from old status set
        self._redis.srem(self._status_key(old_status), task.id)
        
        # Add to new status set
        self._redis.sadd(self._status_key(new_status), task.id)
        
        # Update task data
        task.status = new_status
        now = datetime.now(timezone.utc)
        if new_status == TaskStatus.DOING:
            # Prefer reflecting the latest attempt start time
            task.started_at = now
        elif new_status in (TaskStatus.DONE, TaskStatus.FAILED):
            # Preserve completion time if already set (e.g. unarchive back to DONE)
            if not task.completed_at:
                task.completed_at = now
        elif new_status == TaskStatus.ARCHIVED:
            # Archived time is used as updated_at for grouping in UI
            task.archived_at = now
        elif new_status == TaskStatus.CANCELLED:
            if not task.deleted_at:
                task.deleted_at = now
        
        self._redis.hset(self._task_key(task.id), task.to_redis_hash())

    def cancel_task(self, task_id: str) -> Optional[Task]:
        """Cancel TODO task (soft delete)"""
        task_id = str(task_id)
        task = self.get_task(task_id)
        if not task:
            return None
        
        if task.status == TaskStatus.TODO.value or task.status == TaskStatus.TODO:
            # Remove from TODO queue
            self._redis.lrem(self._queue_key(task.workspace), 0, task.id)
            
            # Update status
            self._update_task_status(task, TaskStatus.CANCELLED)
            logger.info(f"Task {task_id} cancelled and moved to trash")
        
        return task

    def update_task_status(self, task_id: str, new_status: TaskStatus) -> Optional[Task]:
        """Manually update task status.
        
        Used to unblock dependent tasks or change task state manually.
        Handles queue membership changes based on status transitions.
        """
        task_id = str(task_id)
        task = self.get_task(task_id)
        if not task:
            return None
        
        old_status_val = task.status if isinstance(task.status, str) else task.status.value
        old_status = TaskStatus(old_status_val)
        
        # Handle queue transitions
        if old_status == TaskStatus.TODO and new_status != TaskStatus.TODO:
            # Remove from TODO queue if leaving TODO
            self._redis.lrem(self._queue_key(task.workspace), 0, task.id)
        elif old_status != TaskStatus.TODO and new_status == TaskStatus.TODO:
            # Add back to TODO queue if returning to TODO
            self._redis.rpush(self._queue_key(task.workspace), task.id)
        
        # Handle executing set
        if old_status == TaskStatus.DOING and new_status != TaskStatus.DOING:
            self._redis.srem(self._executing_key(task.workspace), task.id)
        elif old_status != TaskStatus.DOING and new_status == TaskStatus.DOING:
            self._redis.sadd(self._executing_key(task.workspace), task.id)
        
        self._update_task_status(task, new_status)
        logger.info(f"Task {task_id} status manually updated: {old_status_val} -> {new_status.value}")
        
        return task

    def get_queue_status(self) -> dict:
        """Get overall queue status"""
        todo = self._redis.scard(self._status_key(TaskStatus.TODO))
        doing = self._redis.scard(self._status_key(TaskStatus.DOING))
        done = self._redis.scard(self._status_key(TaskStatus.DONE))
        failed = self._redis.scard(self._status_key(TaskStatus.FAILED))
        cancelled = self._redis.scard(self._status_key(TaskStatus.CANCELLED))
        archived = self._redis.scard(self._status_key(TaskStatus.ARCHIVED))

        return {
            "total": todo + doing + done + failed + cancelled + archived,
            "todo": todo,
            "doing": doing,
            "done": done,
            "failed": failed,
            "cancelled": cancelled,
            "archived": archived,
            # Backward compatibility aliases
            "pending": todo,
            "in_progress": doing,
            "completed": done,
        }

    def update_task(self, task: Task) -> bool:
        """Update task data in Redis.

        This saves all task fields including claude_session_id.
        Does not change queue membership or status indices.

        Args:
            task: Task object with updated fields

        Returns:
            True if successful, False if task doesn't exist
        """
        if not self._redis.exists(self._task_key(task.id)):
            logger.warning(f"Task {task.id} not found for update")
            return False

        self._redis.hset(self._task_key(task.id), task.to_redis_hash())
        logger.debug(f"Updated task {task.id}")
        return True

    def get_projects(self) -> List[dict]:
        """Get all projects with task counts and status"""
        # Find all project keys
        project_keys = list(self._redis.scan_iter(f"tasks:{self.exec_user}:by_project:*"))
        
        result = []
        for key in project_keys:
            # Extract project_id from key
            project_id = key.split(":")[-1]
            task_ids = self._redis.smembers(key)
            
            if not task_ids:
                continue
            
            # Count tasks by status
            todo = doing = done = 0
            project_name = None
            
            for task_id in task_ids:
                task = self.get_task(task_id)
                if task:
                    if not project_name:
                        project_name = task.project_name
                    status = task.status if isinstance(task.status, str) else task.status.value
                    if status == TaskStatus.TODO.value:
                        todo += 1
                    elif status == TaskStatus.DOING.value:
                        doing += 1
                    elif status == TaskStatus.DONE.value:
                        done += 1
            
            result.append({
                "project_id": project_id,
                "project_name": project_name or project_id,
                "total_tasks": len(task_ids),
                "pending": todo,  # backward compatibility
                "todo": todo,
                "in_progress": doing,  # backward compatibility
                "doing": doing,
                "completed": done,  # backward compatibility
                "done": done,
            })
        
        return sorted(result, key=lambda x: x["project_id"])

    def get_project_by_id(self, project_id: str) -> Optional[dict]:
        """Get project info by ID"""
        task_ids = self._redis.smembers(self._project_key(project_id))
        if not task_ids:
            return None
        
        tasks = []
        for task_id in task_ids:
            task = self.get_task(task_id)
            if task:
                tasks.append(task)
        
        if not tasks:
            return None
        
        first_task = tasks[0]
        todo = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == TaskStatus.TODO.value)
        doing = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == TaskStatus.DOING.value)
        done = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == TaskStatus.DONE.value)
        failed = sum(1 for t in tasks if (t.status if isinstance(t.status, str) else t.status.value) == TaskStatus.FAILED.value)
        
        return {
            "project_id": project_id,
            "project_name": first_task.project_name or project_id,
            "total_tasks": len(tasks),
            "pending": todo,
            "todo": todo,
            "in_progress": doing,
            "doing": doing,
            "completed": done,
            "done": done,
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
        # Get task IDs from sorted set (most recent first)
        task_ids = self._redis.zrange(self._all_tasks_key(), -limit, -1)
        task_ids = list(reversed(task_ids))  # Most recent first
        
        tasks = []
        for task_id in task_ids:
            task = self.get_task(task_id)
            if task:
                tasks.append(task)
        
        return tasks

    def list_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        workspace: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[List[Task], int]:
        """List tasks with simple filtering and pagination.

        Notes:
            - This implementation favors correctness and minimal dependencies.
            - Filtering is done by loading task objects; for large datasets this can be optimized.

        Returns:
            (tasks, total)
        """
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20

        # Fetch all task IDs, most recent first
        all_task_ids = self._redis.zrange(self._all_tasks_key(), 0, -1)
        all_task_ids = list(reversed(all_task_ids))

        status_norm = status.lower().strip() if status else None
        project_norm = project_id.strip() if project_id else None
        workspace_norm = workspace.strip() if workspace else None
        search_norm = search.lower().strip() if search else None

        filtered: List[Task] = []
        for task_id in all_task_ids:
            task = self.get_task(task_id)
            if not task:
                continue

            task_status = task.status if isinstance(task.status, str) else task.status.value
            if status_norm and task_status != status_norm:
                continue

            if project_norm and (task.project_id or "") != project_norm:
                continue

            if workspace_norm and (task.workspace or "") != workspace_norm:
                continue

            if search_norm:
                hay = " ".join([
                    task.id or "",
                    task.description or "",
                    task.project_id or "",
                    task.project_name or "",
                    task.workspace or "",
                    task_status or "",
                ]).lower()
                if search_norm not in hay:
                    continue

            filtered.append(task)

        total = len(filtered)

        start = (page - 1) * page_size
        end = start + page_size
        return filtered[start:end], total

    def get_failed_tasks(self, limit: int = 10) -> List[Task]:
        """Get the most recent failed tasks"""
        task_ids = self._redis.smembers(self._status_key(TaskStatus.FAILED))
        
        tasks = []
        for task_id in task_ids:
            task = self.get_task(task_id)
            if task:
                tasks.append(task)
        
        # Sort by created_at descending
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    def delete_project(self, project_id: str) -> int:
        """Soft delete all tasks in a project (mark as CANCELLED). Returns count of affected tasks."""
        task_ids = self._redis.smembers(self._project_key(project_id))
        count = 0

        for task_id in task_ids:
            task = self.get_task(task_id)
            if task and (task.status == TaskStatus.TODO.value or task.status == TaskStatus.TODO):
                # Remove from TODO queue
                self._redis.lrem(self._queue_key(task.workspace), 0, task.id)
                # Update status
                self._update_task_status(task, TaskStatus.CANCELLED)
                count += 1

        if count:
            logger.info(f"Soft deleted project {project_id}: {count} tasks moved to trash")

        return count

    def archive_tasks(self, task_ids: List[str]) -> Dict[str, Any]:
        """Batch archive tasks.

        Rules:
        - Only DONE tasks can be archived.
        - Archived tasks move to TaskStatus.ARCHIVED.

        Returns:
            {"count": int, "archived": [ids], "skipped": {id: reason}}
        """
        archived: List[str] = []
        skipped: Dict[str, str] = {}

        for raw_id in task_ids or []:
            task_id = str(raw_id)
            task = self.get_task(task_id)
            if not task:
                skipped[task_id] = "not_found"
                continue

            status_val = task.status if isinstance(task.status, str) else task.status.value
            if status_val != TaskStatus.DONE.value:
                skipped[task_id] = f"invalid_status:{status_val}"
                continue

            # Best-effort: ensure it is not in execution queues
            try:
                self._redis.lrem(self._queue_key(task.workspace), 0, task.id)
            except Exception:
                pass
            try:
                self._redis.srem(self._executing_key(task.workspace), task.id)
            except Exception:
                pass

            self._update_task_status(task, TaskStatus.ARCHIVED)
            archived.append(task_id)

        return {"count": len(archived), "archived": archived, "skipped": skipped}

    def unarchive_tasks(self, task_ids: List[str]) -> Dict[str, Any]:
        """Batch unarchive tasks.

        Rules:
        - Only ARCHIVED tasks can be unarchived.
        - Unarchive moves task back to DONE.

        Returns:
            {"count": int, "unarchived": [ids], "skipped": {id: reason}}
        """
        unarchived: List[str] = []
        skipped: Dict[str, str] = {}

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

            # Clear archived marker
            try:
                task.archived_at = None
            except Exception:
                pass

            self._update_task_status(task, TaskStatus.DONE)

            # Ensure archived_at field is removed from Redis hash
            try:
                self._redis.hdel(self._task_key(task.id), "archived_at")
            except Exception:
                pass

            unarchived.append(task_id)

        return {"count": len(unarchived), "unarchived": unarchived, "skipped": skipped}

    def clear_tasks(self, task_ids: List[str]) -> Dict[str, Any]:
        """Batch hard delete tasks.

        Intended for clearing ARCHIVED tasks from UI.

        Returns:
            {"count": int, "cleared": [ids], "skipped": {id: reason}}
        """
        cleared: List[str] = []
        skipped: Dict[str, str] = {}

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
        """Hard delete a task and all related indexes.

        This removes the task from:
        - task hash
        - all tasks zset
        - status/project/workspace indexes
        - todo queue / executing set (best effort)

        The operation is idempotent.
        """
        task_id = str(task_id)

        # Best-effort cleanups even if task is missing
        removed_any = False

        task = self.get_task(task_id)
        if task:
            # Remove from status index
            try:
                status_val = task.status if isinstance(task.status, str) else task.status.value
                try:
                    st = TaskStatus(status_val)
                    if self._redis.srem(self._status_key(st), task_id):
                        removed_any = True
                except Exception:
                    # fallback: remove from all known status sets
                    for st in TaskStatus:
                        if self._redis.srem(self._status_key(st), task_id):
                            removed_any = True
            except Exception:
                pass

            # Remove from project index
            if task.project_id:
                try:
                    if self._redis.srem(self._project_key(task.project_id), task_id):
                        removed_any = True
                except Exception:
                    pass

            # Remove from workspace index + queues
            try:
                if self._redis.srem(self._workspace_key(task.workspace), task_id):
                    removed_any = True
            except Exception:
                pass

            try:
                # Remove from TODO queue if present
                if self._redis.lrem(self._queue_key(task.workspace), 0, task_id):
                    removed_any = True
            except Exception:
                pass

            try:
                if self._redis.srem(self._executing_key(task.workspace), task_id):
                    removed_any = True
            except Exception:
                pass
        else:
            # If task meta is missing, still try to remove from common indexes
            try:
                for st in TaskStatus:
                    if self._redis.srem(self._status_key(st), task_id):
                        removed_any = True
            except Exception:
                pass

        # Remove from global zset
        try:
            if self._redis.zrem(self._all_tasks_key(), task_id):
                removed_any = True
        except Exception:
            pass

        # Remove the task hash
        try:
            if self._redis.delete(self._task_key(task_id)):
                removed_any = True
        except Exception:
            pass

        if removed_any:
            logger.info(f"Hard deleted task {task_id}")

        return True

    # ============ Executor Support Methods ============
    
    def get_next_todo_task(self, workspace: Optional[str] = None) -> Optional[Task]:
        """Get next TODO task from queue for execution
        
        Args:
            workspace: Workspace to get task from. If None, checks all workspaces.
        
        Returns:
            Next task to execute, or None if queue is empty
        """
        if workspace is not None:
            task_id = self._redis.lpop(self._queue_key(workspace))
            if task_id:
                return self.get_task(task_id)
            return None
        
        # Check all workspace queues
        queue_keys = list(self._redis.scan_iter(f"queue:{self.exec_user}:*:todo"))
        for key in queue_keys:
            # Remove prefix to get actual key
            task_id = self._redis.lpop(key.replace(self._redis._prefix, ""))
            if task_id:
                return self.get_task(task_id)
        
        return None
    
    def start_task(self, task_id: str) -> Optional[Task]:
        """Mark task as DOING and add to executing set"""
        task = self.get_task(task_id)
        if not task:
            return None
        
        if task.status != TaskStatus.TODO.value and task.status != TaskStatus.TODO:
            logger.warning(f"Task {task_id} is not in TODO status, cannot start")
            return None
        
        # Update status
        self._update_task_status(task, TaskStatus.DOING)
        task.attempt_count += 1
        self._redis.hset(self._task_key(task.id), {"attempt_count": str(task.attempt_count)})
        
        # Add to executing set
        self._redis.sadd(self._executing_key(task.workspace), task.id)
        
        logger.info(f"Task {task_id} started (attempt {task.attempt_count})")
        return task
    
    def complete_task(self, task_id: str, error_message: Optional[str] = None) -> Optional[Task]:
        """Mark task as DONE or FAILED"""
        task = self.get_task(task_id)
        if not task:
            return None
        
        # Remove from executing set
        self._redis.srem(self._executing_key(task.workspace), task.id)
        
        if error_message:
            task.error_message = error_message
            self._redis.hset(self._task_key(task.id), {"error_message": error_message})
            self._update_task_status(task, TaskStatus.FAILED)
            logger.error(f"Task {task_id} failed: {error_message}")
        else:
            self._update_task_status(task, TaskStatus.DONE)
            logger.info(f"Task {task_id} completed successfully")
        
        return task
    
    def get_executing_count(self, workspace: Optional[str] = None) -> int:
        """Get count of currently executing tasks for a workspace"""
        return self._redis.scard(self._executing_key(workspace))
    
    def get_all_workspaces(self) -> List[str]:
        """Get all unique workspaces with tasks"""
        workspace_keys = list(self._redis.scan_iter(f"tasks:{self.exec_user}:by_workspace:*"))
        workspaces = []
        for key in workspace_keys:
            workspace_hash = key.split(":")[-1]
            workspaces.append(workspace_hash)
        return workspaces
    
    def requeue_stuck_tasks(self, timeout_seconds: int = 3600) -> int:
        """Requeue tasks that have been DOING for too long
        
        Returns count of requeued tasks
        """
        doing_task_ids = self._redis.smembers(self._status_key(TaskStatus.DOING))
        count = 0
        now = datetime.now(timezone.utc)
        
        for task_id in doing_task_ids:
            task = self.get_task(task_id)
            if task and task.started_at:
                started_at = task.started_at
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                
                elapsed = (now - started_at).total_seconds()
                if elapsed > timeout_seconds:
                    # Remove from executing set
                    self._redis.srem(self._executing_key(task.workspace), task.id)
                    
                    # Update status back to TODO
                    self._update_task_status(task, TaskStatus.TODO)
                    
                    # Re-add to queue
                    self._redis.rpush(self._queue_key(task.workspace), task.id)
                    
                    logger.warning(f"Task {task_id} requeued after {elapsed:.0f}s timeout")
                    count += 1
        
        return count

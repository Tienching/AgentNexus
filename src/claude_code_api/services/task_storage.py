# -*- coding: utf-8 -*-
"""Redis task storage for slash commands

Provides TaskQueue class for managing tasks in Redis.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid
from typing import List, Optional, Dict, Any

from ..logger import get_logger
from ..models.task_models import Task, TaskPriority, TaskStatus
from .redis_client import get_redis_client, RedisClient

logger = get_logger(__name__)


class TaskQueue:
    """Task queue manager with Redis backend
    
    Redis key structure:
    - task:{agent}:{task_id} - Task hash data
    - tasks:{agent}:all - Sorted set of all task IDs (score = created_at timestamp)
    - tasks:{agent}:by_status:{status} - Set of task IDs by status
    - tasks:{agent}:by_project:{project_id} - Set of task IDs by project
    - tasks:{agent}:by_workspace:{workspace_hash} - Set of task IDs by workspace
    - queue:{agent}:{workspace_hash}:todo - List of TODO task IDs (queue for execution)
    - executing:{agent}:{workspace_hash} - Set of currently executing task IDs
    """

    def __init__(self, db_path: str = None, agent_name: str = "default"):
        """Initialize task queue with Redis
        
        Args:
            db_path: Ignored, kept for backward compatibility
            agent_name: Agent name for task isolation
        """
        self.agent_name = agent_name
        self._redis: RedisClient = get_redis_client()
        logger.info(f"TaskQueue initialized for agent: {agent_name}")

    def _task_key(self, task_id: str) -> str:
        """Get Redis key for task data"""
        return f"task:{self.agent_name}:{task_id}"
    
    def _all_tasks_key(self) -> str:
        """Get Redis key for all tasks sorted set"""
        return f"tasks:{self.agent_name}:all"
    
    def _status_key(self, status: TaskStatus) -> str:
        """Get Redis key for tasks by status"""
        return f"tasks:{self.agent_name}:by_status:{status.value}"
    
    def _project_key(self, project_id: str) -> str:
        """Get Redis key for tasks by project"""
        return f"tasks:{self.agent_name}:by_project:{project_id}"
    
    def _workspace_key(self, workspace: str) -> str:
        """Get Redis key for tasks by workspace"""
        # Use hash of workspace path for shorter keys
        workspace_hash = str(hash(workspace or "default") % 10**8)
        return f"tasks:{self.agent_name}:by_workspace:{workspace_hash}"
    
    def _queue_key(self, workspace: str) -> str:
        """Get Redis key for workspace TODO queue"""
        workspace_hash = str(hash(workspace or "default") % 10**8)
        return f"queue:{self.agent_name}:{workspace_hash}:todo"
    
    def _executing_key(self, workspace: str) -> str:
        """Get Redis key for executing tasks set"""
        workspace_hash = str(hash(workspace or "default") % 10**8)
        return f"executing:{self.agent_name}:{workspace_hash}"

    def add_task(
        self,
        description: str,
        priority: TaskPriority = TaskPriority.THOUGHT,
        context: Optional[dict] = None,
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
        workspace: Optional[str] = None,
        task_id: Optional[str] = None,
        source_session_id: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> Task:
        """Add new task to queue
        
        Args:
            source_session_id: Optional session ID from the source context (e.g., chat session).
                              If provided, task session_id will be {source_session_id}_{task_id}.
                              Otherwise, defaults to task_{task_id}.
            agent_name: Optional agent name (CCR user) for task execution.
                       If not provided, uses self.agent_name (the queue's default agent).
        """
        # Generate task_id first if not provided
        actual_task_id = str(task_id) if task_id else str(uuid.uuid4())[:8]
        
        # Use provided agent_name or fallback to queue's default
        effective_agent = agent_name or self.agent_name
        
        # Generate session_id based on source_session_id
        logger.info(f"add_task called with source_session_id={source_session_id!r}, task_id={actual_task_id}, agent_name={effective_agent}")
        if source_session_id:
            session_id = f"{source_session_id}_{actual_task_id}"
        else:
            session_id = f"task_{actual_task_id}"
        logger.info(f"Generated session_id={session_id}")
        
        task = Task(
            id=actual_task_id,
            description=description,
            priority=priority,
            context=context,
            project_id=project_id,
            project_name=project_name,
            workspace=workspace,
            agent_name=effective_agent,
            session_id=session_id,
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
        # Priority: SERIOUS tasks go to front, others to back
        if priority == TaskPriority.SERIOUS:
            self._redis.lpush(self._queue_key(workspace), task.id)
        else:
            self._redis.rpush(self._queue_key(workspace), task.id)
        
        project_info = f" [Project: {project_name}]" if project_name else ""
        workspace_info = f" [Workspace: {workspace}]" if workspace else ""
        logger.info(f"Added task {task.id}: {description[:50]}...{project_info}{workspace_info}")
        
        return task

    def enqueue_chat_continue(self, task_id: str, message: str) -> Optional[Task]:
        """Re-enqueue an existing task as a background chat-continue run.

        This keeps the same task id and session id (`task_<id>`), but updates task.context
        with the latest user message for the next run.

        Rules:
        - If task is DOING, do not enqueue.
        - If task is CANCELLED, do not enqueue.
        - Avoid duplicating task id in the TODO queue.
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
        self._redis.hset(self._task_key(task.id), {"context": json.dumps(ctx, ensure_ascii=False)})

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
                "message": message[:50] if message else "",
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
        if new_status == TaskStatus.DOING:
            task.started_at = datetime.now(timezone.utc)
        elif new_status in (TaskStatus.DONE, TaskStatus.FAILED):
            task.completed_at = datetime.now(timezone.utc)
        elif new_status == TaskStatus.CANCELLED:
            task.deleted_at = datetime.now(timezone.utc)
        
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

    def get_queue_status(self) -> dict:
        """Get overall queue status"""
        todo = self._redis.scard(self._status_key(TaskStatus.TODO))
        doing = self._redis.scard(self._status_key(TaskStatus.DOING))
        done = self._redis.scard(self._status_key(TaskStatus.DONE))
        failed = self._redis.scard(self._status_key(TaskStatus.FAILED))
        cancelled = self._redis.scard(self._status_key(TaskStatus.CANCELLED))
        
        return {
            "total": todo + doing + done + failed + cancelled,
            "todo": todo,
            "doing": doing,
            "done": done,
            "failed": failed,
            # Backward compatibility aliases
            "pending": todo,
            "in_progress": doing,
            "completed": done,
        }

    def get_projects(self) -> List[dict]:
        """Get all projects with task counts and status"""
        # Find all project keys
        project_keys = list(self._redis.scan_iter(f"tasks:{self.agent_name}:by_project:*"))
        
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
        queue_keys = list(self._redis.scan_iter(f"queue:{self.agent_name}:*:todo"))
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
        workspace_keys = list(self._redis.scan_iter(f"tasks:{self.agent_name}:by_workspace:*"))
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

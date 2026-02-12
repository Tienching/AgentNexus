# -*- coding: utf-8 -*-
"""Slash Command Handler for agent-runtime

Handles slash commands like /task, /check, /usage, /report, /cancel, /trash, /chat.

Note:
- `/think` and `/log` are removed (no compatibility).
- Free-text arguments must appear after `--` (parsed by `slash_command_parser`).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import logging

from ...models.task_models import TaskPriority, TaskStatus
from ...stores.session_storage import get_session_storage
from ...stores.task_storage import TaskQueue
from .worktree import (
    NotGitRepoError,
    WorktreeDirConflictError,
    WorktreeCommandError,
    WorktreeError,
    ensure_task_worktree,
)
from .parser import SlashCommandParseError, parse_slash_command, usage_for

logger = logging.getLogger(__name__)


# Known slash commands
# NOTE: `/think` and `/log` are intentionally removed (no compatibility).
SLASH_COMMANDS = ["/task", "/check", "/usage", "/report", "/cancel", "/trash", "/clear", "/help", "/chat"]


def slugify_project(name: str) -> str:
    """Convert project name to slug format"""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


class SlashCommandHandler:
    """Handles slash commands and returns markdown responses"""

    def __init__(self, exec_user: str, config=None):
        """Initialize handler

        Args:
            exec_user: Linux exec user name for task isolation
            config: Optional config override
        """
        self.exec_user = exec_user
        if config is None:
            raise ValueError("SlashCommandHandler requires a config object")
        self.config = config

        # Initialize task queue with exec_user-specific database
        db_path = Path(self.config.user_home_base) / exec_user / "data" / "tasks.db"
        self._task_queue: Optional[TaskQueue] = None
        self._db_path = str(db_path)

        # Trash directory
        self._trash_dir = Path(self.config.user_home_base) / exec_user / "trash"

    @property
    def task_queue(self) -> TaskQueue:
        """Lazy initialization of task queue"""
        if self._task_queue is None:
            self._task_queue = TaskQueue(self._db_path, self.exec_user)
        return self._task_queue

    def is_slash_command(self, content: str) -> bool:
        """Check if content starts with a known slash command"""
        content_lower = content.lower().strip()
        for cmd in SLASH_COMMANDS:
            if content_lower == cmd or content_lower.startswith(cmd + " "):
                return True
        return False

    def get_command_and_args(self, content: str) -> Tuple[str, str]:
        """Parse command and arguments from content"""
        content = content.strip()
        parts = content.split(None, 1)
        command = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        return command, args

    def handle_command(self, content: str, source_session_id: Optional[str] = None) -> str:
        """Handle a slash command and return markdown response.

        Grammar (strict):
            /<cmd> <subcmd> [options...] [-- <free-text...>]

        Args:
            content: The slash command content
            source_session_id: Session ID from the source context (for task creation)

        Notes:
            - Free text MUST appear after `--`.
            - All options must provide both short and long forms.
            - `/think` and `/log` are removed (no compatibility).
        """
        content = (content or "").strip()
        if not content:
            return "## ❌ Error\n\nEmpty command."

        # Removed commands (explicit error; no compatibility)
        lowered = content.lower().strip()
        if lowered == "/think" or lowered.startswith("/think "):
            return "## ❌ 命令已移除\n\n`/think` 命令已移除。"
        if lowered == "/log" or lowered.startswith("/log "):
            return "## ❌ 命令已移除\n\n`/log` 命令已移除。"

        try:
            parsed = parse_slash_command(content)
        except SlashCommandParseError as e:
            usage = (e.usage or "").strip()
            if usage:
                return f"## ❌ 命令解析失败\n\n{e.message}\n\n**Usage:** `{usage}`"
            return f"## ❌ 命令解析失败\n\n{e.message}"
        except Exception as e:
            logger.error(f"Error parsing slash command: {e}", exc_info=True)
            return f"## ❌ Error\n\nFailed to parse command: {str(e)}"

        try:
            if parsed.cmd == "task" and parsed.subcmd == "create":
                return self._handle_task_create(
                    description=parsed.free_text,
                    project_name=parsed.options.get("project"),
                    workspace=parsed.options.get("workspace"),
                    inplace=bool(parsed.options.get("inplace", False)),
                    provider=parsed.options.get("provider"),
                    source_session_id=source_session_id,
                    exec_user=parsed.options.get("exec-user"),
                )

            if parsed.cmd == "chat" and parsed.subcmd == "history":
                return self._handle_chat_history(
                    task_id=parsed.options["task"],
                    tail=int(parsed.options.get("tail", 10)),
                )
            if parsed.cmd == "chat" and parsed.subcmd == "continue":
                return self._handle_chat_continue(
                    task_id=parsed.options["task"],
                    message=parsed.free_text,
                )

            if parsed.cmd == "check" and parsed.subcmd == "status":
                return self._handle_check()

            if parsed.cmd == "usage" and parsed.subcmd == "show":
                return self._handle_usage()

            if parsed.cmd == "report" and parsed.subcmd == "daily":
                return self._handle_report("")
            if parsed.cmd == "report" and parsed.subcmd == "list":
                return self._handle_report("--list")
            if parsed.cmd == "report" and parsed.subcmd == "task":
                return self._handle_report(parsed.options["task"])
            if parsed.cmd == "report" and parsed.subcmd == "project":
                return self._handle_report(parsed.options["project"])

            if parsed.cmd == "cancel" and parsed.subcmd == "task":
                return self._handle_cancel(parsed.options["task"])
            if parsed.cmd == "cancel" and parsed.subcmd == "project":
                return self._handle_cancel(parsed.options["project"])

            if parsed.cmd == "trash" and parsed.subcmd == "list":
                return self._handle_trash("list")
            if parsed.cmd == "trash" and parsed.subcmd == "restore":
                return self._handle_trash(f"restore {parsed.options['project']}")
            if parsed.cmd == "trash" and parsed.subcmd == "empty":
                return self._handle_trash("empty")

            if parsed.cmd == "clear" and parsed.subcmd == "now":
                return self._handle_clear()

            if parsed.cmd == "help" and parsed.subcmd == "show":
                return self._handle_help()

            return f"## ❌ Unknown Command\n\nUnknown command: `/{parsed.cmd} {parsed.subcmd}`\n\n输入 `/help show` 查看所有可用命令。"

        except Exception as e:
            logger.error(f"Error handling parsed command /{parsed.cmd} {parsed.subcmd}: {e}", exc_info=True)
            return f"## ❌ Error\n\nFailed to execute command: {str(e)}"

    def _handle_task_create(
        self,
        description: str,
        project_name: Optional[str] = None,
        workspace: Optional[str] = None,
        inplace: bool = False,
        provider: Optional[str] = None,
        source_session_id: Optional[str] = None,
        exec_user: Optional[str] = None,
    ) -> str:
        """Handle `/task create` (strict syntax; free text must be after `--`).

        Args:
            source_session_id: Session ID from the source context.
                              Task session_id will be {source_session_id}_{task_id}.
            exec_user: Optional Linux exec user for task execution.
                       If not provided, uses the default exec_user from task queue.
        """
        if not (description or "").strip():
            return (
                "## ❌ Missing Description\n\n"
                f"**Usage:** `{usage_for('task', 'create')}`"
            )

        # Determine priority
        priority = TaskPriority.SERIOUS if project_name else TaskPriority.THOUGHT
        project_id = slugify_project(project_name) if project_name else None

        requested_workspace = (workspace or "").strip() or None
        use_inplace = bool(inplace) and bool(requested_workspace)

        # Generate task id early so worktree path/branch are deterministic
        task_id = str(uuid.uuid4())[:8]

        context = {}
        exec_workspace: Optional[str] = None
        
        # 为初始用户消息生成唯一 ID
        context["next_user_message_id"] = f"task-init-{task_id}"

        if requested_workspace:
            context["requested_workspace"] = requested_workspace
            if use_inplace:
                context["cwd_mode"] = "inplace"
                exec_workspace = requested_workspace
            else:
                context["cwd_mode"] = "worktree"
                try:
                    wt = ensure_task_worktree(Path(requested_workspace), task_id=task_id)
                    exec_workspace = str(wt.worktree_dir)
                    context["worktree"] = {
                        "repo_root": str(wt.repo_root),
                        "branch": wt.branch,
                        "dir": str(wt.worktree_dir),
                        "reused": bool(wt.reused),
                    }
                except NotGitRepoError as e:
                    return (
                        "## ❌ Workspace 不是 Git 仓库\n\n"
                        f"{str(e)}\n\n"
                        "提示：如果想直接在原目录开发，请加 `-i`。"
                    )
                except WorktreeDirConflictError as e:
                    return (
                        "## ❌ Worktree 目录冲突\n\n"
                        f"{str(e)}\n\n"
                        "提示：请清理该目录，或确认它已被 `git worktree list` 注册后再重试。"
                    )
                except (WorktreeCommandError, WorktreeError) as e:
                    return (
                        "## ❌ 创建 worktree 失败\n\n"
                        f"{str(e)}"
                    )
        else:
            # No -w provided: --inplace is ignored by design.
            if inplace:
                context["inplace_ignored"] = True

        default_provider = (getattr(self.config, "default_provider", None) or "").strip()
        default_alias = (getattr(self.config, "default_alias", None) or "").strip()
        effective_provider = (provider or "").strip().lower() or default_provider or "codebuddy"
        effective_alias = default_alias or effective_provider
        default_exec_user = (getattr(self.config, "default_exec_user", None) or "").strip()
        effective_exec_user = (exec_user or "").strip() or default_exec_user or None

        # Create task (workspace for execution)
        logger.info(f"_handle_task_create: source_session_id={source_session_id!r}, exec_user={effective_exec_user!r}")
        task = self.task_queue.add_task(
            description=description.strip(),
            priority=priority,
            context=context or None,
            project_id=project_id,
            project_name=project_name,
            workspace=exec_workspace,
            provider=effective_provider,
            alias=effective_alias,
            task_id=task_id,
            source_session_id=source_session_id,
            exec_user=effective_exec_user,
        )

        priority_emoji = "🔴" if priority == TaskPriority.SERIOUS else "💭"
        priority_label = "Serious" if priority == TaskPriority.SERIOUS else "Thought"

        response = f"## {priority_emoji} {priority_label} Task Created\n\n"
        response += "| Field | Value |\n"
        response += "|-------|-------|\n"
        response += f"| Task ID | #{task.id} |\n"
        response += f"| Priority | {priority_label} |\n"
        if effective_provider:
            response += f"| Provider | {effective_provider} |\n"
        if effective_exec_user:
            response += f"| Exec User | {effective_exec_user} |\n"
        if project_name:
            response += f"| Project | {project_name} |\n"
        if requested_workspace:
            response += f"| Workspace | `{requested_workspace}` |\n"
        if exec_workspace:
            response += f"| Exec CWD | `{exec_workspace}` |\n"
        response += f"\n**Description:** {description.strip()}"

        return response

    def _handle_chat_continue(self, task_id: str, message: str) -> str:
        """Handle `/chat continue` - enqueue a background run for an existing task."""
        task_id = (task_id or "").strip()
        msg = (message or "").strip()
        if not task_id:
            return (
                "## ❌ Missing Task ID\n\n"
                f"**Usage:** `{usage_for('chat', 'continue')}`"
            )
        if not msg:
            return (
                "## ❌ Missing Message\n\n"
                f"**Usage:** `{usage_for('chat', 'continue')}`"
            )

        task = self.task_queue.get_task(task_id)
        if not task:
            return f"## ❌ Not Found\n\n任务 `{task_id}` 不存在。"

        status_val = task.status if isinstance(task.status, str) else task.status.value
        if status_val == TaskStatus.DOING.value:
            return (
                f"## ⏳ 已在执行中\n\n"
                f"任务 `#{task.id}` 正在执行中，请稍后再试。\n\n"
                f"你可以用 `/chat -t {task.id}` 查看当前进度。"
            )

        try:
            self.task_queue.enqueue_chat_continue(task_id, msg)
        except Exception as e:
            return f"## ❌ 入队失败\n\n{str(e)}"

        return (
            f"## ✅ 已入队\n\n"
            f"已将续聊消息加入后台队列：任务 `#{task.id}`。\n\n"
            f"- 查看结果：`/chat -t {task.id}`\n"
            f"- 实时回放（Nexus）：`/api/nexus/tasks/{task.id}/agui/stream`\n"
        )

    def _handle_chat_history(self, task_id: str, tail: int = 10) -> str:
        """Handle `/chat history` - show task execution log/conversation."""
        task_id = (task_id or "").strip()
        if not task_id:
            return (
                "## ❌ Missing Task ID\n\n"
                f"**Usage:** `{usage_for('chat', 'history')}`"
            )

        # sanitize tail
        try:
            tail_n = int(tail)
        except Exception:
            tail_n = 10
        if tail_n <= 0:
            tail_n = 10
        if tail_n > 100:
            tail_n = 100

        task = self.task_queue.get_task(task_id)
        if not task:
            return f"## ❌ Not Found\n\n任务 `{task_id}` 不存在。"

        status_val = task.status if isinstance(task.status, str) else task.status.value
        status_icons = {
            "done": "✅",
            "doing": "🔄",
            "todo": "🕒",
            "failed": "❌",
            "cancelled": "🗑️",
        }
        status_icon = status_icons.get(status_val, "•")

        response = f"## 💬 对话记录 - #{task.id}\n\n"
        response += f"**状态:** {status_icon} {status_val}\n"
        response += f"**描述:** {task.description}\n"
        if task.project_name:
            response += f"**项目:** {task.project_name}\n"
        if task.workspace:
            response += f"**工作目录:** `{task.workspace}`\n"
        response += f"**创建时间:** {task.created_at.strftime('%Y-%m-%d %H:%M:%S') if task.created_at else 'N/A'}\n"

        # Prefer Redis archived session messages
        session_id = task.session_id or f"task_{task.id}"  # Use stored session_id, fallback for legacy tasks
        try:
            storage = get_session_storage()
            meta = storage.get_session_meta(session_id)

            if meta:
                # meta.updated_at is in ms
                try:
                    updated_dt = datetime.fromtimestamp(meta.updated_at / 1000, tz=timezone.utc)
                    updated_str = updated_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                except Exception:
                    updated_str = str(getattr(meta, "updated_at", ""))
                response += f"**会话状态:** {getattr(meta, 'status', '')}\n"
                response += f"**会话更新时间:** {updated_str}\n"
            else:
                response += "**会话状态:** (暂无归档会话；可能尚未开始执行)\n"

            stored_messages = storage.get_session_messages(session_id) if meta else []
            
            # 获取工具调用信息
            try:
                tool_calls = storage.get_session_tool_calls(session_id) if meta else []
            except Exception:
                tool_calls = []
            tool_calls_map = {tc.id: tc for tc in tool_calls}

            if stored_messages:
                response += f"\n### 最近 {tail_n} 条\n\n"
                tail_messages = stored_messages[-tail_n:] if len(stored_messages) > tail_n else stored_messages
                for m in tail_messages:
                    role = (getattr(m, "role", None) or "assistant").lower()
                    content = getattr(m, "content", "") or ""
                    
                    # 构建消息内容，包含工具调用信息
                    msg_parts = []
                    
                    # 如果有 content_segments，按顺序展示
                    content_segments = getattr(m, "content_segments", None)
                    if content_segments:
                        sorted_segments = sorted(content_segments, key=lambda s: getattr(s, "sequence", 0))
                        for seg in sorted_segments:
                            seg_type = getattr(seg, "type", "")
                            if seg_type == "text":
                                seg_content = getattr(seg, "content", "")
                                if seg_content:
                                    msg_parts.append(seg_content)
                            elif seg_type == "tool_call":
                                tc_id = getattr(seg, "tool_call_id", "")
                                if tc_id and tc_id in tool_calls_map:
                                    tc = tool_calls_map[tc_id]
                                    tool_name = getattr(tc, "tool_name", "unknown")
                                    msg_parts.append(f"🔧 *[调用工具: {tool_name}]*")
                    else:
                        # 旧格式：只有 content
                        if content:
                            msg_parts.append(content)
                        
                        # 检查 tool_call_ids
                        tool_call_ids = getattr(m, "tool_call_ids", None)
                        if tool_call_ids:
                            for tc_id in tool_call_ids:
                                if tc_id in tool_calls_map:
                                    tc = tool_calls_map[tc_id]
                                    tool_name = getattr(tc, "tool_name", "unknown")
                                    msg_parts.append(f"🔧 *[调用工具: {tool_name}]*")
                    
                    final_content = "\n".join(msg_parts) if msg_parts else "(无内容)"

                    if role == "user":
                        response += f"**👤 用户:**\n{final_content}\n\n"
                    elif role == "assistant":
                        response += f"**🤖 助手:**\n{final_content}\n\n"
                    elif role == "system":
                        response += f"**⚙️ 系统:**\n{final_content}\n\n"
                    else:
                        response += f"**🔧 {role}:**\n{final_content}\n\n"

                return response
        except Exception as e:
            logger.debug(f"Could not read archived session messages: {e}")

        # Fallback to conversation.json (legacy path)
        log_path = Path(self.config.user_home_base) / self.exec_user / "sessions" / f"task_{task.id}" / ".claude" / "conversation.json"

        if log_path.exists():
            try:
                import json

                with open(log_path, 'r', encoding='utf-8') as f:
                    conversation = json.load(f)

                response += f"\n### 最近 {tail_n} 条\n\n"

                messages = conversation if isinstance(conversation, list) else conversation.get('messages', [])

                for msg in messages[-tail_n:]:
                    role = msg.get('role', 'unknown')
                    content = msg.get('content', '')

                    if isinstance(content, list):
                        text_parts = []
                        for item in content:
                            if isinstance(item, dict):
                                if item.get('type') == 'text':
                                    text_parts.append(item.get('text', ''))
                                elif item.get('type') == 'tool_use':
                                    text_parts.append(f"[调用工具: {item.get('name', 'unknown')}]")
                            elif isinstance(item, str):
                                text_parts.append(item)
                        content = '\n'.join(text_parts)

                    if len(content) > 500:
                        content = content[:500] + "..."

                    if role == 'user':
                        response += f"**👤 用户:**\n{content}\n\n"
                    elif role == 'assistant':
                        response += f"**🤖 助手:**\n{content}\n\n"

                return response
            except Exception as e:
                logger.debug(f"Could not read conversation log: {e}")

        response += "\n### 💬 对话记录\n\n暂无对话记录或无法读取。\n"
        return response

    # -----------------
    # Legacy handlers (kept for internal reuse)
    # -----------------

    def _handle_task(self, args: str, invoked_command: str = "/task") -> str:
        """Legacy `/task` handler (deprecated).

        The backend now requires strict syntax:
            `/task create [options...] -- <description...>`

        This legacy handler is kept for compatibility with internal calls only.
        """
        return "## ❌ 旧写法已移除\n\n请使用严格语法：`/task create [-p|--project <项目>] [-w|--workspace <路径>] -- <描述...>`。"

        # Parse -p flag for project
        project_name = None
        workspace = None
        description = args

        # Check for -p or --project flag
        project_match = re.search(r'\s+-p\s+(\S+)', args)
        if not project_match:
            project_match = re.search(r'\s+--project[=\s]+(\S+)', args)

        if project_match:
            project_name = project_match.group(1)
            description = args[:project_match.start()] + args[project_match.end():]
            description = description.strip()

        # Check for -w or --workspace flag
        workspace_match = re.search(r'\s+-w\s+(\S+)', description)
        if not workspace_match:
            workspace_match = re.search(r'\s+--workspace[=\s]+(\S+)', description)

        if workspace_match:
            workspace = workspace_match.group(1)
            description = description[:workspace_match.start()] + description[workspace_match.end():]
            description = description.strip()

        if not description:
            return "## ❌ Missing Description\n\nPlease provide a task description."

        # Determine priority
        priority = TaskPriority.SERIOUS if project_name else TaskPriority.THOUGHT
        project_id = slugify_project(project_name) if project_name else None

        # Create task
        task = self.task_queue.add_task(
            description=description,
            priority=priority,
            project_id=project_id,
            project_name=project_name,
            workspace=workspace,
        )

        # Build response
        priority_emoji = "🔴" if priority == TaskPriority.SERIOUS else "💭"
        priority_label = "Serious" if priority == TaskPriority.SERIOUS else "Thought"

        response = f"## {priority_emoji} {priority_label} Task Created\n\n"
        response += "| Field | Value |\n"
        response += "|-------|-------|\n"
        response += f"| Task ID | #{task.id} |\n"
        response += f"| Priority | {priority_label} |\n"
        if project_name:
            response += f"| Project | {project_name} |\n"
        if workspace:
            response += f"| Workspace | `{workspace}` |\n"
        response += f"\n**Description:** {description}"

        return response

    def _handle_check(self) -> str:
        """Handle /check command - show system health and queue status"""
        queue_status = self.task_queue.get_queue_status()
        recent_tasks = self.task_queue.get_recent_tasks(limit=5)
        projects = self.task_queue.get_projects()

        # Determine health status
        failed_count = queue_status.get("failed", 0)
        if failed_count > 5:
            health_emoji = "🔴"
            health_status = "Unhealthy"
        elif failed_count > 0:
            health_emoji = "🟡"
            health_status = "Degraded"
        else:
            health_emoji = "🟢"
            health_status = "Healthy"

        response = f"## {health_emoji} System Status: {health_status}\n\n"
        
        # Queue summary - use new status names
        response += "### Queue Summary\n\n"
        response += "| Status | Count |\n"
        response += "|--------|-------|\n"
        response += f"| To Do | {queue_status.get('todo', queue_status.get('pending', 0))} |\n"
        response += f"| Doing | {queue_status.get('doing', queue_status.get('in_progress', 0))} |\n"
        response += f"| Done | {queue_status.get('done', queue_status.get('completed', 0))} |\n"
        response += f"| Failed | {queue_status.get('failed', 0)} |\n"
        response += f"| **Total** | **{queue_status.get('total', 0)}** |\n"

        # Projects
        if projects:
            response += "\n### Projects\n\n"
            response += "| Project | To Do | Doing | Done |\n"
            response += "|---------|-------|-------|------|\n"
            for proj in projects[:5]:
                todo = proj.get('todo', proj.get('pending', 0))
                doing = proj.get('doing', proj.get('in_progress', 0))
                done = proj.get('done', proj.get('completed', 0))
                response += f"| {proj['project_name']} | {todo} | {doing} | {done} |\n"

        # Recent tasks
        if recent_tasks:
            response += "\n### Recent Tasks\n\n"
            response += "| ID | Status | Priority | Description |\n"
            response += "|----|--------|----------|-------------|\n"
            status_icons = {
                TaskStatus.DONE: "✅",
                TaskStatus.DOING: "🔄",
                TaskStatus.TODO: "🕒",
                TaskStatus.FAILED: "❌",
                TaskStatus.CANCELLED: "🗑️",
                # Legacy support
                "done": "✅",
                "doing": "🔄",
                "todo": "🕒",
                "failed": "❌",
                "cancelled": "🗑️",
            }
            for task in recent_tasks:
                status_val = task.status if isinstance(task.status, str) else task.status.value
                icon = status_icons.get(task.status, status_icons.get(status_val, "•"))
                priority_val = task.priority if isinstance(task.priority, str) else task.priority.value
                desc = task.description[:40] + "..." if len(task.description) > 40 else task.description
                response += f"| #{task.id} | {icon} {status_val} | {priority_val} | {desc} |\n"

        return response

    def _handle_usage(self) -> str:
        """Handle /usage command - show Claude Code Pro plan usage"""
        # Try to get usage from ccr command
        try:
            result = subprocess.run(
                ["ccr", "usage"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                # Parse usage output
                output = result.stdout.strip()
                
                # Try to extract percentage
                percent_match = re.search(r'(\d+(?:\.\d+)?)\s*%', output)
                if percent_match:
                    usage_percent = float(percent_match.group(1))
                    
                    # Determine status
                    if usage_percent >= 90:
                        status_emoji = "🔴"
                        status_text = "At Limit"
                    elif usage_percent >= 70:
                        status_emoji = "🟡"
                        status_text = "Near Limit"
                    elif usage_percent >= 50:
                        status_emoji = "🟠"
                        status_text = "Moderate"
                    else:
                        status_emoji = "🟢"
                        status_text = "Healthy"

                    # Build usage bar
                    bar_length = 20
                    filled = int(usage_percent / 100 * bar_length)
                    empty = bar_length - filled
                    usage_bar = "█" * filled + "░" * empty

                    response = f"## {status_emoji} Claude Code Usage\n\n"
                    response += f"**Usage:** `{usage_percent:.1f}%` {usage_bar}\n\n"
                    response += f"**Status:** {status_text}\n"
                    
                    return response
                else:
                    # Return raw output if can't parse
                    return f"## 📊 Usage Info\n\n```\n{output}\n```"
        except subprocess.TimeoutExpired:
            pass
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.debug(f"Could not get usage info: {e}")

        return (
            "## ℹ️ Usage Information\n\n"
            "Usage information is not available.\n\n"
            "This feature requires the `ccr usage` command to be available."
        )

    def _handle_report(self, args: str) -> str:
        """Handle /report command - show task details or reports
        
        Usage:
            /report              - Today's summary
            /report <task_id>    - Task details
            /report <project>    - Project report
            /report --list       - List all reports
        """
        args = args.strip()

        # --list flag
        if args == "--list":
            projects = self.task_queue.get_projects()
            
            response = "## 📊 Available Reports\n\n"
            
            if projects:
                response += "### Projects\n\n"
                for proj in projects:
                    response += f"- `{proj['project_id']}` ({proj['total_tasks']} tasks)\n"
            else:
                response += "No projects found.\n"
            
            response += "\n**Usage:**\n"
            response += "- `/report` - Today's summary\n"
            response += "- `/report <task_id>` - Task details\n"
            response += "- `/report <project>` - Project report\n"
            
            return response

        # No args - today's summary
        if not args:
            queue_status = self.task_queue.get_queue_status()
            recent_tasks = self.task_queue.get_recent_tasks(limit=10)
            
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            response = f"## 📅 Daily Report - {today}\n\n"
            
            response += "### Summary\n\n"
            response += f"- **Total Tasks:** {queue_status.get('total', 0)}\n"
            response += f"- **To Do:** {queue_status.get('todo', queue_status.get('pending', 0))}\n"
            response += f"- **Done:** {queue_status.get('done', queue_status.get('completed', 0))}\n"
            response += f"- **Failed:** {queue_status.get('failed', 0)}\n"
            
            if recent_tasks:
                response += "\n### Recent Activity\n\n"
                for task in recent_tasks[:5]:
                    created = task.created_at.strftime("%H:%M") if task.created_at else "N/A"
                    status_val = task.status if isinstance(task.status, str) else task.status.value
                    response += f"- `#{task.id}` [{status_val}] {task.description[:50]}... ({created})\n"
            
            return response

        # Try to parse as task ID
        task = self.task_queue.get_task(args)
        
        if task:
            status_val = task.status if isinstance(task.status, str) else task.status.value
            priority_val = task.priority if isinstance(task.priority, str) else task.priority.value
            
            response = f"## 📋 Task #{task.id}\n\n"
            response += "| Field | Value |\n"
            response += "|-------|-------|\n"
            response += f"| Status | {status_val} |\n"
            response += f"| Priority | {priority_val} |\n"
            if task.project_name:
                response += f"| Project | {task.project_name} |\n"
            if task.workspace:
                response += f"| Workspace | `{task.workspace}` |\n"
            response += f"| Created | {task.created_at.isoformat() if task.created_at else 'N/A'} |\n"
            if task.started_at:
                response += f"| Started | {task.started_at.isoformat()} |\n"
            if task.completed_at:
                response += f"| Completed | {task.completed_at.isoformat()} |\n"
            if task.error_message:
                response += f"| Error | {task.error_message[:100]} |\n"
            
            response += f"\n**Description:**\n{task.description}"
            
            return response

        # Treat as project ID
        project_id = slugify_project(args)
        project = self.task_queue.get_project_by_id(project_id)
        
        if not project:
            return f"## ❌ Not Found\n\nTask or project `{args}` not found."
        
        response = f"## 📦 Project Report: {project['project_name']}\n\n"
        response += "### Summary\n\n"
        response += f"- **Total Tasks:** {project['total_tasks']}\n"
        response += f"- **To Do:** {project.get('todo', project.get('pending', 0))}\n"
        response += f"- **Doing:** {project.get('doing', project.get('in_progress', 0))}\n"
        response += f"- **Done:** {project.get('done', project.get('completed', 0))}\n"
        response += f"- **Failed:** {project['failed']}\n"
        
        if project.get('tasks'):
            response += "\n### Recent Tasks\n\n"
            for t in project['tasks']:
                response += f"- `#{t['id']}` [{t['status']}] {t['description']}\n"
        
        return response

    def _handle_cancel(self, args: str) -> str:
        """Handle /cancel command - cancel task or project
        
        Usage:
            /cancel <task_id>  - Cancel a task
            /cancel <project>  - Cancel all tasks in project
        """
        if not args.strip():
            return (
                "## ❌ Missing Identifier\n\n"
                "**Usage:**\n"
                "- `/cancel <task_id>` - Cancel a task\n"
                "- `/cancel <project>` - Cancel all tasks in project"
            )

        args = args.strip()

        # Try to cancel as task ID first
        task = self.task_queue.cancel_task(args)
        
        if task:
            status_val = task.status if isinstance(task.status, str) else task.status.value
            if status_val == TaskStatus.CANCELLED.value or task.status == TaskStatus.CANCELLED:
                return (
                    f"## ✅ Task Cancelled\n\n"
                    f"Task **#{task.id}** has been moved to trash.\n\n"
                    f"**Description:** {task.description[:100]}"
                )
            else:
                return f"## ❌ Cannot Cancel\n\nTask #{args} is not in To Do status."

        # Treat as project ID
        project_id = slugify_project(args)
        project = self.task_queue.get_project_by_id(project_id)
        
        if not project:
            return f"## ❌ Not Found\n\nTask or project `{args}` not found."

        # Soft delete tasks
        count = self.task_queue.delete_project(project_id)
        
        # Move workspace to trash
        workspace_path = Path(self.config.user_home_base) / self.exec_user / "projects" / project_id
        workspace_status = ""
        
        if workspace_path.exists():
            self._trash_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            trash_path = self._trash_dir / f"project_{project_id}_{timestamp}"
            try:
                workspace_path.rename(trash_path)
                workspace_status = "Workspace moved to trash."
            except Exception as e:
                workspace_status = f"Could not move workspace: {e}"
        else:
            workspace_status = "No workspace to move."

        return (
            f"## 🗑️ Project Cancelled\n\n"
            f"**Project:** {project['project_name']}\n"
            f"**Tasks Moved:** {count}\n\n"
            f"✅ {workspace_status}"
        )

    def _handle_trash(self, args: str) -> str:
        """Handle /trash command - manage trash
        
        Usage:
            /trash list              - Show trash contents
            /trash restore <project> - Restore project from trash
            /trash empty             - Permanently delete trash
        """
        args = args.strip()
        parts = args.split(None, 1)
        subcommand = parts[0].lower() if parts else "list"
        remaining = parts[1] if len(parts) > 1 else ""

        if subcommand == "list" or not subcommand:
            if not self._trash_dir.exists():
                return "## 🗑️ Trash\n\nTrash is empty."
            
            items = list(self._trash_dir.iterdir())
            if not items:
                return "## 🗑️ Trash\n\nTrash is empty."
            
            response = "## 🗑️ Trash Contents\n\n"
            for item in sorted(items):
                if item.is_dir():
                    try:
                        size_mb = sum(f.stat().st_size for f in item.rglob("*") if f.is_file()) / (1024 * 1024)
                        response += f"- 📁 `{item.name}` ({size_mb:.1f} MB)\n"
                    except Exception:
                        response += f"- 📁 `{item.name}`\n"
            
            response += "\n**Commands:**\n"
            response += "- `/trash restore <project>` - Restore project\n"
            response += "- `/trash empty` - Permanently delete all\n"
            
            return response

        elif subcommand == "restore":
            if not remaining:
                return "## ❌ Missing Project\n\n**Usage:** `/trash restore <project_id>`"
            
            if not self._trash_dir.exists():
                return "## 🗑️ Trash Empty\n\nTrash is empty."
            
            # Find matching item
            search_term = remaining.lower().replace(" ", "-")
            matching = [item for item in self._trash_dir.iterdir() if search_term in item.name.lower()]
            
            if not matching:
                return f"## ❌ Not Found\n\nProject `{remaining}` not found in trash."
            
            if len(matching) > 1:
                response = f"## ⚠️ Multiple Matches\n\nMultiple matches for `{remaining}`:\n\n"
                for item in matching:
                    response += f"- `{item.name}`\n"
                return response
            
            trash_item = matching[0]
            
            # Extract project_id from name (e.g., "project_myapp_20231015_120000")
            parts = trash_item.name.split("_")
            if parts[0] != "project" or len(parts) < 4:
                return f"## ❌ Invalid Format\n\nInvalid trash item: `{trash_item.name}`"
            
            project_id = "_".join(parts[1:-2])
            
            # Restore workspace
            workspace_path = Path(self.config.user_home_base) / self.exec_user / "projects" / project_id
            if workspace_path.exists():
                return f"## ⚠️ Workspace Exists\n\nWorkspace already exists at `{workspace_path}`"
            
            workspace_path.parent.mkdir(parents=True, exist_ok=True)
            trash_item.rename(workspace_path)
            
            return (
                f"## ✅ Project Restored\n\n"
                f"Project `{project_id}` restored from trash.\n\n"
                f"⚠️ Note: Tasks remain in CANCELLED status. Update them manually if needed."
            )

        elif subcommand == "empty":
            if not self._trash_dir.exists() or not list(self._trash_dir.iterdir()):
                return "## 🗑️ Trash\n\nTrash is already empty."
            
            count = 0
            for item in self._trash_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                    count += 1
            
            return f"## ✅ Trash Emptied\n\nDeleted **{count}** item(s) from trash."

        else:
            return (
                "## ❓ Unknown Subcommand\n\n"
                "**Usage:**\n"
                "- `/trash list` - Show contents\n"
                "- `/trash restore <project>` - Restore project\n"
                "- `/trash empty` - Delete all"
            )

    def _handle_clear(self) -> str:
        """Handle /clear command - return message indicating session will be cleared"""
        return (
            "## 🔄 Session Cleared\n\n"
            "Your session has been cleared. A fresh workspace has been created."
        )

    def _handle_help(self) -> str:
        """Handle /help command - show all available commands"""
        return """## 📚 帮助 - 可用命令

### 语法规则

- `/<cmd> [options...] [-- <text>]`
- 根据参数自动推断操作类型

---

### 任务管理

**`/task`** - 创建任务
```
/task [-p <项目>] [-w <路径> [-i]] [-r <provider>] [-u <exec_user>] [-l <alias>] -- <描述>
```
- 可选 `-r/--provider` 指定执行 Provider（未指定则使用默认配置）
- 可选 `-u/--exec-user` 指定执行用户（未指定则使用默认配置）
- 可选 `-l/--alias` 指定别名（未指定则默认等于 Provider）

**`/chat`** - 对话管理
```
/chat -t <任务ID>              # 查看记录
/chat -t <ID> -n <N>           # 最近N条
/chat -c -t <ID> -- <msg>      # 续聊
```

**`/check`** - 系统状态

**`/report`** - 报告
```
/report              # 今日摘要
/report -t <任务ID>  # 任务详情
/report -p <项目>    # 项目报告
/report -l           # 列出项目
```

**`/cancel`** - 取消
```
/cancel -t <任务ID>  # 取消任务
/cancel -p <项目>    # 取消项目
```

---

### 系统管理

**`/usage`** - 查看使用量

**`/trash`** - 回收站
```
/trash              # 查看列表
/trash -p <项目>    # 恢复项目
/trash -e           # 清空
```

**`/clear`** - 清除会话

**`/help`** - 显示帮助

---

### 任务状态

🕒 To Do · 🔄 Doing · ✅ Done · ❌ Failed · 🗑️ Cancelled
"""

    def _handle_log(self, args: str) -> str:
        """Deprecated: `/log` is removed (no compatibility)."""
        return "## ❌ 命令已移除\n\n`/log` 已移除，请使用 `/chat history -t|--task <任务ID> [-n|--tail <N>]`。"

        task_id = args.strip()
        task = self.task_queue.get_task(task_id)
        
        if not task:
            return f"## ❌ Not Found\n\n任务 `{task_id}` 不存在。"
        
        # 构建任务信息
        status_val = task.status if isinstance(task.status, str) else task.status.value
        status_icons = {
            "done": "✅",
            "doing": "🔄",
            "todo": "🕒",
            "failed": "❌",
            "cancelled": "🗑️",
        }
        status_icon = status_icons.get(status_val, "•")
        
        response = f"## 📋 任务日志 - #{task.id}\n\n"
        response += f"**状态:** {status_icon} {status_val}\n"
        response += f"**描述:** {task.description}\n"
        
        if task.project_name:
            response += f"**项目:** {task.project_name}\n"
        if task.workspace:
            response += f"**工作目录:** `{task.workspace}`\n"
        
        response += f"**创建时间:** {task.created_at.strftime('%Y-%m-%d %H:%M:%S') if task.created_at else 'N/A'}\n"
        
        if task.started_at:
            response += f"**开始时间:** {task.started_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        if task.completed_at:
            response += f"**完成时间:** {task.completed_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
            if task.started_at:
                duration = (task.completed_at - task.started_at).total_seconds()
                if duration < 60:
                    response += f"**执行耗时:** {duration:.1f} 秒\n"
                else:
                    response += f"**执行耗时:** {duration/60:.1f} 分钟\n"
        
        if task.attempt_count > 1:
            response += f"**重试次数:** {task.attempt_count}\n"
        
        if task.error_message:
            response += f"\n### ❌ 错误信息\n\n```\n{task.error_message}\n```\n"

        # 优先从 Redis 会话归档读取（与 /nexus/tasks/{id}/agui/messages 对齐）
        session_id = task.session_id or f"task_{task.id}"  # Use stored session_id, fallback for legacy tasks
        try:
            storage = get_session_storage()
            meta = storage.get_session_meta(session_id)
            stored_messages = storage.get_session_messages(session_id) if meta else []
            
            # 获取工具调用信息
            try:
                tool_calls = storage.get_session_tool_calls(session_id) if meta else []
            except Exception:
                tool_calls = []
            tool_calls_map = {tc.id: tc for tc in tool_calls}

            if stored_messages:
                response += "\n### 💬 对话记录\n\n"
                tail_messages = stored_messages[-10:] if len(stored_messages) > 10 else stored_messages
                for m in tail_messages:
                    role = (getattr(m, "role", None) or "assistant").lower()
                    content = getattr(m, "content", "") or ""
                    
                    # 构建消息内容，包含工具调用信息
                    msg_parts = []
                    
                    # 如果有 content_segments，按顺序展示
                    content_segments = getattr(m, "content_segments", None)
                    if content_segments:
                        sorted_segments = sorted(content_segments, key=lambda s: getattr(s, "sequence", 0))
                        for seg in sorted_segments:
                            seg_type = getattr(seg, "type", "")
                            if seg_type == "text":
                                seg_content = getattr(seg, "content", "")
                                if seg_content:
                                    msg_parts.append(seg_content)
                            elif seg_type == "tool_call":
                                tc_id = getattr(seg, "tool_call_id", "")
                                if tc_id and tc_id in tool_calls_map:
                                    tc = tool_calls_map[tc_id]
                                    tool_name = getattr(tc, "tool_name", "unknown")
                                    msg_parts.append(f"🔧 *[调用工具: {tool_name}]*")
                    else:
                        # 旧格式：只有 content
                        if content:
                            msg_parts.append(content)
                        
                        # 检查 tool_call_ids
                        tool_call_ids = getattr(m, "tool_call_ids", None)
                        if tool_call_ids:
                            for tc_id in tool_call_ids:
                                if tc_id in tool_calls_map:
                                    tc = tool_calls_map[tc_id]
                                    tool_name = getattr(tc, "tool_name", "unknown")
                                    msg_parts.append(f"🔧 *[调用工具: {tool_name}]*")
                    
                    final_content = "\n".join(msg_parts) if msg_parts else "(无内容)"

                    if role == "user":
                        response += f"**👤 用户:**\n{final_content}\n\n"
                    elif role == "assistant":
                        response += f"**🤖 助手:**\n{final_content}\n\n"
                    elif role == "system":
                        response += f"**⚙️ 系统:**\n{final_content}\n\n"
                    else:
                        response += f"**🔧 {role}:**\n{final_content}\n\n"

                return response
        except Exception as e:
            logger.debug(f"Could not read archived session messages: {e}")

        # 回退：尝试读取任务执行日志（旧链路）
        log_path = Path(self.config.user_home_base) / self.exec_user / "sessions" / f"task_{task.id}" / ".claude" / "conversation.json"
        
        if log_path.exists():
            try:
                import json
                with open(log_path, 'r', encoding='utf-8') as f:
                    conversation = json.load(f)
                
                response += "\n### 💬 对话记录\n\n"
                
                messages = conversation if isinstance(conversation, list) else conversation.get('messages', [])
                
                for msg in messages[-10:]:  # 只显示最近10条
                    role = msg.get('role', 'unknown')
                    content = msg.get('content', '')
                    
                    if isinstance(content, list):
                        # 处理复杂内容格式
                        text_parts = []
                        for item in content:
                            if isinstance(item, dict):
                                if item.get('type') == 'text':
                                    text_parts.append(item.get('text', ''))
                                elif item.get('type') == 'tool_use':
                                    text_parts.append(f"[调用工具: {item.get('name', 'unknown')}]")
                            elif isinstance(item, str):
                                text_parts.append(item)
                        content = '\n'.join(text_parts)
                    
                    if len(content) > 500:
                        content = content[:500] + "..."
                    
                    if role == 'user':
                        response += f"**👤 用户:**\n{content}\n\n"
                    elif role == 'assistant':
                        response += f"**🤖 助手:**\n{content}\n\n"
                
            except Exception as e:
                logger.debug(f"Could not read conversation log: {e}")
                response += "\n### 💬 对话记录\n\n暂无对话记录或无法读取。\n"
        else:
            # 尝试其他可能的日志路径
            alt_log_path = Path(self.config.user_home_base) / self.exec_user / "data" / "task_logs" / f"{task.id}.json"
            
            if alt_log_path.exists():
                try:
                    import json
                    with open(alt_log_path, 'r', encoding='utf-8') as f:
                        log_data = json.load(f)
                    response += "\n### 📝 执行日志\n\n"
                    response += f"```json\n{json.dumps(log_data, indent=2, ensure_ascii=False)[:2000]}\n```\n"
                except Exception as e:
                    logger.debug(f"Could not read task log: {e}")
            else:
                response += "\n### 💬 对话记录\n\n"
                if status_val == "todo":
                    response += "任务尚未执行，暂无日志。\n"
                elif status_val == "doing":
                    response += "任务正在执行中...\n"
                else:
                    response += "暂无对话记录。\n"
        
        return response

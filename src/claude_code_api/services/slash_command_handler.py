# -*- coding: utf-8 -*-
"""Slash Command Handler for tswitch-rca-agent

Handles slash commands like /think, /check, /usage, /report, /cancel, /trash.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from ..config import settings
from ..logger import get_logger
from ..models.task_models import TaskPriority, TaskStatus
from .task_storage import TaskQueue

logger = get_logger(__name__)


# Known slash commands
SLASH_COMMANDS = ["/think", "/check", "/usage", "/report", "/cancel", "/trash", "/clear", "/help", "/log"]


def slugify_project(name: str) -> str:
    """Convert project name to slug format"""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


class SlashCommandHandler:
    """Handles slash commands and returns markdown responses"""

    def __init__(self, agent_name: str, config=None):
        """Initialize handler
        
        Args:
            agent_name: Linux agent user name for task isolation
            config: Optional config override
        """
        self.agent_name = agent_name
        self.config = config or settings
        
        # Initialize task queue with agent-specific database
        db_path = Path(self.config.user_home_base) / agent_name / "data" / "tasks.db"
        self._task_queue: Optional[TaskQueue] = None
        self._db_path = str(db_path)
        
        # Trash directory
        self._trash_dir = Path(self.config.user_home_base) / agent_name / "trash"

    @property
    def task_queue(self) -> TaskQueue:
        """Lazy initialization of task queue"""
        if self._task_queue is None:
            self._task_queue = TaskQueue(self._db_path, self.agent_name)
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

    def handle_command(self, content: str) -> str:
        """Handle a slash command and return markdown response
        
        Args:
            content: The full command string (e.g., "/think Build a feature")
            
        Returns:
            Markdown formatted response string
        """
        command, args = self.get_command_and_args(content)
        
        try:
            if command == "/think":
                return self._handle_think(args)
            elif command == "/check":
                return self._handle_check()
            elif command == "/usage":
                return self._handle_usage()
            elif command == "/report":
                return self._handle_report(args)
            elif command == "/cancel":
                return self._handle_cancel(args)
            elif command == "/trash":
                return self._handle_trash(args)
            elif command == "/clear":
                return self._handle_clear()
            elif command == "/help":
                return self._handle_help()
            elif command == "/log":
                return self._handle_log(args)
            else:
                return f"## ❌ Unknown Command\n\nUnknown command: `{command}`\n\n输入 `/help` 查看所有可用命令。"
        except Exception as e:
            logger.error(f"Error handling command {command}: {e}", exc_info=True)
            return f"## ❌ Error\n\nFailed to execute command: {str(e)}"

    def _handle_think(self, args: str) -> str:
        """Handle /think command - create task or capture thought
        
        Usage:
            /think <description>                      - Create THOUGHT priority task
            /think <description> -p <proj>            - Create SERIOUS priority project task
            /think <description> -w <workspace>       - Create task with workspace
            /think <description> -p <proj> -w <path>  - Create project task with workspace
        """
        if not args.strip():
            return (
                "## ❌ Missing Description\n\n"
                "**Usage:**\n"
                "- `/think <description>` - Capture a thought\n"
                "- `/think <description> -p <project>` - Create project task\n"
                "- `/think <description> -w <workspace>` - Create task with workspace\n"
                "- `/think <description> -p <project> -w <workspace>` - Full options"
            )

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
        workspace_path = Path(self.config.user_home_base) / self.agent_name / "projects" / project_id
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
            workspace_path = Path(self.config.user_home_base) / self.agent_name / "projects" / project_id
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

### 任务管理

| 命令 | 说明 |
|------|------|
| `/think <描述>` | 创建一个思考任务（低优先级） |
| `/think <描述> -p <项目>` | 创建项目任务（高优先级） |
| `/think <描述> -w <工作目录>` | 创建指定工作目录的任务 |
| `/check` | 查看系统状态和任务队列 |
| `/report` | 查看今日任务摘要 |
| `/report <任务ID>` | 查看任务详情 |
| `/report <项目名>` | 查看项目报告 |
| `/report --list` | 列出所有项目 |
| `/log <任务ID>` | 查看任务执行日志/对话记录 |
| `/cancel <任务ID>` | 取消待执行的任务 |
| `/cancel <项目名>` | 取消项目所有任务 |

### 系统管理

| 命令 | 说明 |
|------|------|
| `/usage` | 查看 Claude Code 使用量 |
| `/trash list` | 查看回收站内容 |
| `/trash restore <项目>` | 从回收站恢复项目 |
| `/trash empty` | 清空回收站 |
| `/clear` | 清除当前会话 |
| `/help` | 显示此帮助信息 |

### 任务状态说明

| 状态 | 图标 | 说明 |
|------|------|------|
| To Do | 🕒 | 等待执行 |
| Doing | 🔄 | 正在执行 |
| Done | ✅ | 执行完成 |
| Failed | ❌ | 执行失败 |
| Cancelled | 🗑️ | 已取消 |

### 示例

```
/think 优化登录页面的性能
/think 实现用户注册功能 -p myapp
/think 修复数据库连接问题 -p backend -w /home/ubuntu/projects/backend
/check
/report abc123
/log abc123
/cancel abc123
```
"""

    def _handle_log(self, args: str) -> str:
        """Handle /log command - show task execution log
        
        Usage:
            /log <task_id>  - Show task execution log/conversation
        """
        if not args.strip():
            return (
                "## ❌ Missing Task ID\n\n"
                "**Usage:** `/log <task_id>` - 查看任务执行日志\n\n"
                "**示例:** `/log abc123`"
            )

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
        
        # 尝试读取任务执行日志
        log_path = Path(self.config.user_home_base) / self.agent_name / "sessions" / f"task_{task.id}" / ".claude" / "conversation.json"
        
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
            alt_log_path = Path(self.config.user_home_base) / self.agent_name / "data" / "task_logs" / f"{task.id}.json"
            
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

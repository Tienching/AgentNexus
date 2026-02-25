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
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import logging

from ...models.task_models import TaskPriority, TaskStatus
from ...stores.session_storage import get_session_storage
from ...models.session import StoredMessage
from ...stores.task_storage import TaskQueue
from ...stores.user_config import UserConfigStore
from ...stores.concurrency_config import get_concurrency_config_store
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
SLASH_COMMANDS = ["/task", "/check", "/usage", "/report", "/cancel", "/trash", "/clear", "/help", "/chat", "/workspace", "/config", "/handoff", "/exit"]


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

        # User config store (Redis)
        self._user_config_store = UserConfigStore()

        # Store startup CWD for /exit command
        # Use config.user_home_base or Path.home() to ensure stability
        # avoiding issues where process CWD has already changed
        base = Path(self.config.user_home_base)
        if str(base).strip() == "/home":
            base = Path.home()
        self.startup_cwd = base

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

    def handle_command(
        self,
        content: str,
        source_session_id: Optional[str] = None,
        response_url: Optional[str] = None,
        callback_msg_id: Optional[str] = None,
        callback_user: Optional[str] = None,
    ) -> str:
        """Handle a slash command and return markdown response.

        Grammar (strict):
            /<cmd> <subcmd> [options...] [-- <free-text...>]

        Args:
            content: The slash command content
            source_session_id: Session ID from the source context (for task creation)
            response_url: Optional callback URL for async task completion notification
            callback_msg_id: Optional message ID to pass back in callback
            callback_user: Optional user identifier for callback

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
                    alias=parsed.options.get("alias"),
                    model=parsed.options.get("model"),
                    source_session_id=source_session_id,
                    exec_user=parsed.options.get("exec-user"),
                    response_url=response_url,
                    callback_msg_id=callback_msg_id,
                    callback_user=callback_user,
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
                    model=parsed.options.get("model"),
                    response_url=response_url,
                    callback_msg_id=callback_msg_id,
                    callback_user=callback_user,
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

            if parsed.cmd == "workspace":
                return self._handle_workspace(
                    path_arg=parsed.options.get("workspace"),
                    task_id=parsed.options.get("task"),
                    args=parsed.args,
                    current_session_id=source_session_id
                )

            if parsed.cmd == "config" and parsed.subcmd == "show":
                return self._handle_config_show(callback_user=callback_user)
            if parsed.cmd == "config" and parsed.subcmd == "set":
                return self._handle_config_set(args=parsed.args, callback_user=callback_user)
            if parsed.cmd == "config" and parsed.subcmd == "reset":
                return self._handle_config_reset(callback_user=callback_user)
            if parsed.cmd == "config" and parsed.subcmd == "concurrency":
                return self._handle_config_concurrency(args=parsed.args)

            if parsed.cmd == "exit":
                return self._handle_exit_impl(current_session_id=source_session_id)

            if parsed.cmd == "handoff":
                return self._handle_handoff(
                    provider=parsed.options.get("provider"),
                    alias=parsed.options.get("alias"),
                    model=parsed.options.get("model"),
                    auto_summary=bool(parsed.options.get("auto", False)),
                    summary=parsed.free_text,
                    current_session_id=source_session_id,
                )

            if parsed.cmd == "help" and parsed.subcmd == "show":
                return self._handle_help()

            return f"## ❌ Unknown Command\n\nUnknown command: `/{parsed.cmd} {parsed.subcmd}`\n\n输入 `/help show` 查看所有可用命令。"

        except Exception as e:
            logger.error(f"Error handling parsed command /{parsed.cmd} {parsed.subcmd}: {e}", exc_info=True)
            return f"## ❌ Error\n\nFailed to execute command: {str(e)}"

    def _import_history(self, source_session_id: str, target_session_id: str) -> None:
        """Import history from source session to target session.

        This effectively allows a new session to "inherit" the context of an old task.
        It appends messages, so it works as a merge.
        """
        try:
            if not source_session_id or not target_session_id:
                return

            storage = get_session_storage()
            source_msgs = storage.get_session_messages(source_session_id)

            if not source_msgs:
                return

            # Add a system delimiter to indicate context switch
            delimiter = StoredMessage(
                role="system",
                content=f"Context switched to session: {source_session_id}. Previous history imported below.",
                created_at=int(datetime.now(timezone.utc).timestamp() * 1000)
            )
            storage.add_session_message(target_session_id, delimiter)

            # Copy messages
            # Note: We keep original timestamps to preserve history timeline
            for msg in source_msgs:
                storage.add_session_message(target_session_id, msg)

            logger.info(f"Imported {len(source_msgs)} messages from {source_session_id} to {target_session_id}")

        except Exception as e:
            logger.error(f"Failed to import history from {source_session_id}: {e}")

    def _handle_config_show(self, callback_user: Optional[str]) -> str:
        if not callback_user:
            return "## ❌ 无法识别用户\n\n无法获取用户标识，无法显示配置。"

        user_cfg = self._user_config_store.get_all(callback_user)
        default_provider = (getattr(self.config, "default_provider", None) or "").strip()
        default_alias = (getattr(self.config, "default_alias", None) or "").strip()
        default_exec_user = (getattr(self.config, "default_exec_user", None) or "").strip()

        effective_provider = (user_cfg.get("provider") or "").strip() or default_provider or "codebuddy"
        effective_exec_user = (user_cfg.get("exec_user") or "").strip() or default_exec_user or ""
        effective_alias = (user_cfg.get("alias") or "").strip() or default_alias or (user_cfg.get("provider") or "").strip() or effective_provider

        def _display(val: str) -> str:
            return val if val else "未设置"

        response = "## ⚙️ 当前配置\n\n"
        response += "| 项 | 用户设置 | 生效值 |\n"
        response += "|---|---|---|\n"
        response += f"| Provider | {_display(user_cfg.get('provider') or '')} | {effective_provider} |\n"
        response += f"| Exec User | {_display(user_cfg.get('exec_user') or '')} | {_display(effective_exec_user)} |\n"
        response += f"| Alias | {_display(user_cfg.get('alias') or '')} | {effective_alias} |\n"
        response += "\n**设置示例：** `/config -s provider claude`\n"
        response += "\n**并发配置：** `/config -c` 查看并发限制"
        return response

    def _handle_config_set(self, args: list, callback_user: Optional[str]) -> str:
        if not callback_user:
            return "## ❌ 无法识别用户\n\n无法获取用户标识，无法设置配置。"

        if not args or len(args) < 2:
            return "## ❌ 缺少参数\n\n**Usage:** `/config -s <key> <value>`\n\n支持的 key: `provider`, `exec_user`, `alias`。"

        key = (args[0] or "").strip()
        value = " ".join(args[1:]).strip()
        if not value:
            return "## ❌ 缺少参数\n\n**Usage:** `/config -s <key> <value>`"

        try:
            ok = self._user_config_store.set(callback_user, key, value)
        except ValueError as e:
            return f"## ❌ 无效配置\n\n{str(e)}\n\n支持的 key: `provider`, `exec_user`, `alias`。"

        if not ok:
            return "## ❌ 设置失败\n\n请稍后重试。"

        return f"## ✅ 已更新\n\n`{key}` 已设置为 `{value}`。"

    def _handle_config_reset(self, callback_user: Optional[str]) -> str:
        if not callback_user:
            return "## ❌ 无法识别用户\n\n无法获取用户标识，无法重置配置。"

        ok = self._user_config_store.reset(callback_user)
        if not ok:
            return "## ❌ 重置失败\n\n请稍后重试。"
        return "## ✅ 已重置\n\n用户配置已清空。"

    def _handle_config_concurrency(self, args: list) -> str:
        """Handle ``/config -c [show | set <key> <value> | reset <key>]``.

        Sub-actions (positional args):
            (empty) / show     – display current concurrency configuration.
            set global <N>     – set global max concurrency (0 = unlimited).
            set <alias> <N>    – set per-provider/alias max concurrency.
            reset global       – remove global concurrency limit.
            reset <alias>      – remove per-provider/alias limit.
        """
        store = get_concurrency_config_store()
        action = (args[0] if args else "show").strip().lower()

        # ---- show ----
        if action in ("show", ""):
            cfg = store.get_all()
            global_val = cfg.get("global_max_concurrency", 0)
            provider_map = cfg.get("provider_concurrency", {})

            response = "## ⚙️ 并发配置\n\n"
            response += f"**全局最大并发** (global): `{global_val if global_val else '无限制'}`\n\n"

            if provider_map:
                response += "**Provider / Alias 并发限制：**\n\n"
                response += "| Name | Max Concurrency |\n|---|---|\n"
                for name, limit in sorted(provider_map.items()):
                    response += f"| {name} | {limit} |\n"
            else:
                response += "_暂无 Provider/Alias 级别的并发限制。_\n"

            response += "\n**设置示例：**\n"
            response += "- `/config -c set global 10` — 设置全局最大并发为 10\n"
            response += "- `/config -c set claude 3` — 设置 claude 的最大并发为 3\n"
            response += "- `/config -c reset claude` — 移除 claude 的并发限制\n"

            # Hot-reload executor hint
            response += "\n_设置后立即生效。_"
            return response

        # ---- set ----
        if action == "set":
            if len(args) < 3:
                return "## ❌ 缺少参数\n\n**Usage:** `/config -c set <name|global> <number>`"
            key = args[1].strip().lower()
            try:
                value = int(args[2])
            except (ValueError, TypeError):
                return f"## ❌ 无效数值\n\n`{args[2]}` 不是有效的整数。"

            if value < 0:
                return "## ❌ 无效数值\n\n并发数必须 >= 0（0 表示无限制）。"

            try:
                if key == "global":
                    ok = store.set_global_concurrency(value)
                else:
                    ok = store.set_provider_concurrency(key, value)
            except ValueError as e:
                return f"## ❌ 设置失败\n\n{e}"

            if not ok:
                return "## ❌ 设置失败\n\n请稍后重试。"

            # Hot-reload into running executor
            self._apply_concurrency_to_executor(key, value)

            label = "全局" if key == "global" else key
            desc = str(value) if value > 0 else "无限制"
            return f"## ✅ 已更新\n\n`{label}` 最大并发已设置为 `{desc}`。"

        # ---- reset ----
        if action == "reset":
            if len(args) < 2:
                return "## ❌ 缺少参数\n\n**Usage:** `/config -c reset <name|global>`"
            key = args[1].strip().lower()
            if key == "global":
                ok = store.set_global_concurrency(0)
            else:
                ok = store.remove_provider_concurrency(key)
            if not ok:
                return "## ❌ 重置失败\n\n请稍后重试。"
            self._apply_concurrency_to_executor(key, 0)
            label = "全局" if key == "global" else key
            return f"## ✅ 已重置\n\n`{label}` 并发限制已移除。"

        return (
            "## ❌ 未知操作\n\n"
            "支持的操作: `show`, `set`, `reset`。\n\n"
            "**示例:** `/config -c set claude 3`"
        )

    @staticmethod
    def _apply_concurrency_to_executor(key: str, value: int) -> None:
        """Hot-reload concurrency setting into the running executor."""
        try:
            from ...execution.task_executor import get_executor
            executor = get_executor()
            if executor:
                if key == "global":
                    executor.set_global_concurrency(value)
                else:
                    executor.set_provider_concurrency(key, value)
        except Exception as e:
            logger.warning(f"Failed to hot-reload concurrency to executor: {e}")

    def _handle_task_create(
        self,
        description: str,
        project_name: Optional[str] = None,
        workspace: Optional[str] = None,
        inplace: bool = False,
        provider: Optional[str] = None,
        alias: Optional[str] = None,
        model: Optional[str] = None,
        source_session_id: Optional[str] = None,
        exec_user: Optional[str] = None,
        response_url: Optional[str] = None,
        callback_msg_id: Optional[str] = None,
        callback_user: Optional[str] = None,
    ) -> str:
        """Handle `/task create` (strict syntax; free text must be after `--`).

        Args:
            source_session_id: Session ID from the source context.
                              Task session_id will be {source_session_id}_{task_id}.
            exec_user: Optional exec_user (CLI executor user) for task execution.
                       If not provided, uses the default exec_user from task queue.
            response_url: Optional callback URL for task completion notification.
            callback_msg_id: Optional message ID to pass back in callback.
            callback_user: Optional user identifier for callback.
        """
        if not (description or "").strip():
            return (
                "## ❌ Missing Description\n\n"
                f"**Usage:** `{usage_for('task', 'create')}`"
            )

        # Determine priority
        priority = TaskPriority.PROJECT if project_name else TaskPriority.THOUGHT
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

        def _safe_str(value: Optional[str]) -> str:
            return value.strip() if isinstance(value, str) else ""

        user_config = self._user_config_store.get_all(callback_user) if callback_user else {}
        user_provider = _safe_str(user_config.get("provider"))
        user_exec_user = _safe_str(user_config.get("exec_user"))
        user_alias = _safe_str(user_config.get("alias"))

        default_provider = _safe_str(getattr(self.config, "default_provider", None))
        default_alias = _safe_str(getattr(self.config, "default_alias", None))
        default_exec_user = _safe_str(getattr(self.config, "default_exec_user", None))
        effective_exec_user = _safe_str(exec_user) or user_exec_user or default_exec_user or None

        # Resolve alias -> provider mapping.
        # Priority: explicit -l > user config alias > default_alias
        effective_alias = _safe_str(alias) or user_alias or default_alias or None
        explicit_provider = _safe_str(provider).lower()

        from src.runtime.stores.alias_registry import get_alias_registry
        alias_registry = get_alias_registry()

        if effective_alias:
            resolved = alias_registry.resolve(effective_alias)
            if resolved:
                # Alias is valid.  Use resolved provider unless explicit -r overrides.
                effective_provider = explicit_provider or resolved
            else:
                # Unknown alias — show all registered aliases for reference.
                all_aliases = alias_registry.list_all()
                alias_list = ", ".join(f"`{a}`" for a in sorted(all_aliases.keys()))
                return (
                    f"## ❌ 未知别名\n\n"
                    f"别名 `{effective_alias}` 未注册。\n\n"
                    f"**可用别名**: {alias_list}\n\n"
                    f"请使用已注册的别名，或先注册：\n"
                    f"```\n/alias -r {effective_alias} <provider>\n```"
                )
        else:
            effective_provider = explicit_provider or user_provider or default_provider or "codebuddy"

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
            model=(model or "").strip() or None,
            task_id=task_id,
            source_session_id=source_session_id,
            exec_user=effective_exec_user,
            response_url=response_url,
            callback_msg_id=callback_msg_id,
            callback_user=callback_user,
        )

        priority_emoji = "🔴" if priority == TaskPriority.PROJECT else "💭"
        priority_label = "Project" if priority == TaskPriority.PROJECT else "Thought"

        response = f"## {priority_emoji} {priority_label} Task Created\n\n"
        response += "| Field | Value |\n"
        response += "|-------|-------|\n"
        response += f"| Task ID | #{task.id} |\n"
        response += f"| Priority | {priority_label} |\n"
        if effective_provider:
            response += f"| Provider | {effective_provider} |\n"
        if effective_alias:
            response += f"| Alias | {effective_alias} |\n"
        if effective_exec_user:
            response += f"| Exec User | {effective_exec_user} |\n"
        if task.model:
            response += f"| Model | {task.model} |\n"
        if project_name:
            response += f"| Project | {project_name} |\n"
        if requested_workspace:
            response += f"| Workspace | `{requested_workspace}` |\n"
        if exec_workspace:
            response += f"| Exec CWD | `{exec_workspace}` |\n"
        response += f"\n**Description:** {description.strip()}"

        return response

    def _handle_chat_continue(
        self,
        task_id: str,
        message: str,
        model: Optional[str] = None,
        response_url: Optional[str] = None,
        callback_msg_id: Optional[str] = None,
        callback_user: Optional[str] = None,
    ) -> str:
        """Handle `/chat continue` - enqueue a background run for an existing task.

        Args:
            response_url: Optional callback URL for completion notification.
            callback_msg_id: Optional message ID to pass back in callback.
            callback_user: Optional user identifier for callback.
        """
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
            self.task_queue.enqueue_chat_continue(
                task_id,
                msg,
                model=model,
                response_url=response_url,
                callback_msg_id=callback_msg_id,
                callback_user=callback_user,
            )
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

    def _find_claude_session_id(self, task_dir: Path) -> Optional[str]:
        """Find Claude CLI session UUID from task directory.

        Claude stores sessions in ~/.claude/projects/{path-with-dashes}/
        The main session file is {uuid}.jsonl (not agent-*.jsonl)

        Args:
            task_dir: The task's execution directory

        Returns:
            Claude CLI session UUID if found, None otherwise
        """
        try:
            # Transform path: /home/ubuntu/sessions/xxx_taskid → -home-ubuntu-sessions-xxx-taskid
            path_str = str(task_dir.resolve())
            projects_dir_name = path_str.replace("/", "-").replace("_", "-")

            claude_projects_dir = Path.home() / ".claude" / "projects" / projects_dir_name

            if not claude_projects_dir.exists():
                logger.debug(f"Claude projects dir not found: {claude_projects_dir}")
                return None

            # Find session UUID file (*.jsonl but not agent-*.jsonl)
            for f in claude_projects_dir.iterdir():
                if f.suffix == ".jsonl" and not f.name.startswith("agent-"):
                    logger.info(f"Found Claude session UUID: {f.stem}")
                    return f.stem  # Return UUID without extension

            return None
        except Exception as e:
            logger.warning(f"Failed to find Claude session ID: {e}")
            return None

    def _handle_workspace(self, path_arg: Optional[str] = None, task_id: Optional[str] = None, args: Optional[list] = None, current_session_id: Optional[str] = None) -> str:
        """Handle /workspace command - change process working directory

        Usage:
            /workspace              - Show current directory
            /workspace -w <path>    - Switch to path
            /workspace -t <taskid>  - Switch to task workspace
        """
        # Reject positional args if present
        if args or (path_arg is None and task_id is None and args):
            # Special case: if strictly no args/options, it means "Show current" (args is empty list)
            # But if args has content, it's invalid usage.
            if args:
                return (
                    "## ❌ Invalid Usage\n\n"
                    "Positional arguments are not supported.\n"
                    "**Usage:**\n"
                    "- `/workspace` (Show current)\n"
                    "- `/workspace -w <path>`\n"
                    "- `/workspace -t <task_id>`"
                )

        # No options -> Show current execution directory
        if not path_arg and not task_id:
            # Check if there's an exec_dir override for this session
            actual_exec_dir = None
            if current_session_id:
                try:
                    storage = get_session_storage()
                    actual_exec_dir = storage.get_exec_dir_override(current_session_id)
                except Exception:
                    pass

            if actual_exec_dir:
                return f"## 📂 Current Workspace\n\n`{actual_exec_dir}`\n(Overridden by /workspace -t)"
            else:
                # Default: show the session directory (even if not yet created)
                base = Path(self.config.user_home_base)
                if str(base).strip() == "/home":
                    base = Path.home()
                if current_session_id:
                    session_dir = base / "sessions" / current_session_id
                    # Always show the session directory path, regardless of existence
                    # The directory will be created when Claude CLI executes
                    return f"## 📂 Current Workspace\n\n`{session_dir}`"
                # Fallback: no session_id available (should be rare)
                return f"## 📂 Current Workspace\n\n`{os.getcwd()}`"

        target_path = None
        found_session_id = None  # Track the actual session ID from directory name

        # Resolve path from task_id
        if task_id:
            task = self.task_queue.get_task(task_id)
            if not task:
                return f"## ❌ Not Found\n\nTask `{task_id}` not found."

            if task.workspace:
                target_path = task.workspace
                found_session_id = task.session_id  # Use task's session_id if workspace is set
            else:
                # Fallback logic to find session directory
                # 1. Determine correct base (handle misconfigured user_home_base)
                base = Path(self.config.user_home_base)
                if str(base).strip() == "/home":
                    base = Path.home()  # e.g. /home/ubuntu

                sessions_dir = base / "sessions"
                found = None

                # 2. Try task.session_id (best match)
                if task.session_id:
                    p = sessions_dir / task.session_id
                    if p.exists():
                        found = p
                        found_session_id = task.session_id

                # 3. Search for directory ending in _{task_id} (e.g. uuid_taskid)
                if not found and sessions_dir.exists():
                    suffix = f"_{task.id}"
                    for child in sessions_dir.iterdir():
                        if child.is_dir() and child.name.endswith(suffix):
                            found = child
                            found_session_id = child.name  # Use actual directory name as session_id
                            break

                # 4. Fallback to standard naming
                if not found:
                    found = sessions_dir / f"task_{task.id}"
                    found_session_id = f"task_{task.id}"

                target_path = str(found)

        # Resolve explicit path (overrides task if both provided? or error? prioritizing path)
        if path_arg:
            target_path = path_arg

        if not target_path:
            return "## ❌ Error\n\nCould not determine target path."

        try:
            p = Path(target_path).resolve()

            if not p.exists():
                 return f"## ❌ Not Found\n\nDirectory not found: `{p}`"

            if not p.is_dir():
                 return f"## ❌ Invalid Path\n\nNot a directory: `{p}`"

            os.chdir(p)
            response = f"## 📂 Workspace Changed\n\n**New CWD:** `{os.getcwd()}`"

            if task_id and not path_arg:
                response += f"\n(Switched to task #{task_id} workspace)"

                # Set exec_dir override for subsequent commands to use -c in this directory
                if current_session_id:
                    storage = get_session_storage()
                    storage.set_exec_dir_override(current_session_id, str(p))
                    # Also set target_session_id so messages get archived to task's session
                    if found_session_id:
                        storage.set_target_session_id(current_session_id, found_session_id)

                        # Import task session history into current session for context continuity.
                        # This ensures:
                        # 1. Web UI can display the full conversation history
                        # 2. If Claude CLI's -c cannot restore (e.g., different user, cleaned
                        #    ~/.claude), the history is still available in Redis
                        self._import_history(found_session_id, current_session_id)

                    # Store the task's provider so CLI executor uses the correct
                    # resume mechanism (e.g., gemini -> --resume latest, codex -> resume --last)
                    task_provider = getattr(task, "provider", None) or "codebuddy"
                    storage.set_workspace_provider(current_session_id, task_provider)

                    # Store the task's original alias so CLI executor uses the correct
                    # CLI command (e.g., 'gemini-internal' instead of 'gemini')
                    task_alias = getattr(task, "alias", None)
                    if task_alias:
                        storage.set_workspace_alias(current_session_id, task_alias)

                    response += f"\n(Provider: {task_provider}, Alias: {task_alias or 'none'}, context will be restored)"

            return response

        except Exception as e:
            return f"## ❌ Error\n\nFailed to change directory: {e}"

    def _handle_exit(self) -> str:
        """Handle /exit command - return to current session's directory.

        Instead of returning to global home (/home/ubuntu), this should return to
        the session-specific directory if it exists, or home if not.
        """
        current = Path.cwd()

        # Determine the "Home" for this session
        # Logic: {home_base}/sessions/{current_session_id}
        # But wait, we don't have current_session_id stored in self.
        # We need to capture it or infer it.
        # Since _handle_exit doesn't take session_id, we might need to rely on self.startup_cwd
        # BUT self.startup_cwd was set to user_home_base.

        # Let's try to restore to the directory where the process started,
        # which ideally should be the session root if the agent was launched correctly.
        # IF self.startup_cwd is set to /home/ubuntu, that's "too far back".

        # Refined Logic:
        # If we are inside a task directory (sessions/UUID_taskID), we want to go up to sessions/UUID?
        # No, "session directory" usually IS the task directory in this flat structure.
        # The user wants to go back to "this session's default address".
        # If the session started in /home/ubuntu/sessions/main_session, we should go there.

        # Since we can't easily know the "original session ID" without passing it,
        # let's assume the user wants to go to self.startup_cwd (which we previously forced to /home/ubuntu).
        # User says: "exit should enter this session's session_id directory".

        # We will need to pass current_session_id to _handle_exit.
        return self._handle_exit_impl()

    def _handle_exit_impl(self, current_session_id: Optional[str] = None) -> str:
        # Default target is the session directory (not startup_cwd which is /home/ubuntu)
        target = self.startup_cwd

        # Clear target_session_id when exiting (messages should go back to original session)
        # But keep/set exec_dir_override to session directory so -c flag is used
        if current_session_id:
            try:
                storage = get_session_storage()
                # Clear target_session_id - messages should go back to original session
                storage.clear_target_session_id(current_session_id)
                # Clear workspace_provider - no longer in a task workspace
                storage.clear_workspace_provider(current_session_id)
                # Clear workspace_alias - no longer in a task workspace
                storage.clear_workspace_alias(current_session_id)
            except Exception as e:
                logger.warning(f"Failed to clear target_session_id/workspace_provider/workspace_alias: {e}")

            # Return to session directory (the correct "home" for this session)
            base = self.startup_cwd
            session_dir = base / "sessions" / current_session_id
            # Always use session directory - create it if it doesn't exist
            if not session_dir.exists():
                try:
                    session_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Created session directory: {session_dir}")
                except Exception as e:
                    logger.warning(f"Failed to create session directory: {e}")
            target = session_dir

            # Set exec_dir_override to session directory so -c flag is used
            # This ensures context inheritance continues in the original session
            try:
                storage = get_session_storage()
                storage.set_exec_dir_override(current_session_id, str(target))
            except Exception as e:
                logger.warning(f"Failed to set exec_dir_override for session: {e}")

        current = Path.cwd()
        if current == target:
            return "## ℹ️ Already at Home\n\nYou are already at the default directory."

        try:
            os.chdir(target)
            return f"## 🏠 Returned Home\n\nRestored working directory: `{target}`"
        except Exception as e:
            return f"## ❌ Error\n\nFailed to restore directory: {e}"

    def _handle_handoff(
        self,
        provider: Optional[str] = None,
        alias: Optional[str] = None,
        model: Optional[str] = None,
        auto_summary: bool = False,
        summary: Optional[str] = None,
        current_session_id: Optional[str] = None,
    ) -> str:
        """Handle /handoff command - switch provider with optional context handoff.

        Usage:
            /handoff                     # Show current provider
            /handoff -r <provider>       # Direct switch (no context)
            /handoff -l <alias>          # Switch by alias (no context)
            /handoff -r <provider> -m <model>  # Switch with model override
            /handoff -r <provider> -a    # Auto-generate summary and switch
            /handoff -l <alias> -a       # Auto-generate summary and switch by alias
            /handoff -r <provider> -- <summary>  # Manual summary and switch

        Args:
            provider: Target provider to switch to
            alias: Target alias to switch to (alternative to provider)
            model: LLM model name to use after switching
            auto_summary: Whether to auto-generate summary from current Agent
            summary: Manual summary text (after --)
            current_session_id: Current session ID

        Returns:
            Markdown response, or special JSON for auto-summary trigger
        """
        import json

        # Resolve provider from alias if specified
        target_alias = None
        target_provider = provider

        if alias:
            from ...stores.alias_registry import get_alias_registry
            alias_registry = get_alias_registry()
            resolved = alias_registry.resolve(alias)
            if resolved:
                target_provider = resolved
                target_alias = alias
            else:
                all_aliases = alias_registry.list_all()
                alias_list = ", ".join(f"`{a}`" for a in sorted(all_aliases.keys()))
                return (
                    f"## ❌ 未知别名\n\n"
                    f"别名 `{alias}` 未注册。\n\n"
                    f"**可用别名**: {alias_list}"
                )

        # No provider/alias specified - show current provider and handoff status
        if not target_provider:
            user_cfg = self._user_config_store.get_all(current_session_id) if current_session_id else {}
            default_provider = (getattr(self.config, "default_provider", None) or "").strip()
            current_provider = (user_cfg.get("provider") or "").strip() or default_provider or "codebuddy"
            current_alias = (user_cfg.get("alias") or "").strip() or current_provider

            response = "## 🔄 当前 Provider\n\n"
            response += f"| 项 | 值 |\n"
            response += f"|---|---|\n"
            response += f"| Provider | `{current_provider}` |\n"
            response += f"| Alias | `{current_alias}` |\n"

            # Check handoff status
            if current_session_id:
                storage = get_session_storage()
                
                # Check pending summary
                pending_target = storage.get_handoff_pending_summary(current_session_id)
                if pending_target:
                    response += f"\n### ⏳ 交接状态：等待生成摘要\n\n"
                    response += f"- **目标**: `{pending_target}`\n"
                    response += f"- **状态**: 待生成摘要\n"
                    response += f"- **下一步**: 发送任意消息触发摘要生成\n"
                else:
                    # Check handoff context
                    handoff_result = storage.get_handoff_context(current_session_id)
                    if handoff_result:
                        ctx, target = handoff_result
                        if ctx:
                            # 有摘要内容，等待切换
                            response += f"\n### ✅ 交接状态：已就绪\n\n"
                            response += f"- **目标**: `{target}`\n"
                            response += f"- **状态**: 摘要已生成，等待切换\n"
                            response += f"- **下一步**: 发送任意消息将切换到 `{target}`\n"
                            if len(ctx) > 100:
                                response += f"- **摘要预览**: {ctx[:100]}...\n"
                            else:
                                response += f"- **摘要内容**: {ctx}\n"
                        else:
                            # 空摘要，可能是直接切换
                            response += f"\n### 🔄 交接状态：待切换\n\n"
                            response += f"- **目标**: `{target}`\n"
                            response += f"- **状态**: 无摘要，直接切换\n"
                            response += f"- **下一步**: 发送任意消息将切换到 `{target}`\n"

            response += "\n**切换示例：**\n"
            response += "- `/handoff -r codex` — 直接切换 Provider\n"
            response += "- `/handoff -l gemini-internal` — 通过别名切换\n"
            response += "- `/handoff -r codex -a` — 自动生成摘要后切换\n"
            response += "- `/handoff -r codex -- 手动摘要内容` — 手动摘要切换\n"
            return response

        # Validate provider
        from ...stores.alias_registry import get_alias_registry
        alias_registry = get_alias_registry()
        resolved = alias_registry.resolve(target_provider)
        if not resolved:
            # Check if it's a valid provider name directly
            valid_providers = ["claude", "codex", "gemini", "codebuddy"]
            if target_provider.lower() not in valid_providers:
                all_aliases = alias_registry.list_all()
                alias_list = ", ".join(f"`{a}`" for a in sorted(all_aliases.keys()))
                return (
                    f"## ❌ 未知 Provider\n\n"
                    f"Provider `{target_provider}` 未注册。\n\n"
                    f"**可用别名**: {alias_list}\n\n"
                    f"**内置 Provider**: {', '.join(f'`{p}`' for p in valid_providers)}"
                )

        # Resolve effective model
        effective_model = (model or "").strip() or None

        # Auto-summary mode: set pending state, next message will trigger summary generation
        if auto_summary:
            if not current_session_id:
                return "## ❌ 无法切换\n\n需要 session_id 才能自动生成摘要。"

            # Store pending switch target (empty context means summary pending)
            storage = get_session_storage()
            effective_alias = target_alias or target_provider.lower()
            storage.set_handoff_pending_summary(current_session_id, effective_alias, model=effective_model)

            # Return markdown message
            response = f"## 🔄 准备切换 Provider\n\n"
            response += f"- **目标 Provider**: `{target_provider}`\n"
            if target_alias:
                response += f"- **目标 Alias**: `{target_alias}`\n"
            if effective_model:
                response += f"- **Model**: `{effective_model}`\n"
            response += f"- **状态**: 等待生成摘要\n\n"
            response += f"请发送任意消息，当前 Agent 会先生成对话摘要，然后自动切换到 `{effective_alias}` 并继续处理您的消息。"

            return response

        # Direct switch or manual summary
        if current_session_id:
            storage = get_session_storage()
            effective_alias = target_alias or target_provider.lower()

            if summary:
                # Manual summary provided
                storage.set_handoff_context(current_session_id, summary, effective_alias, model=effective_model)
                response = f"## ✅ 准备切换\n\n"
                response += f"- **目标 Provider**: `{target_provider}`\n"
                if target_alias:
                    response += f"- **目标 Alias**: `{target_alias}`\n"
                if effective_model:
                    response += f"- **Model**: `{effective_model}`\n"
                response += f"- **上下文摘要**: 已保存\n\n"
                response += f"下一次对话将自动切换到 `{effective_alias}` 并注入摘要上下文。"
            else:
                # Direct switch (no context) — store model via handoff_context with empty context
                if effective_model:
                    storage.set_handoff_context(current_session_id, "", effective_alias, model=effective_model)
                else:
                    storage.clear_handoff_context(current_session_id)
                response = f"## ✅ 切换 Provider\n\n"
                response += f"- **目标 Provider**: `{target_provider}`\n"
                if target_alias:
                    response += f"- **目标 Alias**: `{target_alias}`\n"
                if effective_model:
                    response += f"- **Model**: `{effective_model}`\n"
                response += f"- **上下文传递**: 无\n\n"
                response += f"下一次对话将使用 `{effective_alias}`。"

            return response

        return f"## ✅ 切换 Provider\n\n目标 Provider: `{target_provider}`"

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
/task [-p <项目>] [-w <路径> [-i]] [-r <provider>] [-u <exec_user>] [-l <alias>] [-m <model>] -- <描述>
```
- 可选 `-r/--provider` 指定执行 Provider（未指定则使用默认配置）
- 可选 `-u/--exec-user` 指定执行用户（未指定则使用默认配置）
- 可选 `-l/--alias` 指定别名（未指定则默认等于 Provider）
- 可选 `-m/--model` 指定 LLM 模型（如 claude-opus-4.6, gemini-2.5-pro）

**`/chat`** - 对话管理
```
/chat -t <任务ID>              # 查看记录
/chat -t <ID> -n <N>           # 最近N条
/chat -c -t <ID> -- <msg>      # 续聊
/chat -c -t <ID> -m <model> -- <msg>  # 续聊并切换模型
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

### 工作区管理

**`/workspace`** - 切换目录
```
/workspace              # 显示当前目录
/workspace -w <path>    # 切换到指定路径
/workspace -t <task_id> # 切换到任务目录
```

**`/exit`** - 退出
```
/exit                   # 回退到初始目录
```

**`/handoff`** - 切换 Provider（带上下文传递）
```
/handoff                 # 显示当前 Provider
/handoff -r <provider>   # 直接切换（无上下文）
/handoff -l <alias>      # 通过别名切换
/handoff -r <provider> -m <model>  # 切换并指定模型
/handoff -r <provider> -a    # 自动生成摘要后切换
/handoff -r <provider> -- <摘要>  # 手动摘要切换
```

---

### 系统管理

**`/config`** - 用户配置
```
/config                 # 查看当前配置
/config -s <key> <value> # 设置配置
/config -r              # 重置配置
```
- 支持的 key: `provider`, `exec_user`, `alias`

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

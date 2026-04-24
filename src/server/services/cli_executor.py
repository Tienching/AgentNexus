# -*- coding: utf-8 -*-
"""CLI Command Executor Service

Responsibilities:
- Build and execute CLI commands for all providers (Claude, Gemini, Codex, CodeBuddy)
- Process streaming output
- 格式化 SSE 响应
"""

import asyncio
import json
import shlex
import time
import re
import uuid
import os
import pwd
import tempfile
from pathlib import Path
from typing import AsyncGenerator, List, Dict, Any, Optional

from ..models import RequestModel
from src.runtime.events.agui import (
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    MessageRole,
)
from ..config import settings
from ..logger import get_logger
from .user_directory import UserDirectoryManager
from src.runtime.commands.slash.handler import SlashCommandHandler, SLASH_COMMANDS
from src.runtime.commands.slash.parser import SlashCommandParseError, parse_slash_command
from src.runtime.history import HistoryService
from src.providers.persistent import PersistentProcessManager

logger = get_logger(__name__)

# Debug模式：将完整的stream-json输出保存到文件
DEBUG_STREAM = os.environ.get("DEBUG_STREAM", "0") == "1"
# 安全修复: 不使用世界可读的 /tmp，改用 log 目录或环境变量指定的安全路径
_debug_stream_default = os.path.join(settings.log_dir, "debug_stream.jsonl")
DEBUG_STREAM_FILE = os.environ.get("DEBUG_STREAM_FILE", _debug_stream_default)


def _resolve_agent_loop():
    """Best-effort resolver used by runtime slash extensions that need AgentLoop."""
    try:
        from src.server.app import get_agent_loop

        return get_agent_loop()
    except Exception:
        return None


class CLIExecutor:
    """CLI 命令执行器（服务于所有 Provider）"""

    def __init__(self, config=None):
        self.config = config or settings
        self.user_dir_manager = UserDirectoryManager(config)
        self._slash_handlers: Dict[str, SlashCommandHandler] = {}
        self._current_process: Optional[asyncio.subprocess.Process] = None
        # Persistent process manager (lazy-init on first use when enabled)
        self._persistent_manager: Optional[PersistentProcessManager] = None
        if getattr(self.config, "persistent_enabled", False):
            self._persistent_manager = PersistentProcessManager(self.config)

    def kill_process(self) -> None:
        """Kill the currently running subprocess if any.

        Called by the outer timeout handler in channel_service to prevent
        orphan CLI processes when the overall request times out.
        """
        proc = self._current_process
        if proc and proc.returncode is None:
            try:
                proc.kill()
                logger.info(f"Killed orphan CLI process (pid={proc.pid})")
            except (ProcessLookupError, OSError):
                pass

    def _get_slash_handler(self, exec_user: str) -> SlashCommandHandler:
        """Get or create slash command handler for exec_user"""
        if exec_user not in self._slash_handlers:
            handler = SlashCommandHandler(exec_user, self.config)
            handler.agent_loop_resolver = _resolve_agent_loop
            self._slash_handlers[exec_user] = handler
        return self._slash_handlers[exec_user]

    def _resolve_execution_binding(self, storage, session_id: Optional[str]):
        """Resolve the best available execution binding for a session."""
        if not storage or not session_id:
            return None

        getter = getattr(storage, "get_effective_execution_binding", None)
        if callable(getter):
            try:
                binding = getter(session_id)
                if binding:
                    return binding
            except Exception:
                pass

        getter = getattr(storage, "get_execution_binding", None)
        if callable(getter):
            try:
                binding = getter(session_id)
                if binding:
                    return binding
            except Exception:
                pass

        getter = getattr(storage, "get_session_meta", None)
        if callable(getter):
            try:
                meta = getter(session_id)
            except Exception:
                meta = None
            if meta:
                try:
                    binding = getattr(meta, "execution_binding", None)
                    if binding:
                        return binding
                except Exception:
                    pass
                try:
                    return meta.to_execution_binding()
                except Exception:
                    pass
        return None

    def _is_slash_command(self, content: str) -> bool:
        """Check if content is a slash command (excluding /clear which has special handling)"""
        content_lower = content.lower().strip()
        for cmd in SLASH_COMMANDS:
            if content_lower == cmd or content_lower.startswith(cmd + " "):
                return True
        return False

    async def execute(
        self,
        request: RequestModel,
        exec_user: str,
        output_format: str = "raw"
    ) -> AsyncGenerator[str, None]:
        """
        执行 CLI 命令并生成流式输出

        Args:
            request: 请求模型
            exec_user: Linux系统用户名
            output_format: 输出格式 - "raw"(原始JSON行), "legacy"(Legacy格式)

        Yields:
            原始JSON行或格式化的SSE
        """
        start_time = time.time()

        # 验证用户参数
        if not request.user:
            logger.error(f"Missing required user parameter", extra={"exec_user": exec_user})
            raise ValueError("用户名参数是必需的，请在请求中提供 'user' 字段")

        # 清理输入内容
        cleaned_content = self._clean_content(request.content)

        # Helper: yield a markdown-like slash response (works for both protocols)
        def _format_slash_result(text: str, is_error: bool = False) -> str:
            # For raw output, return a pseudo "result" event; legacy formatting is handled by caller.
            if output_format == "legacy":
                return self.format_legacy_sse(text, finished=True, answer_success=0 if is_error else 1)
            return json.dumps({
                "type": "result",
                "subtype": "slash_command",
                "content": text,
            })

        # Removed commands (explicit error; no compatibility)
        lowered = (cleaned_content or "").lower().strip()
        if lowered == "/think" or lowered.startswith("/think "):
            yield _format_slash_result(
                "## ❌ 命令已移除\n\n`/think` 命令已移除。",
                is_error=True,
            )
            return
        if lowered == "/log" or lowered.startswith("/log "):
            yield _format_slash_result(
                "## ❌ 命令已移除\n\n`/log` 命令已移除。",
                is_error=True,
            )
            return

        # Slash commands (strict grammar)
        if self._is_slash_command(cleaned_content):
            try:
                parsed = parse_slash_command(cleaned_content)
            except SlashCommandParseError as e:
                usage = (e.usage or "").strip()
                if usage:
                    yield _format_slash_result(f"## ❌ 命令解析失败\n\n{e.message}\n\n**Usage:** `{usage}`", is_error=True)
                else:
                    yield _format_slash_result(f"## ❌ 命令解析失败\n\n{e.message}", is_error=True)
                return

            # /clear now: clear directory and return immediately
            if parsed.cmd == "clear" and parsed.subcmd == "now":

                session_id = request.session_id if request.session_id else "default"
                user_dir = await self.user_dir_manager.ensure_directory(exec_user, request.user, session_id)
                await self.user_dir_manager.clear_directory(exec_user, request.user, user_dir, session_id)
                await self.user_dir_manager.ensure_directory(exec_user, request.user, session_id)

                # Clear Redis resume state so the next CLI invocation starts
                # a fresh session instead of resuming the old one.
                try:
                    from ...runtime.stores.session_storage import get_session_storage
                    _clear_storage = get_session_storage()
                    _clear_storage.clear_cli_session_id(session_id)
                    _clear_storage.set_session_cleared(session_id)
                    _clear_storage.clear_persistent_mode(session_id)
                    # Clear active_model to avoid false model_changed detection
                    _clear_storage.clear_active_model(session_id)
                    logger.info(f"/clear: cleared Redis resume state for session {session_id}")
                except Exception as e:
                    logger.warning(f"/clear: failed to clear Redis resume state: {e}")

                # Destroy persistent process for this session if one exists
                if self._persistent_manager:
                    try:
                        await self._persistent_manager.destroy(session_id)
                        logger.info(f"/clear: destroyed persistent process for session {session_id}")
                    except Exception as e:
                        logger.warning(f"/clear: failed to destroy persistent process: {e}")

                yield _format_slash_result(
                    "## 🔄 Session Cleared\n\nYour session has been cleared. A fresh workspace has been created.",
                    is_error=False,
                )
                return

            # Other slash commands: handled locally
            else:
                source_session_id = request.session_id if request.session_id else None
                logger.info(f"Slash command: request.session_id={request.session_id!r}, source_session_id={source_session_id!r}")
                # Extract callback parameters from request
                response_url = getattr(request, "response_url", None)
                callback_msg_id = getattr(request, "msg_id", None)
                callback_user = getattr(request, "user", None)
                # Unified notification target (e.g. for WeCom WebSocket mode)
                notification_sink_type = getattr(request, "notification_sink_type", None)
                notification_channel = getattr(request, "notification_channel", None)
                notification_chat_id = getattr(request, "notification_chat_id", None)
                async for output in self._handle_slash_command(
                    cleaned_content,
                    exec_user,
                    output_format,
                    source_session_id,
                    response_url=response_url,
                    callback_msg_id=callback_msg_id,
                    callback_user=callback_user,
                    notification_sink_type=notification_sink_type,
                    notification_channel=notification_channel,
                    notification_chat_id=notification_chat_id,
                ):
                    yield output
                return

        # 获取session_id（注意：/chat continue 可能已重写 session_id）
        session_id = request.session_id if request.session_id else "default"
        
        # 检查是否是 inplace 模式（直接在用户指定的目录执行）
        cwd_mode = getattr(request, "cwd_mode", "") or ""
        is_inplace = cwd_mode == "inplace"

        # Resolve execution cwd: request.cwd (if provided) > user_dir
        run_cwd = None
        try:
            run_cwd = getattr(request, "cwd", None)
        except Exception:
            run_cwd = None

        # Resolve execution binding / legacy overrides for the current session.
        binding = None
        exec_dir_override = None
        storage = None
        try:
            from ...runtime.stores.session_storage import get_session_storage
            storage = get_session_storage()
            binding = self._resolve_execution_binding(storage, session_id)
            if binding and getattr(binding, "work_dir", None):
                exec_dir_override = binding.work_dir
            else:
                exec_dir_override = storage.get_exec_dir_override(request.session_id)
            if exec_dir_override:
                logger.info(f"Using exec_dir override: {exec_dir_override}", extra={
                    "session_id": request.session_id,
                    "exec_dir_override": exec_dir_override,
                })
        except Exception as e:
            logger.warning(f"Failed to check exec_dir override: {e}")

        # 对于 inplace 模式，不创建 session 目录，直接使用指定的 cwd
        if exec_dir_override:
            # Use the override directory (from /workspace -t)
            exec_dir = Path(exec_dir_override)
            user_dir = str(exec_dir)
            cwd_mode = "override"
        elif is_inplace and run_cwd:
            exec_dir = Path(str(run_cwd))
            user_dir = str(exec_dir)  # 用于日志记录
        else:
            # 确保用户目录存在
            user_dir = await self.user_dir_manager.ensure_directory(exec_user, request.user, session_id)
            exec_dir = Path(str(run_cwd)) if run_cwd else Path(user_dir)

        if run_cwd:
            # Validate provided cwd
            try:
                if not exec_dir.exists() or not exec_dir.is_dir():
                    raise ValueError(f"cwd 不存在或不是目录: {exec_dir}")
            except Exception as e:
                logger.error(f"Invalid cwd: {e}")
                raise

        logger.info(
            f"Using user directory",
            extra={
                "api_user": request.user,
                "exec_user": exec_user,
                "session_id": session_id,
                "user_dir": str(user_dir),
                "exec_dir": str(exec_dir),
                "cwd_mode": cwd_mode,
            }
        )

        # ── Check session transition flags (needed by both persistent & subprocess) ──
        run_kind = getattr(request, "run_kind", "") or ""
        is_chat_continue = run_kind == "chat_continue"
        model_changed = getattr(request, "model_changed", False)

        session_cleared = False
        exec_user_switched = False
        try:
            if storage and session_id:
                session_cleared = storage.consume_session_cleared(session_id)
                if session_cleared:
                    logger.info(f"Session was recently cleared, will skip resume/continue for session {session_id}")
                exec_user_switched = storage.consume_exec_user_switched(session_id)
                if exec_user_switched:
                    logger.info(f"Session exec_user changed, will rebuild local CLI session for {session_id}")
        except Exception as e:
            logger.warning(f"Failed to check session transition flags: {e}")

        # If a transition occurred, destroy any existing persistent process so
        # a fresh one is created (or we fall through to the subprocess path).
        if (session_cleared or exec_user_switched or model_changed) and self._persistent_manager:
            try:
                await self._persistent_manager.destroy(session_id)
                if storage:
                    storage.clear_persistent_mode(session_id)
                reason = []
                if session_cleared:
                    reason.append("session_cleared")
                if exec_user_switched:
                    reason.append("exec_user_switched")
                if model_changed:
                    reason.append("model_changed")
                logger.info(
                    f"Destroyed persistent process due to transition: {', '.join(reason)}",
                    extra={"session_id": session_id},
                )
            except Exception as e:
                logger.warning(f"Failed to destroy persistent process on transition: {e}")

        # ── Persistent process routing ────────────────────────────────────
        # If persistent mode is enabled and the provider supports it, route
        # through PersistentProcessManager instead of spawning a new subprocess.
        # Skip persistent path if a transition just occurred — the subprocess
        # path handles context injection for model/user switches.
        if (
            not session_cleared
            and not exec_user_switched
            and not model_changed
            and self._should_use_persistent(request, session_id, storage)
        ):
            agent_type = getattr(request, "agent_type", None) or getattr(request, "provider", None)
            request_alias = getattr(request, "alias", None) or None
            request_model_name = getattr(request, "model", None) or None
            provider = (agent_type or "").strip().lower()

            try:
                async for output in self._execute_via_persistent(
                    session_id=session_id,
                    exec_user=exec_user,
                    provider=provider,
                    exec_dir=exec_dir,
                    content=cleaned_content,
                    model=request_model_name,
                    alias=request_alias,
                    output_format=output_format,
                    request=request,
                    storage=storage,
                ):
                    yield output
                return
            except Exception as e:
                logger.warning(
                    f"Persistent process failed, falling back to subprocess: {e}",
                    extra={"session_id": session_id},
                    exc_info=True,
                )
                # Fall through to normal subprocess path

        # 构建命令 - 决定是否使用 -c (continue) 选项
        # - session_cleared：/clear 后的第一次执行，不恢复旧会话
        # - exec_dir_override 模式（/workspace -t）：总是使用 -c，恢复该目录的上下文
        # - inplace 模式的首次执行：不使用 -c，避免恢复到其他目录的会话
        # - inplace 模式的续聊（chat_continue）：使用 -c，继续当前目录的会话
        # - 非 inplace 模式：总是使用 -c
        # - model_changed：模型发生切换时，不使用 -c，因为 CLI 工具在
        #   continue 模式下会锁定原会话的模型，忽略 --model 参数

        # 简化逻辑：exec_dir_override 模式下总是使用 -c 来恢复上下文
        if session_cleared:
            use_continue = False
            logger.info("Skipping -c (continue) due to /clear, will start new CLI session")
        elif exec_user_switched or model_changed:
            use_continue = False
            reason_label = "执行用户切换" if exec_user_switched and not model_changed else "模型切换"
            if exec_user_switched and model_changed:
                reason_label = "执行用户/模型切换"
            logger.info(f"Skipping -c (continue) due to {reason_label}, will start new CLI session")
            # Inject conversation history so the new session has context
            # (without -c, the CLI starts fresh and loses all prior context).
            if session_id:
                try:
                    if not storage:
                        from ...runtime.stores.session_storage import get_session_storage
                        storage = get_session_storage()
                    history_text = self._build_model_switch_context(storage, session_id)
                    if history_text:
                        cleaned_content = (
                            f"[{reason_label} - 以下是之前对话的上下文]\n\n"
                            f"{history_text}\n\n"
                            f"---\n\n"
                            f"请基于以上上下文继续对话。用户的当前请求：\n"
                            f"{cleaned_content}"
                        )
                        logger.info(f"Injected conversation context for {reason_label} ({len(history_text)} chars)")
                except Exception as e:
                    logger.warning(f"Failed to inject {reason_label} context: {e}")
        elif exec_dir_override:
            use_continue = True  # 切换到任务目录后，使用 -c 恢复该目录的上下文
        else:
            use_continue = (not is_inplace) or is_chat_continue

        agent_type = getattr(request, "agent_type", None) or getattr(request, "provider", None)
        if not agent_type and binding and getattr(binding, "provider", None):
            agent_type = binding.provider

        # In /workspace -t mode, override agent_type with the task's provider
        # so that the correct resume mechanism is used (gemini -> --resume latest,
        # codex -> skip -c, claude -> -c).
        workspace_alias = getattr(binding, "alias", None) if binding else None
        if exec_dir_override and not workspace_alias:
            try:
                workspace_provider = getattr(binding, "provider", None) if binding else None
                if not workspace_provider and storage:
                    workspace_provider = storage.get_workspace_provider(request.session_id)
                if workspace_provider:
                    logger.info(f"Overriding agent_type with workspace provider: {agent_type} -> {workspace_provider}")
                    agent_type = workspace_provider
            # Also get the workspace alias for CLI command selection
                if not workspace_alias and storage:
                    workspace_alias = storage.get_workspace_alias(request.session_id)
                if workspace_alias:
                    logger.info(f"Using workspace alias for CLI command: {workspace_alias}")
            except Exception as e:
                logger.warning(f"Failed to get workspace provider/alias: {e}")

        request_alias = getattr(request, "alias", None) or workspace_alias
        request_model_name = getattr(request, "model", None) or None
        request_cli_session_id = getattr(request, "cli_session_id", None) or None
        if not request_cli_session_id and binding and getattr(binding, "cli_session_id", None):
            request_cli_session_id = binding.cli_session_id
        # Fallback: read cli_session_id from session storage (legacy redirect / task workspace)
        if not request_cli_session_id and session_id:
            try:
                if not storage:
                    from ...runtime.stores.session_storage import get_session_storage
                    storage = get_session_storage()

                lookup_session_id = session_id
                if exec_dir_override:
                    target_sid = storage.get_target_session_id(session_id)
                    if target_sid:
                        lookup_session_id = target_sid

                stored_cli_sid = storage.get_cli_session_id(lookup_session_id)
                if stored_cli_sid:
                    request_cli_session_id = stored_cli_sid
                    logger.info(f"Loaded cli_session_id from session storage for {lookup_session_id}: {stored_cli_sid}")
            except Exception as e:
                logger.warning(f"Failed to load cli_session_id from storage: {e}")
        logger.info(f"CLI command decision: request.alias={getattr(request, 'alias', None)}, workspace_alias={workspace_alias}, request_alias={request_alias}, agent_type={agent_type}, model={request_model_name}, cli_session_id={request_cli_session_id}")
        request_image_paths = getattr(request, "image_paths", None) or []
        request_file_paths = getattr(request, "file_paths", None) or []
        request_content_parts = getattr(request, "content_parts", None) or []
        cmd = self._build_command(exec_user, cleaned_content, use_continue=use_continue, agent_type=agent_type, alias=request_alias, model=request_model_name, cli_session_id=request_cli_session_id, image_paths=request_image_paths or None, file_paths=request_file_paths or None, content_parts=request_content_parts or None)

        # 检查当前用户
        current_user = pwd.getpwuid(os.getuid()).pw_name
        cli_cmd_str = ' '.join(shlex.quote(arg) for arg in cmd)
        full_cmd = f"cd {shlex.quote(str(exec_dir))} && {cli_cmd_str}"
        
        if current_user == exec_user:
            cmd = ["bash", "-c", full_cmd]
            logger.info(f"Running command directly as current user", extra={
                "exec_user": exec_user,
                "api_user": request.user,
                "user_dir": str(user_dir),
            })
        else:
            cmd = ["su", "-", exec_user, "-c", full_cmd]
            logger.info(f"Wrapping command with su for exec_user {exec_user}", extra={
                "exec_user": exec_user,
                "api_user": request.user,
                "user_dir": str(user_dir),
            })

        logger.info(f"Starting CLI processing", extra={
            "process_type": "cli_start",
            "api_user": request.user,
            "exec_user": exec_user,
            "content_preview": cleaned_content[:100] if len(cleaned_content) > 100 else cleaned_content,
            "full_cmd": full_cmd,
            "exec_dir": str(exec_dir),
            "cwd_mode": cwd_mode,
            "run_kind": run_kind,
            "use_continue": use_continue,
        })

        # Persist exec_dir into session meta so it's visible in the Runtime list
        if session_id:
            try:
                if not storage:
                    from ...runtime.stores.session_storage import get_session_storage
                    storage = get_session_storage()
                meta = storage.get_session_meta(session_id)
                if meta and not meta.exec_dir:
                    meta.exec_dir = str(exec_dir)
                    storage.save_session_meta(meta)
                # Record the model being used so we can detect changes next time
                if request_model_name:
                    storage.set_active_model(session_id, request_model_name)
            except Exception:
                pass  # best-effort

        try:
            # 创建子进程
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=10 * 1024 * 1024,
            )
            self._current_process = process

            # 处理流式输出
            async for output in self._process_stream(process, request, output_format,
                                                      session_id=session_id, storage=storage):
                yield output

            # 等待进程结束
            await asyncio.wait_for(process.wait(), timeout=self.config.cli_timeout)

            duration = time.time() - start_time
            logger.info(f"CLI processing completed", extra={
                "process_type": "cli_complete",
                "duration_ms": int(duration * 1000),
            })

        except asyncio.TimeoutError:
            logger.error(f"CLI command timeout", extra={"timeout_seconds": self.config.cli_timeout})
            try:
                process.kill()
            except Exception:
                pass
            if output_format == "legacy":
                yield self.format_legacy_error("处理超时，请重试")
            else:
                yield json.dumps({"type": "error", "message": "处理超时，请重试"})

        except Exception as e:
            logger.error(f"Process error: {e}", exc_info=True)
            error_msg = self._format_error_message(str(e), exec_user)
            if output_format == "legacy":
                yield self.format_legacy_error(error_msg)
            else:
                yield json.dumps({"type": "error", "message": error_msg})

    async def _handle_slash_command(
        self,
        content: str,
        exec_user: str,
        output_format: str = "raw",
        source_session_id: Optional[str] = None,
        response_url: Optional[str] = None,
        callback_msg_id: Optional[str] = None,
        callback_user: Optional[str] = None,
        notification_sink_type: Optional[str] = None,
        notification_channel: Optional[str] = None,
        notification_chat_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Handle slash commands and yield formatted response

        Args:
            content: The slash command content
            exec_user: Linux exec user name
            output_format: Output format - "raw" or "legacy"
            source_session_id: Session ID from the source context (for task creation)
            response_url: Callback URL for async task completion notification
            callback_msg_id: Message ID to pass back in callback
            callback_user: User identifier for callback
            notification_sink_type: Unified sink type for task completion (e.g. "wecom").
                                    Takes priority over response_url when set.
            notification_channel: Channel name for unified notification.
            notification_chat_id: Chat/channel ID for unified notification.

        Yields:
            Formatted response strings
        """
        handler = self._get_slash_handler(exec_user)

        try:
            # Get markdown response from handler
            response = handler.handle_command(
                content,
                source_session_id=source_session_id,
                response_url=response_url,
                callback_msg_id=callback_msg_id,
                callback_user=callback_user,
                notification_sink_type=notification_sink_type,
                notification_channel=notification_channel,
                notification_chat_id=notification_chat_id,
            )
            
            logger.info(f"Slash command handled", extra={
                "command": content.split()[0] if content else "",
                "exec_user": exec_user,
                "response_length": len(response),
            })
            
            if output_format == "legacy":
                # For legacy format, send as SSE
                yield self.format_legacy_sse(response, finished=True)
            else:
                # For raw format, create a simple result event
                yield json.dumps({
                    "type": "result",
                    "subtype": "slash_command",
                    "content": response,
                })
                
        except Exception as e:
            logger.error(f"Slash command error: {e}", exc_info=True)
            error_msg = f"命令执行错误: {str(e)}"
            if output_format == "legacy":
                yield self.format_legacy_error(error_msg)
            else:
                yield json.dumps({"type": "error", "message": error_msg})

    async def _process_stream(
        self,
        process: asyncio.subprocess.Process,
        request: RequestModel,
        output_format: str = "raw",
        session_id: Optional[str] = None,
        storage=None,
    ) -> AsyncGenerator[str, None]:
        """处理子进程的流式输出"""
        line_count = 0
        tool_input_buffer: Dict[int, str] = {}
        
        debug_file = None
        if DEBUG_STREAM:
            try:
                # 确保目标目录存在，使用安全权限打开文件（仅 owner 可读写）
                os.makedirs(os.path.dirname(DEBUG_STREAM_FILE), exist_ok=True)
                fd = os.open(DEBUG_STREAM_FILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                debug_file = os.fdopen(fd, "a", encoding="utf-8")
                debug_file.write(f"\n\n=== New Stream Session: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            except Exception as e:
                logger.warning(f"Failed to open debug stream file: {e}")

        try:
            while True:
                try:
                    line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=self.config.cli_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.error(
                        "Stream read timeout",
                        extra={"timeout_seconds": self.config.cli_timeout},
                    )
                    try:
                        process.kill()
                    except Exception:
                        pass
                    raise

                if not line:
                    break

                line_count += 1
                try:
                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        continue
                    
                    if debug_file:
                        debug_file.write(f"[{line_count}] {line_str}\n")
                        debug_file.flush()

                    # Extract and persist CLI session ID from result events (subprocess path)
                    try:
                        _data = json.loads(line_str)
                        if _data.get("type") == "result":
                            _cli_sid = _data.get("session_id")
                            if _cli_sid and session_id and storage:
                                try:
                                    storage.set_cli_session_id(session_id, _cli_sid)
                                    logger.debug(f"Saved cli_session_id from subprocess result: {_cli_sid}")
                                except Exception:
                                    pass
                    except (json.JSONDecodeError, TypeError):
                        pass

                    # 原始JSON行模式
                    if output_format == "raw":
                        yield line_str
                        continue

                    # 易事厅格式处理
                    data = json.loads(line_str)
                    event_type = data.get("type")
                    
                    for sse in self._process_legacy_event(data, event_type, tool_input_buffer):
                        yield sse

                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON line #{line_count}: {line_str[:100]}...")
                except Exception as e:
                    logger.error(f"Error processing stream line #{line_count}: {e}", exc_info=True)
                    if output_format == "legacy":
                        yield self.format_legacy_sse(f"处理流事件时出错: {str(e)}", finished=False)

            logger.info(f"Stream processing completed, total lines: {line_count}")

            # Invalidate history caches so the History UI immediately reflects
            # updated file timestamps from this CLI execution.
            try:
                removed = HistoryService.invalidate_project_caches_across_instances()
                if removed:
                    logger.info(f"Invalidated {removed} history cache entries after CLI execution")
            except Exception:
                pass  # best-effort

            if process.stderr:
                try:
                    stderr_data = await process.stderr.read()
                    # 测试里 stderr 可能是 AsyncMock，读出来不是 bytes；这里做兼容处理
                    if asyncio.iscoroutine(stderr_data):
                        stderr_data = await stderr_data
                    if isinstance(stderr_data, (bytes, bytearray)) and stderr_data:
                        stderr_str = stderr_data.decode('utf-8', errors='ignore')[:1000]
                        logger.warning(f"CLI stderr: {stderr_str}")
                        if debug_file:
                            debug_file.write(f"\n=== STDERR ===\n{stderr_str}\n")
                except Exception:
                    pass
        finally:
            if debug_file:
                debug_file.write(f"\n=== Stream End: {line_count} lines ===\n")
                debug_file.close()

    def _process_legacy_event(self, data: Dict[str, Any], event_type: str, tool_input_buffer: Dict[int, str]) -> List[str]:
        """处理 Legacy 格式的事件"""
        results = []
        
        if event_type == "result":
            pass
        
        elif event_type == "stream_event":
            formatted_text = self._format_stream_event_legacy(data, tool_input_buffer)
            if formatted_text:
                results.append(self.format_legacy_sse(formatted_text, finished=False))
        
        elif event_type == "user":
            formatted_text = self._format_user_message_legacy(data)
            if formatted_text:
                results.append(self.format_legacy_sse(formatted_text, finished=False))
        
        return results

    def _format_stream_event_legacy(self, data: Dict[str, Any], tool_input_buffer: Dict[int, str]) -> str:
        """格式化 stream_event 类型的数据（易事厅格式）"""
        event = data.get("event", {})
        event_type = event.get("type")
        
        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            delta_type = delta.get("type")
            
            if delta_type == "text_delta":
                text = delta.get("text", "")
                return self._sanitize_text(text)
            
            elif delta_type == "input_json_delta":
                index = event.get("index", 0)
                partial_json = delta.get("partial_json", "")
                if index not in tool_input_buffer:
                    tool_input_buffer[index] = ""
                tool_input_buffer[index] += partial_json
        
        elif event_type == "content_block_start":
            content_block = event.get("content_block", {})
            block_type = content_block.get("type")
            
            if block_type == "tool_use":
                tool_name = content_block.get("name", "unknown")
                return f"\n🔧 **调用工具: {tool_name}**\n"
        
        elif event_type == "content_block_stop":
            index = event.get("index", 0)
            if index in tool_input_buffer:
                params = tool_input_buffer.pop(index)
                if params:
                    try:
                        params_obj = json.loads(params)
                        if isinstance(params_obj, dict):
                            key_params = []
                            for key in ["command", "pattern", "path", "filePath", "content", "description"]:
                                if key in params_obj:
                                    val = params_obj[key]
                                    if isinstance(val, str) and len(val) > 100:
                                        val = val[:100] + "..."
                                    key_params.append(f"{key}: {val}")
                            if key_params:
                                return f"参数: {', '.join(key_params[:3])}\n"
                    except json.JSONDecodeError:
                        pass
        
        return ""

    def _format_user_message_legacy(self, data: Dict[str, Any]) -> str:
        """格式化 user 消息（工具结果）（Legacy 格式）"""
        message = data.get("message", {})
        content = message.get("content", [])
        
        results = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                result_content = item.get("content", "")
                is_error = item.get("is_error", False)
                
                if isinstance(result_content, list):
                    text_parts = []
                    for rc in result_content:
                        if isinstance(rc, dict) and rc.get("type") == "text":
                            text_parts.append(rc.get("text", "")[:500])
                        elif isinstance(rc, str):
                            text_parts.append(rc[:500])
                    result_content = "\n".join(text_parts)
                elif isinstance(result_content, str):
                    result_content = result_content[:500]
                else:
                    result_content = str(result_content)[:500]
                
                if is_error:
                    results.append(f"❌ **错误**: {result_content}\n")
                else:
                    results.append(f"✅ **结果**: {result_content}\n")
        
        return "".join(results)

    @staticmethod
    def _build_model_switch_context(
        storage,
        session_id: str,
        max_messages: int = 50,
        truncate_each: int = 800,
    ) -> str:
        """Build a condensed conversation history for model-switch context injection.

        When a model switch forces a new CLI session (no ``-c``), we prepend
        recent conversation history so the new session is not completely blank.
        Uses the same Redis messages that ``/switch -r -a`` would use.
        """
        try:
            messages = storage.get_session_messages(session_id)
            if not messages:
                return ""

            selected = messages[-max_messages:] if max_messages and max_messages > 0 else messages

            parts: list[str] = []
            for msg in selected:
                role_label = {"user": "用户", "assistant": "助手"}.get(msg.role, msg.role)
                content = (msg.content or "").strip()
                if not content:
                    continue
                if truncate_each and truncate_each > 0 and len(content) > truncate_each:
                    content = content[:truncate_each] + "…(截断)"
                parts.append(f"[{role_label}] {content}")

            return "\n\n".join(parts) if parts else ""
        except Exception as e:
            logger.warning(f"Failed to build model switch context: {e}")
            return ""

    def _clean_content(self, content: str) -> str:
        """清理输入内容"""
        triggers_to_remove = []
        cleaned = content
        
        for trigger in triggers_to_remove:
            if trigger in cleaned:
                cleaned = cleaned.replace(trigger, '')

        cleaned = cleaned.strip()
        while cleaned.startswith('\n'):
            cleaned = cleaned[1:].strip()

        return cleaned

    def _check_for_admin_command(self, content: str) -> bool:
        """检查是否包含管理员命令"""
        admin_commands = ["/clear"]
        return any(cmd in content for cmd in admin_commands)

    def _parse_model_param(self, content: str) -> tuple:
        """解析content中的--model参数"""
        model_pattern = r'--model\s+([^\s]+(?:\s*,\s*[^\s,]+)*)'
        match = re.search(model_pattern, content)
        
        if match:
            model_value = match.group(1).strip()
            cleaned_content = re.sub(model_pattern, '', content).strip()
            cleaned_content = re.sub(r'\s+', ' ', cleaned_content).strip()
            return cleaned_content, model_value
        
        return content, None

    def _should_use_persistent(
        self,
        request: RequestModel,
        session_id: str,
        storage=None,
    ) -> bool:
        """Decide whether to route this request through the persistent process path.

        Decision logic (in priority order):
            1. Global toggle ``persistent_enabled`` must be True.
            2. Per-request override: ``request.use_persistent`` (True/False) wins.
            3. Session stickiness: if the session previously used persistent mode
               (stored in Redis), continue using it.
            4. Provider must support ``--input-format stream-json``
               (currently claude, codebuddy).
            5. Default: False (keep subprocess behaviour).
        """
        # 1. Global toggle
        if not self._persistent_manager:
            return False

        # 2. Per-request override
        req_persistent = getattr(request, "use_persistent", None)
        if req_persistent is True:
            return True
        if req_persistent is False:
            return False

        # 3. Session stickiness
        if storage and session_id:
            try:
                if storage.get_persistent_mode(session_id):
                    return True
            except Exception:
                pass

        # 4. Provider check — only activate for supported providers
        provider = (
            getattr(request, "agent_type", None)
            or getattr(request, "provider", None)
            or ""
        )
        if not PersistentProcessManager.supports_persistent(provider):
            return False

        # 5. Default off
        return False

    async def _execute_via_persistent(
        self,
        session_id: str,
        exec_user: str,
        provider: str,
        exec_dir: Path,
        content: str,
        model: Optional[str] = None,
        alias: Optional[str] = None,
        output_format: str = "raw",
        request: Optional[RequestModel] = None,
        storage=None,
    ) -> AsyncGenerator[str, None]:
        """Execute a user message through the persistent CLI process.

        Creates or reuses a long-lived CLI subprocess and sends the message
        via stdin pipe (stream-json).  Yields output lines compatible with
        ``_process_stream()`` / raw JSON mode.

        On failure, raises an exception so the caller can fall back to the
        normal subprocess path.
        """
        assert self._persistent_manager is not None

        start_time = time.time()

        logger.info(
            "Routing through persistent process",
            extra={
                "session_id": session_id,
                "provider": provider,
                "exec_dir": str(exec_dir),
            },
        )

        proc = await self._persistent_manager.get_or_create(
            session_id=session_id,
            exec_user=exec_user,
            provider=provider,
            exec_dir=exec_dir,
            model=model,
            alias=alias,
        )

        # Mark session as using persistent mode for stickiness
        if storage:
            try:
                storage.set_persistent_mode(session_id, True)
            except Exception:
                pass

        # Send the user message
        await proc.send_message(content)

        # Read output and yield lines
        turn_timeout = float(getattr(self.config, "cli_timeout", 600))
        quiescence = float(getattr(self.config, "persistent_quiescence_timeout", 3.0))

        line_count = 0
        debug_file = None
        if DEBUG_STREAM:
            try:
                os.makedirs(os.path.dirname(DEBUG_STREAM_FILE), exist_ok=True)
                fd = os.open(DEBUG_STREAM_FILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                debug_file = os.fdopen(fd, "a", encoding="utf-8")
                debug_file.write(f"\n\n=== Persistent Stream: {time.strftime('%Y-%m-%d %H:%M:%S')} session={session_id} ===\n")
            except Exception:
                pass

        try:
            async for raw_line in proc.stream_output(
                timeout=turn_timeout,
                quiescence_timeout=quiescence,
            ):
                line_count += 1

                if debug_file:
                    try:
                        debug_file.write(f"[{line_count}] {raw_line}\n")
                        debug_file.flush()
                    except Exception:
                        pass

                # Extract and persist CLI session ID from result events
                try:
                    data = json.loads(raw_line)
                    if data.get("type") == "result":
                        cli_sid = data.get("session_id")
                        if cli_sid and storage:
                            storage.set_cli_session_id(session_id, cli_sid)
                except (json.JSONDecodeError, TypeError):
                    pass

                if output_format == "raw":
                    yield raw_line
                else:
                    # Legacy format
                    try:
                        data = json.loads(raw_line)
                        event_type = data.get("type")
                        for sse in self._process_legacy_event(data, event_type, {}):
                            yield sse
                    except (json.JSONDecodeError, TypeError):
                        pass

        finally:
            if debug_file:
                debug_file.write(f"\n=== Persistent Stream End: {line_count} lines ===\n")
                debug_file.close()

        # Also persist CLI session ID if the detector found one
        if proc.cli_session_id and storage:
            try:
                storage.set_cli_session_id(session_id, proc.cli_session_id)
            except Exception:
                pass

        # Persist exec_dir into session meta
        if session_id and storage:
            try:
                meta = storage.get_session_meta(session_id)
                if meta and not meta.exec_dir:
                    meta.exec_dir = str(exec_dir)
                    storage.save_session_meta(meta)
                if model:
                    storage.set_active_model(session_id, model)
            except Exception:
                pass

        # Invalidate history caches
        try:
            HistoryService.invalidate_project_caches_across_instances()
        except Exception:
            pass

        duration = time.time() - start_time
        logger.info(
            "Persistent process turn completed",
            extra={
                "session_id": session_id,
                "lines": line_count,
                "duration_ms": int(duration * 1000),
            },
        )

    def _build_command(
        self,
        exec_user: str,
        content: str,
        use_continue: bool = True,
        agent_type: Optional[str] = None,
        alias: Optional[str] = None,
        model: Optional[str] = None,
        cli_session_id: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        file_paths: Optional[List[str]] = None,
        content_parts: Optional[list] = None,
    ) -> List[str]:
        """构建 CLI 命令

        Args:
            exec_user: Linux exec user
            content: 用户消息内容
            use_continue: 是否使用 -c (continue) 选项，默认为 True
            agent_type: Agent类型（如 claude / codex）决定参数格式
            alias: CLI 命令名覆盖（如 claude-internal），不影响参数格式
            model: Explicit LLM model name override. Inline --model in content takes priority.
            cli_session_id: Specific CLI session UUID for precise resume.
                Provider-specific: claude/gemini use --resume, codebuddy uses -r,
                codex uses resume SESSION_ID.
            image_paths: Local image file paths to inject into the prompt.
            file_paths: Local file paths (non-image) to inject into the prompt.
            content_parts: Ordered list of content parts preserving text/image interleaving.
        """
        cleaned_content, inline_model = self._parse_model_param(content)
        model_param = inline_model or model or None
        cli_session_id = (cli_session_id or "").strip() or None
        provider = (agent_type or "").strip().lower()
        is_codebuddy_provider = provider == "codebuddy" or provider.startswith("codebuddy-")
        provider_command_map = {
            "claude": "claude",
            "codex": "codex",
            "gemini": "gemini",
            "codebuddy": "codebuddy",
        }

        # Determine CLI command name: alias overrides provider_command_map
        cli_alias = (alias or "").strip().lower()
        if cli_alias:
            cli_command = cli_alias
        elif provider in provider_command_map:
            cli_command = provider_command_map[provider]
        else:
            cli_command = self.config.agent_cli_command_map.get(exec_user, self.config.cli_command)

        cmd = [cli_command]

        if cli_command == "ccr":
            cmd.append("code")

        is_codex = provider == "codex"
        is_gemini = provider == "gemini"

        if cleaned_content.lower() == "/clear":
            message = "你好"
        else:
            message = cleaned_content

        # Inject image/file paths into the prompt.
        # Prefer content_parts (preserves original interleaving order).
        if content_parts:
            assembled: list[str] = []
            for part in content_parts:
                if part.get("type") == "image":
                    p = part.get("path") or part.get("url", "")
                    assembled.append(f"{{image: {p}}}")
                elif part.get("type") == "text":
                    assembled.append(part.get("content", ""))
                elif part.get("type") == "file":
                    p = part.get("path") or part.get("url", "")
                    assembled.append(f"{{file: {p}}}")
            message = "\n".join(assembled)
        else:
            # Fallback: flat image_paths/file_paths (all images before text)
            if image_paths:
                tags = " ".join(f"{{image: {p}}}" for p in image_paths)
                if message.strip():
                    message = f"{tags}\n\n{message}"
                else:
                    message = tags

            if file_paths:
                tags = " ".join(f"{{file: {p}}}" for p in file_paths)
                if message.strip():
                    message = f"{tags}\n\n{message}"
                else:
                    message = tags

        # Provider-aware continue/resume logic:
        # When cli_session_id is available, use precise session resume:
        #   - claude: --resume SESSION_ID (instead of -c which is "latest")
        #   - codebuddy: -r SESSION_ID (instead of -c)
        #   - gemini: --resume SESSION_ID (instead of --resume latest)
        #   - codex: resume SESSION_ID (instead of resume --last)
        # Fallback to generic "latest" resume when no specific session ID.
        if use_continue and cleaned_content.lower() != "/clear":
            if is_codex:
                pass  # codex uses "resume ..." appended after prompt
            elif is_gemini:
                if cli_session_id:
                    cmd.extend(["--resume", cli_session_id])
                else:
                    cmd.extend(["--resume", "latest"])
            elif is_codebuddy_provider:
                if cli_session_id:
                    cmd.extend(["-r", cli_session_id])
                else:
                    cmd.extend(["-c"])
            else:
                # claude
                if cli_session_id:
                    cmd.extend(["--resume", cli_session_id])
                else:
                    cmd.extend(["-c"])

        # Provider-specific command assembly.
        #
        # CLI semantics differ significantly:
        #   - claude / codebuddy:
        #       -p is a boolean flag (--print), prompt is positional
        #       flags: --output-format stream-json --include-partial-messages --verbose
        #       safety: --dangerously-skip-permissions
        #   - gemini:
        #       -p/--prompt is a [string] option — MUST be immediately followed by
        #       the prompt text (e.g. -p "hello").  Other flags must NOT sit between
        #       -p and the prompt.
        #       flags: --output-format stream-json (ONLY)
        #       no: --include-partial-messages, --verbose, --dangerously-skip-permissions
        #   - codex:
        #       -p is --profile (disabled), NOT print/prompt.
        #       prompt is positional [PROMPT].  No --output-format, --verbose, etc.
        #       safety: --dangerously-bypass-approvals-and-sandbox

        is_claude = provider == "claude"
        is_codebuddy = is_codebuddy_provider

        if is_codex:
            if model_param:
                cmd.extend(["--model", model_param])
            cmd.extend([message, "--dangerously-bypass-approvals-and-sandbox"])
            # For codex in continue mode, append "resume SESSION_ID" or "resume --last"
            if use_continue and cleaned_content.lower() != "/clear":
                if cli_session_id:
                    cmd.extend(["resume", cli_session_id])
                else:
                    cmd.extend(["resume", "--last"])
        elif is_gemini:
            # Gemini: -p <prompt>, --output-format stream-json only
            cmd.extend(["--output-format", "stream-json"])
            if model_param:
                cmd.extend(["--model", model_param])
            cmd.extend(["-p", message])
        elif is_claude or is_codebuddy:
            # Claude/CodeBuddy: full flag set
            cmd.extend([
                "--output-format", "stream-json",
                "--include-partial-messages",
                "--verbose",
            ])
            if model_param:
                cmd.extend(["--model", model_param])
            cmd.extend(["-p", message, "--dangerously-skip-permissions"])
        else:
            # Unknown provider — fall back to Claude-style, log warning
            logger.warning(f"Unknown provider '{provider}', using Claude-style CLI args")
            cmd.extend([
                "--output-format", "stream-json",
                "--include-partial-messages",
                "--verbose",
            ])
            if model_param:
                cmd.extend(["--model", model_param])
            cmd.extend(["-p", message, "--dangerously-skip-permissions"])

        return cmd

    def _sanitize_text(self, text: str) -> str:
        """Legacy SSE 下保留原始文本（包含 <think> 标签）。"""
        return text

    def _format_error_message(self, error: str, exec_user: str) -> str:
        """格式化错误消息"""
        if "su:" in error:
            return f"无法切换到用户 '{exec_user}'。请确保用户存在且当前进程有切换权限。"
        elif "cannot create child process" in error.lower():
            return f"无法创建子进程。可能是权限不足或资源限制。"
        return f"处理错误: {error}"

    def format_legacy_sse(self, response: str, finished: bool = False, answer_success: int = 1) -> str:
        """格式化为 Legacy SSE 格式"""
        data = {
            "response": response,
            "finished": finished,
            "global_output": {
                "context": "",
                "answer_success": answer_success,
                "docs": [],
            },
        }
        json_data = json.dumps(data, ensure_ascii=False)
        return f"event:delta\ndata:{json_data}\n\n"

    def format_legacy_error(self, error_msg: str) -> str:
        """发送 Legacy 格式的错误消息"""
        return self.format_legacy_sse(error_msg, finished=True, answer_success=0)

# -*- coding: utf-8 -*-
"""CCR Command Executor Service

Responsibilities:
- Build and execute CCR commands
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
from pathlib import Path
from typing import AsyncGenerator, List, Dict, Any, Optional

from src.providers.claude_code_api.models import RequestModel
from src.providers.claude_code_api.models.agui_events import (
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

logger = get_logger(__name__)

# Debug模式：将完整的stream-json输出保存到文件
DEBUG_STREAM = os.environ.get("DEBUG_STREAM", "0") == "1"
DEBUG_STREAM_FILE = os.environ.get("DEBUG_STREAM_FILE", "/tmp/debug_stream.jsonl")


class CCRExecutor:
    """CCR 命令执行器"""

    def __init__(self, config=None):
        self.config = config or settings
        self.user_dir_manager = UserDirectoryManager(config)
        self._slash_handlers: Dict[str, SlashCommandHandler] = {}

    def _get_slash_handler(self, agent_name: str) -> SlashCommandHandler:
        """Get or create slash command handler for agent"""
        if agent_name not in self._slash_handlers:
            self._slash_handlers[agent_name] = SlashCommandHandler(agent_name, self.config)
        return self._slash_handlers[agent_name]

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
        agent_name: str,
        output_format: str = "raw"
    ) -> AsyncGenerator[str, None]:
        """
        执行 CCR 命令并生成流式输出

        Args:
            request: 请求模型
            agent_name: Linux系统用户名
            output_format: 输出格式 - "raw"(原始JSON行), "legacy"(易事厅格式)

        Yields:
            原始JSON行或格式化的SSE
        """
        start_time = time.time()

        # 验证用户参数
        if not request.user:
            logger.error(f"Missing required user parameter", extra={"agent_name": agent_name})
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
                user_dir = await self.user_dir_manager.ensure_directory(agent_name, request.user, session_id)
                await self.user_dir_manager.clear_directory(agent_name, request.user, user_dir, session_id)
                await self.user_dir_manager.ensure_directory(agent_name, request.user, session_id)
                yield _format_slash_result(
                    "## 🔄 Session Cleared\n\nYour session has been cleared. A fresh workspace has been created.",
                    is_error=False,
                )
                return

            # Other slash commands: handled locally
            else:
                source_session_id = request.session_id if request.session_id else None
                logger.info(f"Slash command: request.session_id={request.session_id!r}, source_session_id={source_session_id!r}")
                async for output in self._handle_slash_command(
                    cleaned_content, agent_name, output_format, source_session_id
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

        # 对于 inplace 模式，不创建 session 目录，直接使用指定的 cwd
        if is_inplace and run_cwd:
            exec_dir = Path(str(run_cwd))
            user_dir = str(exec_dir)  # 用于日志记录
        else:
            # 确保用户目录存在
            user_dir = await self.user_dir_manager.ensure_directory(agent_name, request.user, session_id)
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
                "agent_name": agent_name,
                "session_id": session_id,
                "user_dir": str(user_dir),
                "exec_dir": str(exec_dir),
                "cwd_mode": cwd_mode,
            }
        )

        # 构建命令 - 决定是否使用 -c (continue) 选项
        # - inplace 模式的首次执行：不使用 -c，避免恢复到其他目录的会话
        # - inplace 模式的续聊（chat_continue）：使用 -c，继续当前目录的会话
        # - 非 inplace 模式：总是使用 -c
        run_kind = getattr(request, "run_kind", "") or ""
        is_chat_continue = run_kind == "chat_continue"
        use_continue = (not is_inplace) or is_chat_continue
        cmd = self._build_command(agent_name, cleaned_content, use_continue=use_continue)

        # 检查当前用户
        current_user = pwd.getpwuid(os.getuid()).pw_name
        ccr_cmd_str = ' '.join(shlex.quote(arg) for arg in cmd)
        full_cmd = f"cd {shlex.quote(str(exec_dir))} && {ccr_cmd_str}"
        
        if current_user == agent_name:
            cmd = ["bash", "-c", full_cmd]
            logger.info(f"Running command directly as current user", extra={
                "agent_name": agent_name,
                "api_user": request.user,
                "user_dir": str(user_dir),
            })
        else:
            cmd = ["su", "-", agent_name, "-c", full_cmd]
            logger.info(f"Wrapping command with su for agent {agent_name}", extra={
                "agent_name": agent_name,
                "api_user": request.user,
                "user_dir": str(user_dir),
            })

        logger.info(f"Starting CCR processing", extra={
            "process_type": "ccr_start",
            "api_user": request.user,
            "agent_name": agent_name,
            "content_preview": cleaned_content[:100] if len(cleaned_content) > 100 else cleaned_content,
            "full_cmd": full_cmd,
            "exec_dir": str(exec_dir),
            "cwd_mode": cwd_mode,
            "run_kind": run_kind,
            "use_continue": use_continue,
        })

        try:
            # 创建子进程
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=10 * 1024 * 1024,
            )

            # 处理流式输出
            async for output in self._process_stream(process, request, output_format):
                yield output

            # 等待进程结束
            await asyncio.wait_for(process.wait(), timeout=self.config.ccr_timeout)

            duration = time.time() - start_time
            logger.info(f"CCR processing completed", extra={
                "process_type": "ccr_complete",
                "duration_ms": int(duration * 1000),
            })

        except asyncio.TimeoutError:
            logger.error(f"CCR command timeout", extra={"timeout_seconds": self.config.ccr_timeout})
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
            error_msg = self._format_error_message(str(e), agent_name)
            if output_format == "legacy":
                yield self.format_legacy_error(error_msg)
            else:
                yield json.dumps({"type": "error", "message": error_msg})

    async def _handle_slash_command(
        self,
        content: str,
        agent_name: str,
        output_format: str = "raw",
        source_session_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Handle slash commands and yield formatted response
        
        Args:
            content: The slash command content
            agent_name: Linux agent user name
            output_format: Output format - "raw" or "legacy"
            source_session_id: Session ID from the source context (for task creation)
            
        Yields:
            Formatted response strings
        """
        handler = self._get_slash_handler(agent_name)
        
        try:
            # Get markdown response from handler
            response = handler.handle_command(content, source_session_id=source_session_id)
            
            logger.info(f"Slash command handled", extra={
                "command": content.split()[0] if content else "",
                "agent_name": agent_name,
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
        output_format: str = "raw"
    ) -> AsyncGenerator[str, None]:
        """处理子进程的流式输出"""
        line_count = 0
        tool_input_buffer: Dict[int, str] = {}
        
        debug_file = None
        if DEBUG_STREAM:
            try:
                debug_file = open(DEBUG_STREAM_FILE, "a", encoding="utf-8")
                debug_file.write(f"\n\n=== New Stream Session: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            except Exception as e:
                logger.warning(f"Failed to open debug stream file: {e}")

        try:
            while True:
                try:
                    line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=self.config.ccr_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.error(
                        "Stream read timeout",
                        extra={"timeout_seconds": self.config.ccr_timeout},
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

            if process.stderr:
                try:
                    stderr_data = await process.stderr.read()
                    # 测试里 stderr 可能是 AsyncMock，读出来不是 bytes；这里做兼容处理
                    if asyncio.iscoroutine(stderr_data):
                        stderr_data = await stderr_data
                    if isinstance(stderr_data, (bytes, bytearray)) and stderr_data:
                        stderr_str = stderr_data.decode('utf-8', errors='ignore')[:1000]
                        logger.warning(f"CCR stderr: {stderr_str}")
                        if debug_file:
                            debug_file.write(f"\n=== STDERR ===\n{stderr_str}\n")
                except Exception:
                    pass
        finally:
            if debug_file:
                debug_file.write(f"\n=== Stream End: {line_count} lines ===\n")
                debug_file.close()

    def _process_legacy_event(self, data: Dict[str, Any], event_type: str, tool_input_buffer: Dict[int, str]) -> List[str]:
        """处理易事厅格式的事件"""
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
        """格式化 user 消息（工具结果）（易事厅格式）"""
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

    def _build_command(self, agent_name: str, content: str, use_continue: bool = True) -> List[str]:
        """构建CCR命令
        
        Args:
            agent_name: Agent用户名
            content: 用户消息内容
            use_continue: 是否使用 -c (continue) 选项，默认为 True
        """
        cleaned_content, model_param = self._parse_model_param(content)
        ccr_command = self.config.agent_ccr_command_map.get(agent_name, self.config.ccr_command)
        
        cmd = [ccr_command]
        
        if ccr_command == "ccr":
            cmd.append("code")
        
        if cleaned_content.lower() == "/clear":
            cmd.extend(["-p"])
            message = "你好"
        else:
            if use_continue:
                cmd.extend(["-c", "-p"])
            else:
                cmd.extend(["-p"])
            message = cleaned_content
        
        cmd.extend([
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
        ])
        
        if model_param:
            cmd.extend(["--model", model_param])
        
        cmd.extend([message, "--dangerously-skip-permissions"])
        
        return cmd

    def _sanitize_text(self, text: str) -> str:
        """Legacy SSE 下保留原始文本（包含 <think> 标签）。"""
        return text

    def _format_error_message(self, error: str, agent_name: str) -> str:
        """格式化错误消息"""
        if "su:" in error:
            return f"无法切换到用户 '{agent_name}'。请确保用户存在且当前进程有切换权限。"
        elif "cannot create child process" in error.lower():
            return f"无法创建子进程。可能是权限不足或资源限制。"
        return f"处理错误: {error}"

    def format_legacy_sse(self, response: str, finished: bool = False, answer_success: int = 1) -> str:
        """格式化为易事厅 SSE 格式"""
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
        """发送易事厅格式的错误消息"""
        return self.format_legacy_sse(error_msg, finished=True, answer_success=0)

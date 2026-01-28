# -*- coding: utf-8 -*-
"""CCR (Claude Code Runner) Executor

This executor runs the CCR/Claude CLI as a subprocess.

IMPORTANT: This module is part of agent_runtime and must NOT depend on
claude_code_api or server layers. API-specific logic (like slash command 
handlers) should be injected via callbacks or kept in the API layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pwd
import re
import shlex
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Callable, Awaitable

from .base import BaseExecutor, ExecutorConfig, RequestContext

logger = logging.getLogger(__name__)

# Debug mode: save full stream-json output to file
DEBUG_STREAM = os.environ.get("DEBUG_STREAM", "0") == "1"
DEBUG_STREAM_FILE = os.environ.get("DEBUG_STREAM_FILE", "/tmp/debug_stream.jsonl")


# Type for slash command handler callback
SlashCommandCallback = Callable[[str, Optional[str]], Awaitable[str]]


class CCRExecutorConfig(ExecutorConfig):
    """CCR-specific configuration."""
    
    def __init__(
        self,
        timeout: float = 120.0,
        user_home_base: str = "/home",
        ccr_command: str = "ccr",
        agent_ccr_command_map: Optional[Dict[str, str]] = None,
        **kwargs,
    ):
        super().__init__(timeout=timeout, user_home_base=user_home_base)
        self.ccr_command = ccr_command
        self.agent_ccr_command_map = agent_ccr_command_map or {}
        self.extra.update(kwargs)


class CCRExecutor(BaseExecutor):
    """CCR command executor.
    
    Runs Claude Code Runner CLI and yields stream output.
    """
    
    def __init__(
        self,
        config: Optional[CCRExecutorConfig] = None,
        slash_command_handler: Optional[SlashCommandCallback] = None,
        user_dir_manager: Optional[Any] = None,
    ):
        """Initialize CCR executor.
        
        Args:
            config: CCR configuration
            slash_command_handler: Optional callback for handling slash commands
            user_dir_manager: Optional UserDirectoryManager instance
        """
        super().__init__(config or CCRExecutorConfig())
        self._slash_command_handler = slash_command_handler
        self._user_dir_manager = user_dir_manager
    
    @property
    def ccr_config(self) -> CCRExecutorConfig:
        """Get CCR-specific config."""
        return self.config  # type: ignore
    
    async def execute(
        self,
        context: RequestContext,
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Execute CCR command and yield stream output.
        
        Args:
            context: Request context
            output_format: "raw" (JSON lines) or "legacy" (event:delta SSE)
            
        Yields:
            Output lines
        """
        start_time = time.time()
        
        # Validate user
        if not context.user or context.user == "anonymous":
            logger.error("Missing required user parameter")
            raise ValueError("用户名参数是必需的")
        
        # Clean content
        cleaned_content = self._clean_content(context.content)
        
        # Helper for slash command results
        def _format_slash_result(text: str, is_error: bool = False) -> str:
            if output_format == "legacy":
                return self.format_legacy_sse(text, finished=True, answer_success=0 if is_error else 1)
            return json.dumps({
                "type": "result",
                "subtype": "slash_command",
                "content": text,
            })
        
        # Check removed commands
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
        
        # Check slash commands
        if self._is_slash_command(cleaned_content):
            if self._slash_command_handler:
                async for output in self._handle_slash_command(
                    cleaned_content, context, output_format
                ):
                    yield output
                return
            else:
                # No handler available, pass through
                logger.warning("Slash command received but no handler configured")
        
        # Resolve execution directory
        exec_dir = await self._resolve_exec_dir(context)
        
        # Build command
        is_inplace = context.cwd_mode == "inplace"
        is_chat_continue = context.run_kind == "chat_continue"
        use_continue = (not is_inplace) or is_chat_continue
        cmd = self._build_command(context, use_continue=use_continue)
        
        # Wrap with user switching if needed
        final_cmd = self.wrap_command_for_user(cmd, exec_dir, context.agent_name)
        
        logger.info(
            f"Starting CCR processing",
            extra={
                "process_type": "ccr_start",
                "api_user": context.user,
                "agent_name": context.agent_name,
                "content_preview": cleaned_content[:100] if len(cleaned_content) > 100 else cleaned_content,
                "exec_dir": str(exec_dir),
                "cwd_mode": context.cwd_mode,
                "run_kind": context.run_kind,
                "use_continue": use_continue,
            }
        )
        
        try:
            process = await self.run_subprocess(final_cmd)
            
            async for output in self._process_stream(process, output_format):
                yield output
            
            await asyncio.wait_for(process.wait(), timeout=self.config.timeout)
            
            duration = time.time() - start_time
            logger.info(f"CCR processing completed", extra={
                "process_type": "ccr_complete",
                "duration_ms": int(duration * 1000),
            })
            
        except asyncio.TimeoutError:
            logger.error(f"CCR command timeout", extra={"timeout_seconds": self.config.timeout})
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
            error_msg = self._format_error_message(str(e), context.agent_name)
            if output_format == "legacy":
                yield self.format_legacy_error(error_msg)
            else:
                yield json.dumps({"type": "error", "message": error_msg})
    
    def _build_command(self, context: RequestContext, use_continue: bool = True) -> List[str]:
        """Build CCR command."""
        cleaned_content, model_param = self._parse_model_param(context.content)
        
        ccr_command = self.ccr_config.agent_ccr_command_map.get(
            context.agent_name, 
            self.ccr_config.ccr_command
        )
        
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
    
    async def _resolve_exec_dir(self, context: RequestContext) -> Path:
        """Resolve execution directory with user directory management."""
        is_inplace = context.cwd_mode == "inplace"
        
        if is_inplace and context.cwd:
            exec_dir = Path(str(context.cwd))
            if not exec_dir.exists() or not exec_dir.is_dir():
                raise ValueError(f"cwd 不存在或不是目录: {exec_dir}")
            return exec_dir
        
        # Use user directory manager if available
        if self._user_dir_manager:
            user_dir = await self._user_dir_manager.ensure_directory(
                context.agent_name, context.user, context.session_id
            )
            if context.cwd:
                exec_dir = Path(str(context.cwd))
                if not exec_dir.exists() or not exec_dir.is_dir():
                    raise ValueError(f"cwd 不存在或不是目录: {exec_dir}")
                return exec_dir
            return Path(user_dir)
        
        # Fallback to base implementation
        return self.resolve_exec_dir(context)
    
    async def _handle_slash_command(
        self,
        content: str,
        context: RequestContext,
        output_format: str,
    ) -> AsyncGenerator[str, None]:
        """Handle slash commands via callback."""
        try:
            response = await self._slash_command_handler(content, context.session_id)
            
            logger.info(f"Slash command handled", extra={
                "command": content.split()[0] if content else "",
                "agent_name": context.agent_name,
                "response_length": len(response),
            })
            
            if output_format == "legacy":
                yield self.format_legacy_sse(response, finished=True)
            else:
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
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Process subprocess stream output."""
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
            async for line in self.read_stream(process, self.config.timeout):
                line_count += 1
                try:
                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        continue
                    
                    if debug_file:
                        debug_file.write(f"[{line_count}] {line_str}\n")
                        debug_file.flush()
                    
                    if output_format == "raw":
                        yield line_str
                        continue
                    
                    # Legacy format processing
                    data = json.loads(line_str)
                    event_type = data.get("type")
                    
                    for sse in self._process_legacy_event(data, event_type, tool_input_buffer):
                        yield sse
                        
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON line #{line_count}")
                except Exception as e:
                    logger.error(f"Error processing stream line #{line_count}: {e}")
                    if output_format == "legacy":
                        yield self.format_legacy_sse(f"处理流事件时出错: {str(e)}", finished=False)
            
            logger.info(f"Stream processing completed, total lines: {line_count}")
            
            # Drain stderr
            await self.drain_stderr(process)
            
        finally:
            if debug_file:
                debug_file.write(f"\n=== Stream End: {line_count} lines ===\n")
                debug_file.close()
    
    def _process_legacy_event(
        self, 
        data: Dict[str, Any], 
        event_type: str, 
        tool_input_buffer: Dict[int, str]
    ) -> List[str]:
        """Process legacy format events."""
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
    
    def _format_stream_event_legacy(
        self, 
        data: Dict[str, Any], 
        tool_input_buffer: Dict[int, str]
    ) -> str:
        """Format stream_event for legacy protocol."""
        event = data.get("event", {})
        event_type = event.get("type")
        
        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            delta_type = delta.get("type")
            
            if delta_type == "text_delta":
                return delta.get("text", "")
            
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
        """Format user message (tool result) for legacy protocol."""
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
    
    # Helper methods
    
    def _is_slash_command(self, content: str) -> bool:
        """Check if content is a slash command."""
        from src.runtime.commands.slash.handler import SLASH_COMMANDS
        content_lower = content.lower().strip()
        for cmd in SLASH_COMMANDS:
            if content_lower == cmd or content_lower.startswith(cmd + " "):
                return True
        return False
    
    def _clean_content(self, content: str) -> str:
        """Clean input content."""
        cleaned = (content or "").strip()
        while cleaned.startswith('\n'):
            cleaned = cleaned[1:].strip()
        return cleaned
    
    def _parse_model_param(self, content: str) -> tuple:
        """Parse --model parameter from content."""
        model_pattern = r'--model\s+([^\s]+(?:\s*,\s*[^\s,]+)*)'
        match = re.search(model_pattern, content)
        
        if match:
            model_value = match.group(1).strip()
            cleaned_content = re.sub(model_pattern, '', content).strip()
            cleaned_content = re.sub(r'\s+', ' ', cleaned_content).strip()
            return cleaned_content, model_value
        
        return content, None
    
    def _format_error_message(self, error: str, agent_name: str) -> str:
        """Format error message."""
        if "su:" in error:
            return f"无法切换到用户 '{agent_name}'。请确保用户存在且当前进程有切换权限。"
        elif "cannot create child process" in error.lower():
            return f"无法创建子进程。可能是权限不足或资源限制。"
        return f"处理错误: {error}"
    
    def format_legacy_sse(self, response: str, finished: bool = False, answer_success: int = 1) -> str:
        """Format as legacy SSE."""
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
        """Format legacy error message."""
        return self.format_legacy_sse(error_msg, finished=True, answer_success=0)

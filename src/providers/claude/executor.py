# -*- coding: utf-8 -*-
"""CCR (Claude Code Runner) Executor

This executor runs the CCR/Claude CLI as a subprocess.

IMPORTANT: This module is part of providers layer and must NOT depend on
server layers. API-specific logic (like slash command handlers) should be 
injected via callbacks or kept in the API layer.
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

from ..base import BaseExecutor, ExecutorConfig, RequestContext

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
            output_format: Output format (only "raw" JSON lines supported)
            
        Yields:
            Output lines (JSON format)
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
                async for output in self._handle_slash_command(cleaned_content, context):
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
        final_cmd = self.wrap_command_for_user(cmd, exec_dir, context.exec_user)
        
        logger.info(
            f"Starting CCR processing",
            extra={
                "process_type": "ccr_start",
                "api_user": context.user,
                "exec_user": context.exec_user,
                "content_preview": cleaned_content[:100] if len(cleaned_content) > 100 else cleaned_content,
                "exec_dir": str(exec_dir),
                "cwd_mode": context.cwd_mode,
                "run_kind": context.run_kind,
                "use_continue": use_continue,
            }
        )
        
        try:
            process = await self.run_subprocess(final_cmd)
            
            async for output in self._process_stream(process):
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
            yield json.dumps({"type": "error", "message": "处理超时，请重试"})
                
        except Exception as e:
            logger.error(f"Process error: {e}", exc_info=True)
            error_msg = self._format_error_message(str(e), context.exec_user)
            yield json.dumps({"type": "error", "message": error_msg})
    
    def _build_command(self, context: RequestContext, use_continue: bool = True) -> List[str]:
        """Build CCR command."""
        cleaned_content, model_param = self._parse_model_param(context.content)
        
        ccr_command = self.ccr_config.agent_ccr_command_map.get(
            context.exec_user, 
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
                context.exec_user, context.user, context.session_id
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
    ) -> AsyncGenerator[str, None]:
        """Handle slash commands via callback."""
        try:
            response = await self._slash_command_handler(content, context.session_id)
            
            logger.info(f"Slash command handled", extra={
                "command": content.split()[0] if content else "",
                "exec_user": context.exec_user,
                "response_length": len(response),
            })
            
            yield json.dumps({
                "type": "result",
                "subtype": "slash_command",
                "content": response,
            })
                
        except Exception as e:
            logger.error(f"Slash command error: {e}", exc_info=True)
            yield json.dumps({"type": "error", "message": f"命令执行错误: {str(e)}"})
    
    async def _process_stream(
        self,
        process: asyncio.subprocess.Process,
    ) -> AsyncGenerator[str, None]:
        """Process subprocess stream output (raw JSON lines only)."""
        line_count = 0
        
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
                    
                    yield line_str
                        
                except Exception as e:
                    logger.error(f"Error processing stream line #{line_count}: {e}")
            
            logger.info(f"Stream processing completed, total lines: {line_count}")
            
            # Drain stderr
            await self.drain_stderr(process)
            
        finally:
            if debug_file:
                debug_file.write(f"\n=== Stream End: {line_count} lines ===\n")
                debug_file.close()
    
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
    
    def _format_error_message(self, error: str, exec_user: str) -> str:
        """Format error message."""
        if "su:" in error:
            return f"无法切换到用户 '{exec_user}'。请确保用户存在且当前进程有切换权限。"
        elif "cannot create child process" in error.lower():
            return f"无法创建子进程。可能是权限不足或资源限制。"
        return f"处理错误: {error}"

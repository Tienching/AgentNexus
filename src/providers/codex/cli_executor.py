# -*- coding: utf-8 -*-
"""Codex CLI Executor

This executor runs Codex CLI using `codex exec --json` non-interactive mode.
Based on OpenAI Codex documentation: https://developers.openai.com/codex/noninteractive

IMPORTANT: This module is part of providers layer and must NOT depend on
server layers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from ..base import BaseExecutor, ExecutorConfig, RequestContext

logger = logging.getLogger(__name__)


class CodexCLIExecutorConfig(ExecutorConfig):
    """Codex CLI executor configuration."""
    
    def __init__(
        self,
        timeout: float = 600.0,  # Codex tasks can be long-running
        user_home_base: str = "/home",
        codex_command: str = "codex-internal",  # Use codex-internal as default (installed on system)
        sandbox_mode: str = "workspace-write",  # read-only, workspace-write, danger-full-access
        full_auto: bool = True,  # Allow file edits without confirmation
        skip_git_repo_check: bool = True,  # Skip git repo check for non-git directories
        **kwargs,
    ):
        super().__init__(timeout=timeout, user_home_base=user_home_base)
        self.codex_command = codex_command
        self.sandbox_mode = sandbox_mode
        self.full_auto = full_auto
        self.skip_git_repo_check = skip_git_repo_check
        self.extra.update(kwargs)


class CodexCLIExecutor(BaseExecutor):
    """Codex CLI executor using `codex exec --json` mode.
    
    Runs Codex in non-interactive mode and yields JSON line stream.
    
    Output format (JSON Lines):
    - {"type":"thread.started","thread_id":"..."}
    - {"type":"turn.started"}
    - {"type":"item.started","item":{"id":"...","type":"command_execution",...}}
    - {"type":"item.completed","item":{"id":"...","type":"agent_message","text":"..."}}
    - {"type":"turn.completed","usage":{...}}
    """
    
    def __init__(self, config: Optional[CodexCLIExecutorConfig] = None):
        super().__init__(config or CodexCLIExecutorConfig())
    
    @property
    def codex_config(self) -> CodexCLIExecutorConfig:
        """Get Codex-specific config."""
        return self.config  # type: ignore
    
    async def execute(
        self,
        request: Any,
        agent_name: str = "default",
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Execute Codex CLI and yield stream output.
        
        This method signature matches CCRExecutor for compatibility with StreamOrchestrator.
        
        Args:
            request: RequestModel instance (from server layer)
            agent_name: Linux system user name
            output_format: Output format (only "raw" JSON lines supported)
            
        Yields:
            Output lines (JSON format)
        """
        # Convert RequestModel to RequestContext
        context = RequestContext.from_request_model(request, agent_name)
        
        async for line in self._execute_internal(context):
            yield line
    
    async def _execute_internal(
        self,
        context: RequestContext,
    ) -> AsyncGenerator[str, None]:
        """Internal execution implementation."""
        start_time = time.time()
        
        if not context.content:
            raise ValueError("Missing required field: content")
        
        cleaned_content = self._clean_content(context.content)
        
        # Resolve execution directory
        exec_dir = self.resolve_exec_dir(context)
        
        if context.cwd:
            if not exec_dir.exists() or not exec_dir.is_dir():
                raise ValueError(f"cwd 不存在或不是目录: {exec_dir}")
        
        logger.info(
            f"Starting Codex CLI processing",
            extra={
                "process_type": "codex_cli_start",
                "agent_name": context.agent_name,
                "content_preview": cleaned_content[:100] if len(cleaned_content) > 100 else cleaned_content,
                "exec_dir": str(exec_dir),
            }
        )
        
        cmd = self._build_command(context)
        final_cmd = self.wrap_command_for_user(cmd, exec_dir, context.agent_name)
        
        logger.info(
            f"Codex CLI command: raw={' '.join(cmd)}, final={' '.join(final_cmd)}, agent={context.agent_name}, dir={exec_dir}"
        )
        
        try:
            process = await self.run_subprocess(final_cmd)
            
            # Read stderr for debugging
            line_count = 0
            async for output in self._process_stream(process):
                line_count += 1
                yield output
            
            logger.info(f"Codex CLI stream completed: {line_count} lines")
            
            # Drain stderr and log it
            stderr_content = await self.drain_stderr(process)
            if stderr_content:
                logger.warning(f"Codex CLI stderr: {stderr_content[:500]}")
            
            await asyncio.wait_for(process.wait(), timeout=self.config.timeout)
            
            duration = time.time() - start_time
            logger.info(f"Codex CLI processing completed", extra={
                "process_type": "codex_cli_complete",
                "duration_ms": int(duration * 1000),
            })
            
        except asyncio.TimeoutError:
            logger.error(f"Codex CLI command timeout", extra={"timeout_seconds": self.config.timeout})
            try:
                process.kill()
            except Exception:
                pass
            yield json.dumps({"type": "error", "message": "处理超时，请重试"})
                
        except Exception as e:
            logger.exception("Codex CLI process error")
            yield json.dumps({"type": "error", "message": f"处理错误: {e}"})
        
        finally:
            _ = start_time  # keep parity hook for future metrics
    
    def _build_command(self, context: RequestContext) -> List[str]:
        """Build Codex CLI command.
        
        Command format: codex exec --json [options] "prompt"
        """
        cleaned_content, model_param = self._parse_model_param(context.content)
        
        cmd = [
            self.codex_config.codex_command,
            "exec",
            "--json",
        ]
        
        # Skip git repo check for non-git directories
        if self.codex_config.skip_git_repo_check:
            cmd.append("--skip-git-repo-check")
        
        # Add sandbox mode
        if self.codex_config.sandbox_mode:
            cmd.extend(["--sandbox", self.codex_config.sandbox_mode])
        
        # Add full-auto mode for file edits
        if self.codex_config.full_auto:
            cmd.append("--full-auto")
        
        # Add model if specified
        if model_param:
            cmd.extend(["--model", model_param])
        
        # Add the prompt
        cmd.append(cleaned_content)
        
        return cmd
    
    async def _process_stream(
        self,
        process: asyncio.subprocess.Process,
    ) -> AsyncGenerator[str, None]:
        """Process subprocess stream output (raw JSON lines only)."""
        line_count = 0
        
        async for line in self.read_stream(process, self.config.timeout):
            line_count += 1
            try:
                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue
                
                # Skip non-JSON lines (stderr leaks, logs, etc.)
                if not line_str.startswith("{"):
                    logger.debug(f"Skipping non-JSON line: {line_str[:100]}")
                    continue
                
                # Validate JSON
                try:
                    json.loads(line_str)
                except json.JSONDecodeError:
                    logger.debug(f"Skipping invalid JSON: {line_str[:100]}")
                    continue
                
                yield line_str
                    
            except Exception as e:
                logger.warning(f"Error processing stream line #{line_count}: {e}")
                continue
        
        logger.debug(f"Codex CLI stream completed, total lines: {line_count}")
        
        # Drain stderr
        await self.drain_stderr(process)
    
    # Helper methods
    
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

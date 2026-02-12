# -*- coding: utf-8 -*-
"""Gemini CLI Executor

This executor runs the Gemini CLI as a subprocess.

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


class GeminiExecutorConfig(ExecutorConfig):
    """Gemini-specific configuration."""
    
    def __init__(
        self,
        timeout: float = 120.0,
        user_home_base: str = "/home",
        gemini_command: str = "gemini",
        **kwargs,
    ):
        super().__init__(timeout=timeout, user_home_base=user_home_base)
        self.gemini_command = gemini_command
        self.extra.update(kwargs)


class GeminiExecutor(BaseExecutor):
    """Gemini CLI executor.
    
    Runs Gemini CLI and yields stream output.
    """
    
    def __init__(self, config: Optional[GeminiExecutorConfig] = None):
        if config is None:
            super().__init__(GeminiExecutorConfig())
            return
        if isinstance(config, GeminiExecutorConfig):
            super().__init__(config)
            return
        # Backward-compat: accept server settings-like objects.
        super().__init__(
            GeminiExecutorConfig(
                timeout=getattr(config, "cli_timeout", 120.0),
                user_home_base=getattr(config, "user_home_base", "/home"),
                gemini_command=getattr(config, "gemini_command", "gemini"),
            )
        )
    
    @property
    def gemini_config(self) -> GeminiExecutorConfig:
        """Get Gemini-specific config."""
        return self.config  # type: ignore
    
    async def execute(
        self,
        request: Any,
        exec_user: str = "default",
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Execute Gemini CLI and yield stream output.
        
        This signature matches CLI/Codex executors for StreamHandler compatibility.
        
        Args:
            request: RequestModel or RequestContext
            exec_user: Linux system user name
            output_format: Output format (only "raw" JSON lines supported)
            
        Yields:
            Output lines (JSON format)
        """
        if isinstance(request, RequestContext):
            context = request
        else:
            context = RequestContext.from_request_model(request, exec_user)
        async for line in self._execute_internal(context, output_format=output_format):
            yield line

    async def _execute_internal(
        self,
        context: RequestContext,
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Internal execution implementation using RequestContext."""
        start_time = time.time()
        
        if not context.content:
            raise ValueError("Missing required field: content")
        
        cleaned_content = self._clean_content(context.content)
        
        # Resolve execution directory
        exec_dir = self.resolve_exec_dir(context)
        
        if context.cwd:
            if not exec_dir.exists() or not exec_dir.is_dir():
                raise ValueError(f"cwd 不存在或不是目录: {exec_dir}")
        
        cmd = self._build_command(context)
        final_cmd = self.wrap_command_for_user(cmd, exec_dir, context.exec_user)
        
        try:
            process = await self.run_subprocess(final_cmd)
            
            async for output in self._process_stream(process):
                yield output
            
            await asyncio.wait_for(process.wait(), timeout=self.config.timeout)
            
        except asyncio.TimeoutError:
            try:
                process.kill()
            except Exception:
                pass
            yield json.dumps({"type": "error", "message": "处理超时，请重试"})
                
        except Exception as e:
            logger.exception("Gemini process error")
            yield json.dumps({"type": "error", "message": f"处理错误: {e}"})
        
        finally:
            _ = start_time  # keep parity hook for future metrics
    
    def _build_command(self, context: RequestContext) -> List[str]:
        """Build Gemini CLI command."""
        cleaned_content, model_param = self._parse_model_param(context.content)
        
        is_chat_continue = getattr(context, "run_kind", "") == "chat_continue"
        
        # Use alias as CLI command name if provided, otherwise default
        cli_command = (getattr(context, "alias", None) or "").strip() or self.gemini_config.gemini_command
        cmd = [cli_command]
        if is_chat_continue:
            cmd.extend(["--resume", "latest"])
        cmd.extend(["-p", cleaned_content, "--output-format", "stream-json"])
        if model_param:
            cmd.extend(["--model", model_param])
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
                
                yield line_str
                    
            except Exception:
                continue
        
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

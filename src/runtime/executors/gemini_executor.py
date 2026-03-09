# -*- coding: utf-8 -*-
"""Gemini CLI Executor

This executor runs the Gemini CLI as a subprocess.

IMPORTANT: This module is part of agent_runtime and must NOT depend on
claude_code_api or server layers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from .base import BaseExecutor, ExecutorConfig, RequestContext

logger = logging.getLogger(__name__)


class GeminiExecutorConfig(ExecutorConfig):
    """Gemini-specific configuration."""
    
    def __init__(
        self,
        timeout: float = 600.0,
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
        super().__init__(config or GeminiExecutorConfig())
    
    @property
    def gemini_config(self) -> GeminiExecutorConfig:
        """Get Gemini-specific config."""
        return self.config  # type: ignore
    
    async def execute(
        self,
        context: RequestContext,
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Execute Gemini CLI and yield stream output.
        
        Args:
            context: Request context
            output_format: "raw" (JSON lines) or "legacy" (event:delta SSE)
            
        Yields:
            Output lines
        """
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
            
            async for output in self._process_stream(process, output_format):
                yield output
            
            await asyncio.wait_for(process.wait(), timeout=self.config.timeout)
            
        except asyncio.TimeoutError:
            try:
                process.kill()
            except Exception:
                pass
            if output_format == "legacy":
                yield self.format_legacy_error("处理超时，请重试")
            else:
                yield json.dumps({"type": "error", "message": "处理超时，请重试"})
                
        except Exception as e:
            logger.exception("Gemini process error")
            msg = f"处理错误: {e}"
            if output_format == "legacy":
                yield self.format_legacy_error(msg)
            else:
                yield json.dumps({"type": "error", "message": msg})
        
        finally:
            _ = start_time  # keep parity hook for future metrics
    
    def _build_command(self, context: RequestContext) -> List[str]:
        """Build Gemini CLI command."""
        cleaned_content, model_param = self._parse_model_param(context.content)
        
        is_chat_continue = getattr(context, "run_kind", "") == "chat_continue"
        cli_session_id = getattr(context, "cli_session_id", None) or None
        session_cleared = getattr(context, "session_cleared", False)
        
        cmd = [self.gemini_config.gemini_command]
        if is_chat_continue and not session_cleared:
            if cli_session_id:
                cmd.extend(["--resume", cli_session_id])
            else:
                cmd.extend(["--resume", "latest"])
        cmd.extend(["-p", cleaned_content, "--output-format", "stream-json"])
        if model_param:
            cmd.extend(["--model", model_param])
        return cmd
    
    async def _process_stream(
        self,
        process: asyncio.subprocess.Process,
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Process subprocess stream output."""
        line_count = 0
        tool_input_buffer: Dict[int, str] = {}
        
        async for line in self.read_stream(process, self.config.timeout):
            line_count += 1
            try:
                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue
                
                if output_format == "raw":
                    yield line_str
                    continue
                
                data = json.loads(line_str)
                event_type = data.get("type")
                for sse in self._process_legacy_event(data, event_type, tool_input_buffer):
                    yield sse
                    
            except json.JSONDecodeError:
                continue
            except Exception:
                if output_format == "legacy":
                    yield self.format_legacy_sse("处理流事件时出错", finished=False, answer_success=0)
        
        # Drain stderr
        await self.drain_stderr(process)
    
    def _process_legacy_event(
        self, 
        data: Dict[str, Any], 
        event_type: str, 
        tool_input_buffer: Dict[int, str]
    ) -> List[str]:
        """Process legacy format events for Gemini."""
        results = []
        
        if event_type == "message":
            if data.get("role") == "assistant":
                content = data.get("content", "")
                if content:
                    results.append(self.format_legacy_sse(content, finished=False, answer_success=1))
        
        elif event_type == "tool_use":
            tool_name = data.get("tool_name") or "unknown"
            params = data.get("parameters")
            text = f"\n🔧 **调用工具: {tool_name}**\n"
            if params:
                try:
                    params_str = json.dumps(params, ensure_ascii=False)
                except Exception:
                    params_str = str(params)
                text += f"参数: {params_str}\n"
            results.append(self.format_legacy_sse(text, finished=False, answer_success=1))
        
        elif event_type == "tool_result":
            status = (data.get("status") or "").lower()
            output = data.get("output")
            content = "" if output is None else str(output)
            if status and status != "success":
                results.append(self.format_legacy_sse(f"❌ **错误**: {content}\n", finished=False, answer_success=0))
            else:
                results.append(self.format_legacy_sse(f"✅ **结果**: {content}\n", finished=False, answer_success=1))
        
        elif event_type == "result" and data.get("subtype") == "slash_command":
            content = data.get("content") or ""
            if content:
                results.append(self.format_legacy_sse(content, finished=True, answer_success=1))
        
        elif event_type == "error":
            msg = data.get("message") or "Gemini CLI error"
            results.append(self.format_legacy_sse(msg, finished=True, answer_success=0))
        
        return results
    
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

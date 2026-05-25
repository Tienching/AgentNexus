# -*- coding: utf-8 -*-
"""Codebuddy CLI Executor

This executor runs the Codebuddy CLI as a subprocess.

IMPORTANT: This module is part of providers layer and must NOT depend on
server layers.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import signal
import time
from typing import Any, AsyncGenerator, List, Optional

from ..base import BaseExecutor, ExecutorConfig, RequestContext, assemble_cli_prompt

logger = logging.getLogger(__name__)


def _clean_default_model(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _env_default_model() -> str:
    return (
        os.environ.get("CODEBUDDY_DEFAULT_MODEL")
        or os.environ.get("AGENT_NEXUS_CODEBUDDY_DEFAULT_MODEL")
        or ""
    ).strip()


class CodebuddyExecutorConfig(ExecutorConfig):
    """Codebuddy-specific configuration."""

    def __init__(
        self,
        timeout: float = 600.0,
        user_home_base: str = "/home",
        codebuddy_command: str = "codebuddy",
        default_model: str = "",
        **kwargs,
    ):
        super().__init__(timeout=timeout, user_home_base=user_home_base)
        self.codebuddy_command = codebuddy_command
        self.default_model = _clean_default_model(default_model) or _env_default_model()
        self.extra.update(kwargs)


class CodebuddyCLIExecutor(BaseExecutor):
    """Codebuddy CLI executor.

    Runs Codebuddy CLI and yields stream output.
    """

    def __init__(self, config: Optional[CodebuddyExecutorConfig] = None):
        if config is None:
            super().__init__(CodebuddyExecutorConfig())
            return
        if isinstance(config, CodebuddyExecutorConfig):
            super().__init__(config)
            return
        # Backward-compat: accept server settings-like objects.
        super().__init__(
            CodebuddyExecutorConfig(
                timeout=getattr(config, "cli_timeout", 600.0),
                user_home_base=getattr(config, "user_home_base", "/home"),
                codebuddy_command=getattr(config, "codebuddy_command", "codebuddy"),
                default_model=getattr(config, "codebuddy_default_model", ""),
            )
        )

    @property
    def codebuddy_config(self) -> CodebuddyExecutorConfig:
        """Get Codebuddy-specific config."""
        return self.config  # type: ignore

    async def run_subprocess(
        self,
        final_cmd: List[str],
        timeout: Optional[float] = None,
    ) -> asyncio.subprocess.Process:
        """Start CodeBuddy in its own process group so timeout cleanup kills tools too."""
        return await asyncio.create_subprocess_exec(
            *final_cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=10 * 1024 * 1024,
            start_new_session=True,
        )

    async def execute(
        self,
        request: Any,
        exec_user: str = "default",
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Execute Codebuddy CLI and yield stream output.

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

        if not (
            context.content
            or getattr(context, "content_parts", None)
            or getattr(context, "image_paths", None)
            or getattr(context, "file_paths", None)
        ):
            raise ValueError("Missing required field: content")

        # Resolve execution directory
        exec_dir = self.resolve_exec_dir(context)

        if context.cwd:
            if not exec_dir.exists() or not exec_dir.is_dir():
                raise ValueError(f"cwd 不存在或不是目录: {exec_dir}")

        cmd = self._build_command(context)
        final_cmd = self.wrap_command_for_user(cmd, exec_dir, context.exec_user)

        process: Optional[asyncio.subprocess.Process] = None

        try:
            async with asyncio.timeout(float(self.config.timeout)):
                process = await self.run_subprocess(final_cmd)

                async for output in self._process_stream(process, context):
                    yield output

                await process.wait()

        except asyncio.TimeoutError:
            if process is not None:
                await self._cleanup_timed_out_process(process)
            logger.error("Codebuddy command timeout", extra={"timeout_seconds": self.config.timeout})
            yield json.dumps({"type": "error", "message": "处理超时，请重试"})

        except Exception as e:
            logger.exception("Codebuddy process error")
            yield json.dumps({"type": "error", "message": f"处理错误: {e}"})

        finally:
            _ = start_time  # keep parity hook for future metrics

    async def _cleanup_timed_out_process(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        """Best-effort timeout cleanup for real processes and async mocks."""
        try:
            pid = getattr(process, "pid", None)
            if isinstance(pid, int):
                os.killpg(os.getpgid(pid), signal.SIGKILL)
                kill_result = None
            else:
                kill_result = process.kill()
            if inspect.isawaitable(kill_result):
                await kill_result
        except Exception:
            try:
                kill_result = process.kill()
            except Exception:
                kill_result = None
            try:
                if inspect.isawaitable(kill_result):
                    await kill_result
            except Exception:
                pass

        try:
            await asyncio.wait_for(process.wait(), timeout=1.0)
        except Exception:
            pass

        try:
            await self.drain_stderr(process)
        except Exception:
            pass

    def _build_command(self, context: RequestContext) -> List[str]:
        """Build Codebuddy CLI command."""
        cleaned_content, inline_model = self._parse_model_param(context.content)
        model_param = (
            _clean_default_model(inline_model)
            or _clean_default_model(getattr(context, "model", None))
            or _clean_default_model(getattr(self.codebuddy_config, "default_model", ""))
            or _env_default_model()
            or None
        )

        is_inplace = getattr(context, "cwd_mode", "") == "inplace"
        is_chat_continue = getattr(context, "run_kind", "") == "chat_continue"
        model_changed = bool(getattr(context, "model_changed", False))
        use_continue = ((not is_inplace) or is_chat_continue) and not model_changed
        cli_session_id = (getattr(context, "cli_session_id", None) or "").strip() or None
        session_cleared = getattr(context, "session_cleared", False)
        is_clear = cleaned_content.lower() == "/clear"
        has_media_input = bool(
            getattr(context, "image_paths", None)
            or getattr(context, "file_paths", None)
            or [
                part
                for part in (getattr(context, "content_parts", None) or [])
                if isinstance(part, dict) and part.get("type") != "text"
            ]
        )
        if has_media_input:
            use_continue = False
        message = "你好" if is_clear else assemble_cli_prompt(
            cleaned_content,
            image_paths=getattr(context, "image_paths", None) or None,
            file_paths=getattr(context, "file_paths", None) or None,
            content_parts=getattr(context, "content_parts", None) or None,
        )

        # Use alias as CLI command name if provided, otherwise default
        cli_command = (getattr(context, "alias", None) or "").strip() or self.codebuddy_config.codebuddy_command
        cmd = [cli_command]
        if use_continue and not session_cleared and not is_clear:
            if cli_session_id:
                cmd.extend(["-r", cli_session_id])
            else:
                cmd.append("-c")
        cmd.extend([
            "-p",
            message,
            "--output-format",
            "stream-json",
            "--dangerously-skip-permissions",
        ])
        if model_param:
            cmd.extend(["--model", model_param])
        return cmd

    async def _process_stream(
        self,
        process: asyncio.subprocess.Process,
        context: Optional[RequestContext] = None,
    ) -> AsyncGenerator[str, None]:
        """Process subprocess stream output (raw JSON lines only)."""
        captured_cli_session_id: Optional[str] = None
        async for line in self.read_stream(process, self.config.timeout):
            try:
                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                try:
                    data = json.loads(line_str)
                except (json.JSONDecodeError, TypeError):
                    data = None
                if isinstance(data, dict):
                    cli_session_id = data.get("session_id") or data.get("thread_id")
                    if (
                        cli_session_id
                        and isinstance(cli_session_id, str)
                        and cli_session_id != captured_cli_session_id
                    ):
                        captured_cli_session_id = cli_session_id
                        await self._notify_cli_session_id(context, cli_session_id)

                yield line_str

            except Exception:
                continue

        # Drain stderr
        await self.drain_stderr(process)

    async def _notify_cli_session_id(
        self,
        context: Optional[RequestContext],
        cli_session_id: str,
    ) -> None:
        """Notify API/runtime layers that CodeBuddy reported its native session ID."""
        if not context or not cli_session_id:
            return
        callback = (getattr(context, "metadata", None) or {}).get("on_cli_session_id")
        if not callable(callback):
            return
        try:
            result = callback(cli_session_id)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.debug("Failed to persist CodeBuddy cli_session_id", exc_info=True)

    # Helper methods

    def _clean_content(self, content: str) -> str:
        """Clean input content."""
        cleaned = (content or "").strip()
        while cleaned.startswith("\n"):
            cleaned = cleaned[1:].strip()
        return cleaned

    def _parse_model_param(self, content: str) -> tuple:
        """Parse --model parameter from content."""
        model_pattern = r"--model\s+([^\s]+(?:\s*,\s*[^\s,]+)*)"
        match = re.search(model_pattern, content)
        if match:
            model_value = match.group(1).strip()
            cleaned_content = re.sub(model_pattern, "", content).strip()
            cleaned_content = re.sub(r"\s+", " ", cleaned_content).strip()
            return cleaned_content, model_value
        return content, None

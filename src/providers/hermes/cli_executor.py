# -*- coding: utf-8 -*-
"""Hermes CLI Executor

Runs the Hermes CLI (`hermes chat -q <prompt> -Q`) as a subprocess and yields
its stream-json output. The contract mirrors :class:`CodebuddyCLIExecutor` so
the existing stream → AG-UI adapter pipeline works unchanged.

Hermes is a tool-calling agent CLI; in quiet non-interactive mode it emits
JSON-lines events (text deltas, tool calls, session id) that map cleanly onto
the same stream-json shape CodeBuddy/Claude produce.

IMPORTANT: This module is part of the providers layer and must NOT depend on
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

from ..base import BaseExecutor, ExecutorConfig, RequestContext

logger = logging.getLogger(__name__)


def _env_default_model() -> str:
    return (
        os.environ.get("HERMES_DEFAULT_MODEL")
        or os.environ.get("AGENT_NEXUS_HERMES_DEFAULT_MODEL")
        or ""
    ).strip()


class HermesExecutorConfig(ExecutorConfig):
    """Hermes-specific configuration."""

    def __init__(
        self,
        timeout: float = 600.0,
        user_home_base: str = "/home",
        hermes_command: str = "hermes",
        default_model: str = "",
        default_provider: str = "",
        **kwargs,
    ):
        super().__init__(timeout=timeout, user_home_base=user_home_base)
        self.hermes_command = hermes_command
        self.default_model = _clean(default_model) or _env_default_model()
        self.default_provider = _clean(default_provider)
        self.extra.update(kwargs)


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


class HermesCLIExecutor(BaseExecutor):
    """Hermes CLI executor.

    Runs the Hermes CLI in quiet non-interactive mode and yields stream-json
    output. Session resumption is supported via ``hermes chat --resume <id>``.
    """

    def __init__(self, config: Optional[HermesExecutorConfig] = None):
        if config is None:
            super().__init__(HermesExecutorConfig())
            return
        if isinstance(config, HermesExecutorConfig):
            super().__init__(config)
            return
        # Backward-compat: accept server-settings-like objects.
        super().__init__(
            HermesExecutorConfig(
                timeout=getattr(config, "cli_timeout", 600.0),
                user_home_base=getattr(config, "user_home_base", "/home"),
                hermes_command=getattr(config, "hermes_command", "hermes"),
                default_model=getattr(config, "hermes_default_model", ""),
                default_provider=getattr(config, "hermes_default_provider", ""),
            )
        )

    @property
    def hermes_config(self) -> HermesExecutorConfig:
        return self.config  # type: ignore[return-value]

    async def run_subprocess(
        self,
        final_cmd: List[str],
        timeout: Optional[float] = None,
    ) -> asyncio.subprocess.Process:
        """Start Hermes in its own process group so timeout cleanup kills tools too."""
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
        """Execute Hermes CLI and yield stream-json output.

        Signature mirrors CodebuddyCLIExecutor for StreamHandler compatibility.
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
        start_time = time.time()

        if not (context.content or getattr(context, "content_parts", None)):
            raise ValueError("Missing required field: content")

        exec_dir = self.resolve_exec_dir(context)
        if context.cwd and (not exec_dir.exists() or not exec_dir.is_dir()):
            raise ValueError(f"cwd does not exist or is not a directory: {exec_dir}")

        cmd = self._build_command(context)
        final_cmd = self.wrap_command_for_user(cmd, exec_dir, context.exec_user)

        process: Optional[asyncio.subprocess.Process] = None
        try:
            async with asyncio.timeout(float(self.config.timeout)):
                process = await self.run_subprocess(final_cmd)
                async for output in self._process_stream(process, context):
                    yield output

                await process.wait()
                returncode = process.returncode
                stderr_text = await self.drain_stderr(process)
                if returncode not in (0, None):
                    message = self._format_nonzero_exit_message(returncode, stderr_text)
                    logger.error(message)
                    yield json.dumps({"type": "error", "message": message})

        except asyncio.TimeoutError:
            if process is not None:
                await self._cleanup_timed_out_process(process)
            logger.error("Hermes command timeout", extra={"timeout_seconds": self.config.timeout})
            yield json.dumps({"type": "error", "message": "processing timed out, please retry"})

        except Exception as e:
            logger.exception("Hermes process error")
            yield json.dumps({"type": "error", "message": f"processing error: {e}"})

        finally:
            _ = start_time

    def _format_nonzero_exit_message(self, returncode: int, stderr_text: Optional[str]) -> str:
        detail = (stderr_text or "").strip()
        if not detail:
            return f"Hermes CLI exited with code {returncode}"
        detail = re.sub(r"\s+", " ", detail)
        if len(detail) > 600:
            detail = detail[:600].rstrip() + "..."
        return f"Hermes CLI exited with code {returncode}: {detail}"

    async def _cleanup_timed_out_process(self, process: asyncio.subprocess.Process) -> None:
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
        """Build the `hermes chat` command.

        Flags (confirmed via `hermes chat --help`):
          -q/--query <text>   non-interactive single query
          -Q/--quiet          quiet mode for programmatic use (no banner/spinner)
          -m/--model <id>     model to use
          --provider <name>   inference provider
          -r/--resume <id>    resume a previous session
          -s/--skills <list>  preload skills (comma-separated)
          --yolo              skip permission prompts (autonomous)
        """
        cleaned_content, inline_model = self._parse_model_param(context.content)
        model_param = (
            _clean(inline_model)
            or _clean(getattr(context, "model", None))
            or _clean(getattr(self.hermes_config, "default_model", ""))
            or _env_default_model()
            or None
        )
        provider_param = _clean(getattr(self.hermes_config, "default_provider", "")) or None

        is_inplace = getattr(context, "cwd_mode", "") == "inplace"
        is_chat_continue = getattr(context, "run_kind", "") == "chat_continue"
        model_changed = bool(getattr(context, "model_changed", False))
        use_resume = ((not is_inplace) or is_chat_continue) and not model_changed
        cli_session_id = (getattr(context, "cli_session_id", None) or "").strip() or None
        session_cleared = getattr(context, "session_cleared", False)
        is_clear = cleaned_content.lower() == "/clear"
        has_media_input = bool(
            getattr(context, "image_paths", None)
            or getattr(context, "file_paths", None)
        )
        if has_media_input:
            use_resume = False

        message = "hello" if is_clear else (cleaned_content or "")

        cli_command = (getattr(context, "alias", None) or "").strip() or self.hermes_config.hermes_command
        cmd = [cli_command, "chat", "-q", message, "-Q"]
        if use_resume and not session_cleared and not is_clear and cli_session_id:
            cmd.extend(["--resume", cli_session_id])
        if model_param:
            cmd.extend(["-m", model_param])
        if provider_param:
            cmd.extend(["--provider", provider_param])
        # Autonomous mode so the non-interactive run isn't blocked on prompts.
        cmd.append("--yolo")
        return cmd

    async def _process_stream(
        self,
        process: asyncio.subprocess.Process,
        context: Optional[RequestContext] = None,
    ) -> AsyncGenerator[str, None]:
        """Process subprocess stream output (raw JSON lines, pass through)."""
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

    async def _notify_cli_session_id(
        self,
        context: Optional[RequestContext],
        cli_session_id: str,
    ) -> None:
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
            logger.debug("Failed to persist Hermes cli_session_id", exc_info=True)

    def _parse_model_param(self, content: str) -> tuple:
        """Parse a `--model <id>` directive out of the user content."""
        model_pattern = r"--model\s+([^\s]+(?:\s*,\s*[^\s,]+)*)"
        match = re.search(model_pattern, content)
        if match:
            model_value = match.group(1).strip()
            cleaned = re.sub(model_pattern, "", content).strip()
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return cleaned, model_value
        return content, None

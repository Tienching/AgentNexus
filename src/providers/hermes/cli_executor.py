# -*- coding: utf-8 -*-
"""Hermes Agent CLI executor.

Hermes (``hermes-agent``) is an agent CLI. Unlike the Claude/Codex/CodeBuddy
CLIs it has **no native stream-json output**: its ``-z / --oneshot`` mode prints
only the final response text to stdout.

This executor therefore:
  * builds ``hermes -z "<prompt>" --yolo [-m model] [--resume sid]``
  * reads the full stdout via ``communicate()`` (hermes returns one block)
  * wraps the block into a single CodeBuddy-style ``assistant`` event and
    yields it, so the shared CodeBuddy AG-UI adapter renders it as a normal
    text message (TextMessageStart / Content / End).

NOTE: This module must NOT depend on server-layer packages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Any, AsyncGenerator, List, Optional

from src.providers.base import BaseExecutor, ExecutorConfig, RequestContext

logger = logging.getLogger(__name__)


def _clean_default_model(value: Any) -> str:
    if not value:
        return ""
    return str(value).strip()


def _resolve_hermes_binary(configured: str = "hermes") -> str:
    """Resolve the hermes executable path.

    Hermes is typically installed under ~/.local/bin which is NOT on PATH for
    non-interactive / non-login shells (the executor runs via ``bash -c``).
    Prefer an explicit configured value; otherwise probe common locations.
    """
    if configured and "/" in configured:
        return configured  # already an absolute/relative path
    found = shutil.which(configured)
    if found:
        return found
    home = os.path.expanduser("~")
    for cand in (
        os.path.join(home, ".local", "bin", "hermes"),
        "/usr/local/bin/hermes",
        "/usr/bin/hermes",
    ):
        if os.path.exists(cand):
            return cand
    return configured  # let it fail loudly with the expected name


def _env_default_model() -> str:
    return _clean_default_model(os.getenv("HERMES_DEFAULT_MODEL")) or _clean_default_model(
        os.getenv("AGENT_NEXUS_HERMES_DEFAULT_MODEL")
    )


class HermesExecutorConfig(ExecutorConfig):
    """Hermes-specific configuration."""

    def __init__(
        self,
        timeout: float = 600.0,
        user_home_base: str = "/home",
        hermes_command: str = "hermes",
        default_model: str = "",
        **kwargs,
    ):
        super().__init__(timeout=timeout, user_home_base=user_home_base)
        self.hermes_command = hermes_command
        self.default_model = _clean_default_model(default_model) or _env_default_model()
        self.extra.update(kwargs)


class HermesCLIExecutor(BaseExecutor):
    """Hermes Agent CLI executor (one-shot block output)."""

    def __init__(self, config: Optional[HermesExecutorConfig] = None):
        if config is None:
            super().__init__(HermesExecutorConfig())
            return
        if isinstance(config, HermesExecutorConfig):
            super().__init__(config)
            return
        # Backward-compat: accept server settings-like objects.
        super().__init__(
            HermesExecutorConfig(
                timeout=getattr(config, "cli_timeout", 600.0),
                user_home_base=getattr(config, "user_home_base", "/home"),
                hermes_command=getattr(config, "hermes_command", "hermes"),
                default_model=getattr(config, "hermes_default_model", ""),
            )
        )

    @property
    def hermes_config(self) -> HermesExecutorConfig:
        return self.config  # type: ignore

    async def run_subprocess(
        self,
        final_cmd: List[str],
        timeout: Optional[float] = None,
    ) -> asyncio.subprocess.Process:
        """Start hermes in its own process group for clean timeout cleanup."""
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
        """Execute Hermes CLI and yield output (wrapped as a single assistant event)."""
        if isinstance(request, RequestContext):
            context = request
        else:
            context = RequestContext.from_request_model(request, exec_user)
        async for line in self._execute_internal(context, output_format=output_format):
            yield line

    def _build_command(self, context: RequestContext) -> List[str]:
        """Build the hermes oneshot command."""
        cleaned_content = context.content or ""
        model_param = (
            _clean_default_model(getattr(context, "model", None))
            or _clean_default_model(getattr(self.hermes_config, "default_model", ""))
            or _env_default_model()
            or None
        )
        cli_session_id = (getattr(context, "cli_session_id", None) or "").strip() or None
        configured = self.hermes_config.hermes_command
        # alias may be user-influenced; only honor a bare command name.
        raw_alias = (configured or "").strip()
        if "/" in raw_alias:
            configured = "hermes"
        cli_command = _resolve_hermes_binary(configured)
        cmd: List[str] = [cli_command]
        cmd.extend(["-z", cleaned_content])
        cmd.append("--yolo")
        if model_param:
            cmd.extend(["-m", model_param])
        if cli_session_id:
            cmd.extend(["--resume", cli_session_id])
        toolsets = (context.metadata or {}).get("toolsets") if context.metadata else None
        if toolsets:
            cmd.extend(["-t", str(toolsets)])
        return cmd

    async def _execute_internal(
        self,
        context: RequestContext,
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Run hermes, capture the full block, wrap and yield as one event."""
        cmd = self._build_command(context)
        exec_dir = self.resolve_exec_dir(context)
        final_cmd = self.wrap_command_for_user(cmd, exec_dir, context.exec_user)

        logger.info("hermes execute: %s", final_cmd[0] if final_cmd else "<?>")

        process = await self.run_subprocess(final_cmd, self.config.timeout)
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=self.config.timeout
            )
        except asyncio.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
            yield json.dumps({"type": "error", "message": "Hermes CLI timed out"})
            return

        text = (stdout_bytes or b"").decode("utf-8", errors="replace")
        if process.returncode not in (0, None):
            err_tail = (stderr_bytes or b"").decode("utf-8", errors="replace")[-500:]
            logger.warning("hermes exit %s; stderr: %s", process.returncode, err_tail)
            if not text.strip():
                yield json.dumps({"type": "error", "message": f"hermes exited with code {process.returncode}"})
                return

        payload = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": text}]},
        }
        yield json.dumps(payload, ensure_ascii=False)

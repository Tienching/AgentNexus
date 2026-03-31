"""CodeBuddy executor for the self-evolution system.

Executes evolution prompts by calling the `codebuddy` CLI in non-interactive
print mode, parsing the JSON output.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from src.nanobot.evolve.models import EvolutionConfig


@dataclass
class ExecutionResult:
    """Result from a CodeBuddy execution."""

    success: bool = False
    output: str = ""
    error: str | None = None
    exit_code: int = -1
    timed_out: bool = False
    duration_seconds: float = 0.0


class CodeBuddyExecutor:
    """Executes prompts via the codebuddy CLI."""

    def __init__(self, config: EvolutionConfig):
        self.config = config
        self._codebuddy_path = config.codebuddy_path or "codebuddy"

    async def execute(
        self,
        prompt: str,
        system_prompt: str = "",
        tools: str = "Read,Write,Edit,Bash,Grep,Glob",
        timeout: int | None = None,
        working_dir: str | None = None,
        max_turns: int | None = None,
    ) -> ExecutionResult:
        """Execute a prompt using codebuddy in non-interactive mode.

        Args:
            prompt: The task prompt to execute.
            system_prompt: System-level context (identity, personality, learnings).
            tools: Comma-separated list of tools to allow.
            timeout: Execution timeout in seconds.
            working_dir: Working directory for the agent.
            max_turns: Maximum number of agentic turns.

        Returns:
            ExecutionResult with output, errors, and metadata.
        """
        timeout = timeout or self.config.codebuddy_timeout
        working_dir = working_dir or self.config.working_dir

        # Build command
        cmd = [self._codebuddy_path, "--print", "--output-format", "text"]

        # Permission mode - bypass for automated evolution
        cmd.extend(["--permission-mode", "bypassPermissions"])

        # Restrict tools
        if tools:
            cmd.extend(["--tools", tools])

        # Model override
        if self.config.codebuddy_model:
            cmd.extend(["--model", self.config.codebuddy_model])

        # Max turns
        if max_turns:
            cmd.extend(["--max-turns", str(max_turns)])

        # System prompt via file (avoids shell escaping issues)
        sys_prompt_file = None
        if system_prompt:
            sys_prompt_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            )
            sys_prompt_file.write(system_prompt)
            sys_prompt_file.close()
            cmd.extend(["--system-prompt-file", sys_prompt_file.name])

        # The prompt itself as positional argument
        cmd.append(prompt)

        logger.info("CodeBuddy: executing with timeout={}s, working_dir={}", timeout, working_dir)
        logger.debug("CodeBuddy: command={}", " ".join(cmd[:6]) + "...")

        import time
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                elapsed = time.monotonic() - start
                logger.warning("CodeBuddy: timed out after {:.1f}s", elapsed)
                return ExecutionResult(
                    success=False,
                    output="",
                    error=f"Timed out after {timeout}s",
                    exit_code=-1,
                    timed_out=True,
                    duration_seconds=elapsed,
                )

            elapsed = time.monotonic() - start
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            err_text = stderr.decode("utf-8", errors="replace") if stderr else ""
            exit_code = proc.returncode or 0

            if exit_code != 0:
                logger.warning("CodeBuddy: exited with code {} after {:.1f}s", exit_code, elapsed)
                return ExecutionResult(
                    success=False,
                    output=output,
                    error=err_text or f"Exit code {exit_code}",
                    exit_code=exit_code,
                    duration_seconds=elapsed,
                )

            logger.info("CodeBuddy: completed in {:.1f}s ({} chars output)", elapsed, len(output))
            return ExecutionResult(
                success=True,
                output=output,
                exit_code=0,
                duration_seconds=elapsed,
            )

        except FileNotFoundError:
            return ExecutionResult(
                success=False,
                error=f"codebuddy not found at '{self._codebuddy_path}'. Is it installed?",
                exit_code=-1,
            )
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.error("CodeBuddy: unexpected error: {}", e)
            return ExecutionResult(
                success=False,
                error=str(e),
                exit_code=-1,
                duration_seconds=elapsed,
            )
        finally:
            # Cleanup temp file
            if sys_prompt_file:
                try:
                    Path(sys_prompt_file.name).unlink(missing_ok=True)
                except Exception:
                    pass

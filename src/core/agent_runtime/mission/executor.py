"""Single task executor for mission tasks - runs a role-specific subagent."""

from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from src.core.agent_runtime.mission.context import (
    check_context_budget,
    emergency_truncate,
    truncate_tool_result,
)
from src.core.agent_runtime.mission.guards import STABILITY_GUIDELINES, LoopGuard, SessionRepair
from src.core.agent_runtime.mission.roles import build_task_prompt
from src.core.agent_runtime.mission.types import Mission, Milestone, Task, TaskResult, TokenUsage, _now_ms

if TYPE_CHECKING:
    from src.core.agent_runtime.config.schema import ExecToolConfig, WebSearchConfig
    from src.core.agent_runtime.providers.base import LLMProvider


# ---------------------------------------------------------------------------
# Error classification & retry helpers (adapted from OpenFang retry.rs)
# ---------------------------------------------------------------------------

_TRANSIENT_ERRORS = (
    "rate_limit", "timeout", "connection", "502", "503", "429",
    "overloaded", "capacity", "temporarily", "retry",
)


def _classify_error(error: Exception) -> str:
    """Classify an error as 'transient' or 'permanent'.
    Transient errors are worth retrying with backoff.
    """
    err_str = str(error).lower()
    if any(keyword in err_str for keyword in _TRANSIENT_ERRORS):
        return "transient"
    if isinstance(error, (ConnectionError, TimeoutError, asyncio.TimeoutError)):
        return "transient"
    return "permanent"


def _backoff_delay(attempt: int, base: float = 1.0, max_delay: float = 30.0, jitter: float = 0.3) -> float:
    """Exponential backoff with jitter (adapted from OpenFang retry.rs).
    delay = min(base * 2^attempt, max_delay) * (1 + random() * jitter)
    """
    delay = min(base * (2 ** attempt), max_delay)
    delay *= (1 + random.random() * jitter)
    return delay


class MissionExecutor:
    """Executes a single mission task using a role-specific agent."""

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        model: str,
        web_search_config: Any = None,
        web_proxy: str | None = None,
        exec_config: Any = None,
        restrict_to_workspace: bool = False,
    ):
        self.provider = provider
        self.workspace = workspace
        self.model = model
        self.web_search_config = web_search_config
        self.web_proxy = web_proxy
        self.exec_config = exec_config
        self.restrict_to_workspace = restrict_to_workspace
        self._total_iterations = 0  # budget tracking across all tasks
        self._checkpoint_callback: Callable | None = None

    @property
    def total_iterations_used(self) -> int:
        return self._total_iterations

    def set_checkpoint_callback(self, callback: Callable | None) -> None:
        """Set a callback for mid-task checkpointing."""
        self._checkpoint_callback = callback

    def _build_tools(self) -> Any:
        """Build an isolated ToolRegistry for this task execution."""
        from src.core.agent_runtime.agent.skills import BUILTIN_SKILLS_DIR
        from src.core.agent_runtime.agent.tools.filesystem import (
            EditFileTool,
            ListDirTool,
            ReadFileTool,
            WriteFileTool,
        )
        from src.core.agent_runtime.agent.tools.registry import ToolRegistry
        from src.core.agent_runtime.agent.tools.shell import ExecTool
        from src.core.agent_runtime.agent.tools.web import WebFetchTool, WebSearchTool
        from src.core.agent_runtime.config.schema import ExecToolConfig, WebSearchConfig

        tools = ToolRegistry()
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        extra_read = [BUILTIN_SKILLS_DIR] if allowed_dir else None

        tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir, extra_allowed_dirs=extra_read))
        tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
        tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
        tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))

        exec_cfg = self.exec_config or ExecToolConfig()
        tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=exec_cfg.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
            path_append=exec_cfg.path_append,
        ))

        ws_config = self.web_search_config or WebSearchConfig()
        tools.register(WebSearchTool(config=ws_config, proxy=self.web_proxy))
        tools.register(WebFetchTool(proxy=self.web_proxy))

        return tools

    async def execute_task(
        self,
        task: Task,
        mission: Mission,
        milestone: Milestone,
        prior_results: dict[str, TaskResult] | None = None,
    ) -> TaskResult:
        """Execute a single task with a role-specific agent loop.

        Applies per-task timeout from mission.config.task_timeout_seconds.
        Raises asyncio.CancelledError if the mission is cancelled.
        """
        timeout = mission.config.task_timeout_seconds
        try:
            return await asyncio.wait_for(
                self._execute_task_inner(task, mission, milestone, prior_results),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return TaskResult(
                status="failed",
                output="",
                error=f"Task timed out after {timeout}s",
                started_at_ms=_now_ms(),
                completed_at_ms=_now_ms(),
            )

    async def _execute_task_inner(
        self,
        task: Task,
        mission: Mission,
        milestone: Milestone,
        prior_results: dict[str, TaskResult] | None = None,
    ) -> TaskResult:
        """Core task execution loop.

        Integrates:
        - Context window management (4-layer: truncate → guard → compact → emergency)
        - Loop guard (SHA256 dedup, ping-pong detection, budget circuit breaker)
        - Session repair (fix orphaned tool results before each LLM call)
        - Multi-model routing (per-task model override)
        - Stability guidelines (behavioral rules in system prompt)
        - Error classification & retry with exponential backoff
        - Graceful degradation for tool execution errors
        - Watchdog/heartbeat for slow iteration detection
        - Progress logging with throughput estimates
        - Mid-task checkpoint callback
        """
        from src.core.agent_runtime.utils.helpers import build_assistant_message

        start_ms = _now_ms()
        task_start_monotonic = time.monotonic()
        logger.info(
            "Mission [{}] executing task '{}' (role: {})",
            mission.id, task.title, task.role,
        )

        try:
            tools = self._build_tools()
            prompt = build_task_prompt(task, mission, milestone, prior_results)

            # Build system prompt with stability guidelines
            system_content = (
                f"# Mission Agent\n\nWorkspace: {self.workspace}\n\n"
                f"{prompt}"
                f"{STABILITY_GUIDELINES}"
            )

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": f"Execute the task: {task.title}\n\n{task.description}"},
            ]

            # Per-task model override (multi-model routing)
            # Priority: task.model > role_model_map[task.role] > self.model
            task_model = task.model
            if not task_model and mission.config.role_model_map:
                task_model = mission.config.role_model_map.get(task.role, "")
            task_model = task_model or self.model

            # Context window budget from mission config
            context_window = mission.config.context_window_tokens

            # Tool result truncation budget: ~30% of context window
            tool_result_budget = max(2000, context_window // 3)

            # Initialize loop guard for this task
            loop_guard = LoopGuard()

            max_iterations = task.max_iterations
            iteration = 0
            final_result: str | None = None
            task_tokens = TokenUsage()

            while iteration < max_iterations:
                iteration += 1
                self._total_iterations += 1
                iteration_start = time.monotonic()

                # Check budget
                budget = mission.config.max_total_iterations
                if budget > 0 and self._total_iterations > budget:
                    final_result = (
                        f"Mission iteration budget exhausted "
                        f"({self._total_iterations}/{budget} iterations used)."
                    )
                    break

                # Check for cancellation between iterations
                await asyncio.sleep(0)  # yield to event loop for cancel checks

                # Layer 4: Session repair — fix orphaned tool results
                messages = SessionRepair.repair(messages)

                # Layer 2: Context guard — compact if over 75% budget
                messages = check_context_budget(messages, max_tokens=context_window)

                # Layer 3: Emergency truncation — aggressive drop if over 90%
                messages = emergency_truncate(messages, max_tokens=context_window)

                # -------------------------------------------------------
                # Retry wrapper for LLM call with exponential backoff
                # -------------------------------------------------------
                llm_attempt = 0
                max_llm_retries = 3
                response = None
                while llm_attempt < max_llm_retries:
                    try:
                        response = await self.provider.chat_with_retry(
                            messages=messages,
                            tools=tools.get_definitions(),
                            model=task_model,
                        )
                        break  # Success
                    except Exception as llm_err:
                        llm_attempt += 1
                        err_class = _classify_error(llm_err)
                        if err_class == "permanent" or llm_attempt >= max_llm_retries:
                            raise  # Give up
                        delay = _backoff_delay(llm_attempt)
                        logger.warning(
                            "Mission [{}] task '{}': transient LLM error (attempt {}/{}), "
                            "retrying in {:.1f}s: {}",
                            mission.id, task.title, llm_attempt, max_llm_retries,
                            delay, llm_err,
                        )
                        await asyncio.sleep(delay)

                if response is None:
                    raise RuntimeError("LLM call failed after retries")

                # Accumulate token usage from this LLM call
                task_tokens.add(response.usage)
                task_tokens.llm_iterations = iteration

                if response.has_tool_calls:
                    tool_call_dicts = [
                        tc.to_openai_tool_call()
                        for tc in response.tool_calls
                    ]
                    messages.append(build_assistant_message(
                        response.content or "",
                        tool_calls=tool_call_dicts,
                        reasoning_content=response.reasoning_content,
                        thinking_blocks=response.thinking_blocks,
                    ))

                    results = await asyncio.gather(*(
                        tools.execute(tc.name, tc.arguments)
                        for tc in response.tool_calls
                    ), return_exceptions=True)

                    for tc, result in zip(response.tool_calls, results):
                        if isinstance(result, BaseException):
                            # Graceful degradation: don't crash the task, report the error
                            error_type = type(result).__name__
                            result = (
                                f"Tool execution failed: {error_type}: {result}\n\n"
                                f"This tool call encountered an error. Try a different approach "
                                f"or use an alternative tool."
                            )
                            logger.warning(
                                "Mission [{}] task '{}': tool '{}' failed: {}",
                                mission.id, task.title, tc.name, result,
                            )

                        # Loop guard check
                        verdict = loop_guard.check_call(tc.name, tc.arguments)
                        result_str = result if isinstance(result, str) else str(result)

                        if verdict == "block":
                            # Block the call — replace result with warning
                            result_str = loop_guard.get_warning_message(tc.name, tc.arguments)
                            logger.warning(
                                "Mission [{}] task '{}': Loop guard BLOCKED '{}'",
                                mission.id, task.title, tc.name,
                            )
                        elif verdict == "warn":
                            # Append warning to the result
                            warning = loop_guard.get_warning_message(tc.name, tc.arguments)
                            result_str = f"{result_str}\n\n⚠️ {warning}"

                        # Record outcome for loop guard (call + result pair tracking)
                        loop_guard.record_outcome(tc.name, tc.arguments, result_str[:500])

                        # Layer 1: Truncate tool result to fit context budget
                        result_str = truncate_tool_result(
                            result_str, max_tokens=tool_result_budget
                        )

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tc.name,
                            "content": result_str,
                        })
                else:
                    final_result = response.content
                    break

                # --- End-of-iteration watchdog & progress tracking ---

                # Watchdog: detect abnormally slow iterations
                iteration_elapsed = time.monotonic() - iteration_start
                if iteration_elapsed > 120:  # 2 minutes per iteration is suspicious
                    logger.warning(
                        "Mission [{}] task '{}': iteration {} took {:.0f}s (unusually slow)",
                        mission.id, task.title, iteration, iteration_elapsed,
                    )

                # Progress logging every 5 iterations
                if iteration % 5 == 0 and iteration > 0:
                    elapsed_s = (time.monotonic() - task_start_monotonic)
                    iters_per_min = (iteration / elapsed_s) * 60 if elapsed_s > 0 else 0
                    tokens_per_iter = task_tokens.total_tokens / iteration if iteration > 0 else 0
                    remaining_iters = max_iterations - iteration
                    eta_s = (remaining_iters / iters_per_min * 60) if iters_per_min > 0 else 0
                    logger.info(
                        "Mission [{}] task '{}': progress {}/{} iters ({:.1f} iter/min, "
                        "~{:.0f} tok/iter, ETA ~{:.0f}s)",
                        mission.id, task.title, iteration, max_iterations,
                        iters_per_min, tokens_per_iter, eta_s,
                    )

                # Mid-task checkpoint callback
                if self._checkpoint_callback and iteration % 5 == 0:
                    try:
                        self._checkpoint_callback()
                    except Exception:
                        pass  # Don't let checkpoint failures affect task execution

            if final_result is None:
                final_result = f"Task reached max iterations ({max_iterations}) without completing."

            end_ms = _now_ms()
            duration_s = (end_ms - start_ms) / 1000.0
            guard_stats = loop_guard.stats
            logger.info(
                "Mission [{}] task '{}' completed in {} iterations ({:.1f}s, {} tokens, "
                "{} tool calls, max repeat {})",
                mission.id, task.title, iteration, duration_s, task_tokens.total_tokens,
                guard_stats["total_calls"], guard_stats["max_repeat"],
            )

            return TaskResult(
                status="completed",
                output=final_result,
                started_at_ms=start_ms,
                completed_at_ms=end_ms,
                token_usage=task_tokens,
            )

        except asyncio.CancelledError:
            raise  # propagate cancellation
        except Exception as e:
            end_ms = _now_ms()
            logger.error("Mission [{}] task '{}' failed: {}", mission.id, task.title, e)
            return TaskResult(
                status="failed",
                output="",
                error=str(e),
                started_at_ms=start_ms,
                completed_at_ms=end_ms,
            )

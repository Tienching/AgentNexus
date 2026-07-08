"""Mission lifecycle runner - DAG scheduler for mission execution."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from src.core.agent_runtime.mission.types import Mission, Milestone, Task, TaskResult, _format_duration, _now_ms

if TYPE_CHECKING:
    from src.core.agent_runtime.bus.queue import MessageBus
    from src.core.agent_runtime.bus.events import InboundMessage, OutboundMessage
    from src.core.agent_runtime.mission.executor import MissionExecutor
    from src.core.agent_runtime.mission.planner import MissionPlanner
    from src.core.agent_runtime.mission.store import MissionFileStore


class MissionRunner:
    """Async engine that drives mission execution through milestones and tasks."""

    def __init__(
        self,
        executor: MissionExecutor,
        planner: MissionPlanner,
        store: MissionFileStore,
        bus: MessageBus | None = None,
        notify_callback: Callable[[str, Any], None] | None = None,
    ):
        self.executor = executor
        self.planner = planner
        self.store = store
        self.bus = bus
        self._notify_cb = notify_callback

    def rebind(
        self,
        *,
        store: MissionFileStore | None = None,
        planner: MissionPlanner | None = None,
        executor: MissionExecutor | None = None,
        workspace: Path | None = None,
    ) -> None:
        """Rebind runner dependencies when the active workspace changes."""
        if store is not None:
            self.store = store
        if planner is not None:
            self.planner = planner
        if executor is not None:
            self.executor = executor
        if workspace is not None:
            self.planner.workspace = workspace
            self.executor.workspace = workspace

    def _notify(self, message: str, origin: Any = None) -> None:
        """Send a progress notification if a callback is registered."""
        if self._notify_cb:
            try:
                self._notify_cb(message, origin)
            except Exception as e:
                logger.warning("Notification callback failed: {}", e)

    async def run_mission(self, mission: Mission) -> None:
        """Run a mission through all milestones, with optional timeout."""
        timeout = mission.config.mission_timeout_seconds
        if timeout and timeout > 0:
            try:
                await asyncio.wait_for(
                    self._run_mission_inner(mission), timeout=timeout
                )
            except asyncio.TimeoutError:
                mission.status = "failed"
                mission.error = f"Mission timed out after {timeout}s"
                mission.add_log(f"Mission timed out after {timeout}s")
                mission.updated_at_ms = _now_ms()
                self.store.update_mission(mission)
                self._notify(f"Mission '{mission.goal[:50]}' timed out after {timeout}s", mission.origin)
        else:
            await self._run_mission_inner(mission)

    async def _run_mission_inner(self, mission: Mission) -> None:
        """Core mission execution logic."""
        mission.status = "running"
        mission.add_log("Mission started")
        self.store.update_mission(mission)

        mission_start_mono = time.monotonic()

        try:
            # --- Milestone DAG scheduler ---
            # Support both sequential and parallel milestones via depends_on
            pending_milestones = set(
                m.id for m in mission.milestones if m.status in ("pending",)
            )
            completed_milestones: dict[str, bool] = {}  # id -> success

            # Pre-populate already-completed milestones (resume case)
            for ms in mission.milestones:
                if ms.status == "completed":
                    completed_milestones[ms.id] = True
                elif ms.status == "failed":
                    completed_milestones[ms.id] = False

            while pending_milestones:
                if mission.status != "running":
                    break

                ready = self._get_ready_milestones(mission, completed_milestones)
                ready = [m for m in ready if m.id in pending_milestones]

                if not ready:
                    if pending_milestones:
                        # Deadlock: pending milestones but nothing can run
                        logger.error("Mission [{}] milestone deadlock", mission.id)
                        mission.status = "failed"
                        mission.error = "Milestone dependency deadlock"
                        mission.add_log("Mission failed: milestone dependency deadlock")
                    break

                # Execute ready milestones concurrently
                if len(ready) == 1:
                    # Single milestone — run directly
                    ms = ready[0]
                    success = await self._execute_milestone_with_replan(mission, ms, mission_start_mono)
                    pending_milestones.discard(ms.id)
                    completed_milestones[ms.id] = success
                    if not success:
                        # Skip dependent milestones
                        self._skip_dependent_milestones(mission, ms.id, pending_milestones)
                        mission.status = "failed"
                        mission.error = f"Milestone '{ms.title}' failed"
                        mission.add_log(f"Mission failed: {mission.error}")
                        break
                else:
                    # Multiple milestones ready — run in parallel
                    results = await asyncio.gather(*[
                        self._execute_milestone_with_replan(mission, m, mission_start_mono)
                        for m in ready
                    ], return_exceptions=True)

                    failed = False
                    for ms, result in zip(ready, results):
                        pending_milestones.discard(ms.id)
                        if isinstance(result, Exception):
                            completed_milestones[ms.id] = False
                            self._skip_dependent_milestones(mission, ms.id, pending_milestones)
                            mission.status = "failed"
                            mission.error = f"Milestone '{ms.title}' failed: {result}"
                            mission.add_log(f"Mission failed: {mission.error}")
                            failed = True
                        else:
                            completed_milestones[ms.id] = bool(result)
                            if not result:
                                self._skip_dependent_milestones(mission, ms.id, pending_milestones)
                                mission.status = "failed"
                                mission.error = f"Milestone '{ms.title}' failed"
                                mission.add_log(f"Mission failed: {mission.error}")
                                failed = True
                    if failed:
                        break

                # Mission progress with ETA
                completed_ms = sum(1 for ms in mission.milestones if ms.status == "completed")
                total_ms = len(mission.milestones)
                if completed_ms > 0 and completed_ms < total_ms:
                    elapsed = time.monotonic() - mission_start_mono
                    avg_per_ms = elapsed / completed_ms
                    remaining = total_ms - completed_ms
                    eta = avg_per_ms * remaining
                    mission.add_log(
                        f"Mission progress: {completed_ms}/{total_ms} milestones "
                        f"(ETA ~{_format_duration(eta)})"
                    )

            if mission.status == "running":
                mission.status = "completed"
                mission.completed_at_ms = _now_ms()
                dur = mission.wall_clock_display
                tok = mission.token_usage
                mission.add_log(
                    f"Mission completed successfully "
                    f"({dur}, {tok.total_tokens} tokens, "
                    f"${tok.estimated_cost_usd:.4f} est. cost)"
                )
                self._notify(
                    f"Mission '{mission.goal[:50]}' completed "
                    f"({dur}, {tok.total_tokens} tokens)",
                    mission.origin,
                )

        except asyncio.CancelledError:
            mission.status = "cancelled"
            mission.add_log("Mission cancelled")
            raise
        except Exception as e:
            mission.status = "failed"
            mission.error = str(e)
            mission.add_log(f"Mission failed with error: {e}")
            logger.exception("Mission [{}] failed", mission.id)
        finally:
            mission.updated_at_ms = _now_ms()
            self.store.update_mission(mission)
            await self._notify_completion(mission)

    async def _execute_milestone_with_replan(
        self, mission: Mission, milestone: Milestone, mission_start_mono: float
    ) -> bool:
        """Execute a milestone with optional replanning on failure."""
        success = await self._execute_milestone(mission, milestone)

        if not success and milestone.status == "failed":
            mission.add_log(f"Milestone '{milestone.title}' failed, attempting replan...")
            error_ctx = self._get_milestone_errors(milestone)
            for task in milestone.tasks:
                if task.result and task.result.output:
                    error_ctx += f"\n\nTask '{task.title}' output:\n{task.result.output[:1000]}"
            new_ms = await self.planner.replan_milestone(milestone, error_ctx)

            if new_ms:
                idx = mission.milestones.index(milestone)
                new_ms.id = milestone.id
                # Preserve validation_commands from original milestone
                new_ms.validation_commands = milestone.validation_commands
                new_ms.validation_timeout = milestone.validation_timeout
                new_ms.depends_on = milestone.depends_on
                mission.milestones[idx] = new_ms
                mission.add_log(f"Replanned milestone '{new_ms.title}'")
                self.store.update_mission(mission)
                success = await self._execute_milestone(mission, new_ms)

        return success

    def _get_ready_milestones(
        self, mission: Mission, completed: dict[str, bool]
    ) -> list[Milestone]:
        """Get milestones whose dependencies are all successfully completed."""
        ready = []
        for m in mission.milestones:
            if m.status != "pending":
                continue
            if all(
                dep in completed and completed[dep]
                for dep in m.depends_on
            ):
                ready.append(m)
        return ready

    def _skip_dependent_milestones(
        self, mission: Mission, failed_id: str, pending: set[str]
    ) -> None:
        """Skip milestones that depend on a failed milestone (transitive)."""
        to_skip: set[str] = set()
        changed = True
        while changed:
            changed = False
            for ms in mission.milestones:
                if ms.id not in to_skip and ms.id in pending:
                    if failed_id in ms.depends_on or any(dep in to_skip for dep in ms.depends_on):
                        to_skip.add(ms.id)
                        changed = True

        for ms_id in to_skip:
            pending.discard(ms_id)
            for ms in mission.milestones:
                if ms.id == ms_id:
                    ms.status = "cancelled"
                    mission.add_log(f"Milestone '{ms.title}' cancelled (dependency failed)")
                    # Cancel all pending tasks
                    for task in ms.tasks:
                        if task.status == "pending":
                            task.status = "cancelled"

    async def _execute_milestone(self, mission: Mission, milestone: Milestone) -> bool:
        """Execute all tasks in a milestone respecting DAG dependencies."""
        milestone.status = "running"
        mission.add_log(f"Starting milestone: {milestone.title}")
        self.store.update_mission(mission)

        # Set up mid-task checkpoint callback for long-running tasks
        def _checkpoint():
            mission.updated_at_ms = _now_ms()
            self.store.update_mission(mission)

        self.executor.set_checkpoint_callback(_checkpoint)

        # Rebuild prior_results from already-completed tasks (resume intelligence)
        prior_results: dict[str, TaskResult] = {}
        for task in milestone.tasks:
            if task.status == "completed" and task.result:
                prior_results[task.id] = task.result

        pending_tasks = set(t.id for t in milestone.tasks if t.status == "pending")
        running_tasks: dict[str, asyncio.Task] = {}

        while pending_tasks or running_tasks:
            if mission.status != "running":
                # Cancel running tasks
                for at in running_tasks.values():
                    at.cancel()
                if running_tasks:
                    await asyncio.gather(*running_tasks.values(), return_exceptions=True)
                return False

            # Find tasks ready to run
            ready = self._get_ready_tasks(milestone, prior_results)
            ready = [t for t in ready if t.id in pending_tasks]

            # Limit parallel execution
            slots = mission.config.max_parallel_tasks - len(running_tasks)
            to_start = ready[:max(0, slots)]

            for task in to_start:
                pending_tasks.discard(task.id)
                task.status = "running"
                mission.add_log(f"  Task started: {task.title} (role: {task.role})")
                self.store.update_mission(mission)

                async_task = asyncio.create_task(
                    self.executor.execute_task(task, mission, milestone, prior_results)
                )
                running_tasks[task.id] = async_task

            if not running_tasks:
                if pending_tasks:
                    # Deadlock: pending tasks but nothing can run
                    logger.error("Mission [{}] milestone deadlock", mission.id)
                    milestone.status = "failed"
                    return False
                break

            # Wait for any task to complete
            done, _ = await asyncio.wait(
                running_tasks.values(),
                return_when=asyncio.FIRST_COMPLETED,
            )

            for completed_future in done:
                # Find which task ID this corresponds to
                task_id = None
                for tid, at in running_tasks.items():
                    if at is completed_future:
                        task_id = tid
                        break

                if task_id is None:
                    continue

                del running_tasks[task_id]

                try:
                    result = completed_future.result()
                except Exception as e:
                    result = TaskResult(
                        status="failed",
                        error=str(e),
                        started_at_ms=_now_ms(),
                        completed_at_ms=_now_ms(),
                    )

                # Update task
                task_obj = next(t for t in milestone.tasks if t.id == task_id)
                task_obj.result = result
                task_obj.status = result.status

                if result.status == "completed":
                    prior_results[task_id] = result
                    # Log with duration and token stats
                    dur = _format_duration(result.duration_seconds)
                    tok = result.token_usage.total_tokens
                    iters = result.token_usage.llm_iterations
                    mission.add_log(
                        f"  Task completed: {task_obj.title} "
                        f"({dur}, {iters} iters, {tok} tokens)"
                    )
                    # Aggregate token usage to mission level
                    mission.token_usage.merge(result.token_usage)
                    # Notify task completion
                    completed_count = sum(1 for t in milestone.tasks if t.status == "completed")
                    total_count = len(milestone.tasks)
                    self._notify(
                        f"Task '{task_obj.title}' completed "
                        f"({completed_count}/{total_count} in '{milestone.title}')",
                        mission.origin,
                    )
                elif result.status == "failed":
                    # Retry logic
                    if task_obj.result and task_obj.result.retry_count < task_obj.max_retries:
                        task_obj.result.retry_count += 1
                        task_obj.status = "pending"
                        pending_tasks.add(task_id)
                        mission.add_log(
                            f"  Task failed, retrying ({task_obj.result.retry_count}/{task_obj.max_retries}): "
                            f"{task_obj.title}"
                        )
                    else:
                        mission.add_log(f"  Task failed (no retries left): {task_obj.title}")
                        # Skip dependent tasks
                        self._skip_dependents(milestone, task_id, pending_tasks)

                self.store.update_mission(mission)

                # Progress reporting
                completed = sum(1 for t in milestone.tasks if t.status == "completed")
                total = len(milestone.tasks)
                pct = (completed / total * 100) if total > 0 else 0
                mission.add_log(
                    f"  Milestone progress: {completed}/{total} tasks ({pct:.0f}%)"
                )

        # Check milestone outcome
        failed_tasks = [t for t in milestone.tasks if t.status == "failed"]
        skipped_tasks = [t for t in milestone.tasks if t.status == "skipped"]

        if failed_tasks:
            milestone.status = "failed"
            return False

        # --- Programmatic milestone validation ---
        passed, output = await self._run_validation(milestone)
        if not passed:
            milestone.status = "failed"
            mission.add_log(f"Validation failed for milestone '{milestone.title}':\n{output[:500]}")
            self._notify(
                f"Milestone '{milestone.title}' validation failed",
                mission.origin,
            )
            return False

        milestone.status = "completed"
        mission.add_log(f"Milestone completed: {milestone.title}")
        ms_idx = next(i for i, m in enumerate(mission.milestones) if m.id == milestone.id)
        self._notify(
            f"Milestone '{milestone.title}' completed ({ms_idx + 1}/{len(mission.milestones)})",
            mission.origin,
        )
        return True

    async def _run_validation(self, milestone: Milestone) -> tuple[bool, str]:
        """Run milestone validation commands. Returns (passed, output)."""
        if not milestone.validation_commands:
            return True, ""

        workspace = str(getattr(self.executor, 'workspace', '.'))
        outputs: list[str] = []

        for cmd in milestone.validation_commands:
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    cwd=workspace,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=milestone.validation_timeout
                )
                stdout_str = stdout.decode(errors="replace") if stdout else ""
                stderr_str = stderr.decode(errors="replace") if stderr else ""
                outputs.append(f"$ {cmd}\n{stdout_str}")
                if proc.returncode != 0:
                    outputs.append(f"FAILED (exit {proc.returncode}): {stderr_str}")
                    return False, "\n".join(outputs)
            except asyncio.TimeoutError:
                outputs.append(f"TIMEOUT after {milestone.validation_timeout}s: {cmd}")
                return False, "\n".join(outputs)
            except Exception as e:
                outputs.append(f"ERROR running '{cmd}': {e}")
                return False, "\n".join(outputs)

        return True, "\n".join(outputs)

    def _get_ready_tasks(
        self, milestone: Milestone, prior_results: dict[str, TaskResult]
    ) -> list[Task]:
        """Find tasks whose dependencies are all completed."""
        ready = []
        completed_ids = set(prior_results.keys())

        for task in milestone.tasks:
            if task.status != "pending":
                continue
            if all(dep in completed_ids for dep in task.depends_on):
                ready.append(task)

        return ready

    def _skip_dependents(
        self, milestone: Milestone, failed_id: str, pending: set[str]
    ) -> None:
        """Skip all tasks that depend on a failed task."""
        to_skip = set()
        for task in milestone.tasks:
            if failed_id in task.depends_on and task.id in pending:
                to_skip.add(task.id)

        # Transitively skip
        changed = True
        while changed:
            changed = False
            for task in milestone.tasks:
                if task.id not in to_skip and task.id in pending:
                    if any(dep in to_skip for dep in task.depends_on):
                        to_skip.add(task.id)
                        changed = True

        for tid in to_skip:
            pending.discard(tid)
            for task in milestone.tasks:
                if task.id == tid:
                    task.status = "skipped"
                    break

    def _get_milestone_errors(self, milestone: Milestone) -> str:
        """Collect error information from failed tasks."""
        errors = []
        for task in milestone.tasks:
            if task.status == "failed" and task.result:
                errors.append(f"Task '{task.title}': {task.result.error or 'Unknown error'}")
        return "\n".join(errors) if errors else "Unknown error"

    async def _notify_completion(self, mission: Mission) -> None:
        """Send a completion notification via the message bus."""
        if not self.bus:
            return

        try:
            from src.core.agent_runtime.bus.events import InboundMessage

            status = "completed" if mission.status == "completed" else "failed"
            tok = mission.token_usage
            content = (
                f"[Mission '{mission.goal[:50]}' {status}]\n\n"
                f"Status: {mission.status}\n"
                f"Progress: {mission.completed_tasks}/{mission.total_tasks} tasks\n"
                f"Duration: {mission.wall_clock_display}\n"
                f"Tokens: {tok.total_tokens} (prompt: {tok.prompt_tokens}, "
                f"completion: {tok.completion_tokens})\n"
                f"Estimated cost: ${tok.estimated_cost_usd:.4f}\n"
            )
            if mission.error:
                content += f"Error: {mission.error}\n"

            msg = InboundMessage(
                channel="system",
                sender_id="mission",
                chat_id=f"{mission.origin.channel}:{mission.origin.chat_id}",
                content=content,
            )
            await self.bus.publish_inbound(msg)
        except Exception as e:
            logger.warning("Failed to send mission notification: {}", e)

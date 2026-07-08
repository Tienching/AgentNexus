"""Mission service - high-level API for mission management."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.core.agent_runtime.mission.executor import MissionExecutor
from src.core.agent_runtime.mission.planner import MissionPlanner
from src.core.agent_runtime.mission.runner import MissionRunner
from src.core.agent_runtime.mission.store import MissionFileStore
from src.core.agent_runtime.mission.types import Mission, MissionConfig, MissionOrigin, _format_duration, _now_ms

if TYPE_CHECKING:
    from src.core.agent_runtime.bus.queue import MessageBus
    from src.core.agent_runtime.config.schema import ExecToolConfig, WebSearchConfig
    from src.core.agent_runtime.providers.base import LLMProvider


class MissionService:
    """High-level API for creating and managing missions."""

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus | None = None,
        model: str | None = None,
        web_search_config: Any = None,
        web_proxy: str | None = None,
        exec_config: Any = None,
        restrict_to_workspace: bool = False,
    ):
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()

        self.store = MissionFileStore(workspace / "missions.json")
        self.planner = MissionPlanner(provider, self.model, workspace)
        self.executor = MissionExecutor(
            provider=provider,
            workspace=workspace,
            model=self.model,
            web_search_config=web_search_config,
            web_proxy=web_proxy,
            exec_config=exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )
        self.runner = MissionRunner(
            executor=self.executor,
            planner=self.planner,
            store=self.store,
            bus=bus,
            notify_callback=self._send_notification,
        )
        self._running_missions: dict[str, asyncio.Task] = {}

    def _send_notification(self, message: str, origin: Any = None) -> None:
        """Send a progress notification via the message bus."""
        if not self.bus or not origin:
            return
        try:
            from src.core.agent_runtime.bus.events import OutboundMessage
            out = OutboundMessage(
                channel=getattr(origin, "channel", "system"),
                chat_id=getattr(origin, "chat_id", "direct"),
                content=message,
            )
            # Schedule on the event loop (non-blocking)
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.bus.publish_outbound(out))
            except RuntimeError:
                pass  # No running event loop — skip notification
        except Exception as e:
            from loguru import logger
            logger.warning("Failed to send mission notification: {}", e)

    async def plan_mission(
        self,
        goal: str,
        mission_type: str | None = None,
        origin: MissionOrigin | None = None,
        config: MissionConfig | None = None,
        context: str = "",
    ) -> Mission:
        """Generate a mission plan without executing. Returns mission in 'planned' status.

        User can review the plan and then call confirm_mission() to start execution.
        """
        now = _now_ms()
        mission_id = f"msn-{str(uuid.uuid4())[:8]}"

        # Plan the mission
        logger.info("Planning mission [{}]: {}", mission_id, goal[:80])
        planned_type, milestones = await self.planner.plan_mission(goal, context)

        # Apply quality task injection
        cfg = config or MissionConfig()
        milestones = self.planner._inject_quality_tasks(
            milestones, cfg.auto_review, cfg.auto_test
        )

        mission = Mission(
            id=mission_id,
            goal=goal,
            mission_type=mission_type or planned_type,
            status="planned",
            milestones=milestones,
            origin=origin or MissionOrigin(),
            config=cfg,
            created_at_ms=now,
            updated_at_ms=now,
        )
        mission.add_log(f"Mission planned: {goal[:80]}")
        mission.add_log(f"Plan: {len(milestones)} milestones, {mission.total_tasks} tasks")
        mission.add_log("Awaiting approval — use confirm_mission() or /mission approve to start")

        self.store.add_mission(mission)

        logger.info(
            "Mission [{}] planned: {} milestones, {} tasks (awaiting approval)",
            mission_id, len(milestones), mission.total_tasks,
        )
        return mission

    async def confirm_mission(self, mission_id: str) -> bool:
        """Approve a planned mission and start execution.

        Returns True if the mission was approved and started, False otherwise.
        """
        mission = self.store.get_mission(mission_id)
        if not mission or mission.status != "planned":
            return False

        mission.status = "running"
        mission.add_log("Mission approved and started")
        mission.updated_at_ms = _now_ms()
        self.store.update_mission(mission)

        # Launch runner as background task
        self._launch_mission(mission)

        logger.info("Mission [{}] approved and started", mission_id)
        return True

    def _launch_mission(self, mission: Mission) -> None:
        """Launch a mission runner as a background task."""
        bg_task = asyncio.create_task(self._run_and_cleanup(mission))
        self._running_missions[mission.id] = bg_task

    async def start_mission(
        self,
        goal: str,
        mission_type: str | None = None,
        origin: MissionOrigin | None = None,
        config: MissionConfig | None = None,
        context: str = "",
    ) -> Mission:
        """Create and immediately start a mission (backward-compatible).

        Combines plan_mission() + confirm_mission() in one step.
        """
        mission = await self.plan_mission(
            goal=goal, mission_type=mission_type, origin=origin,
            config=config, context=context,
        )
        # Immediately approve and start
        mission.status = "running"
        mission.add_log("Mission auto-approved and started (direct start)")
        mission.updated_at_ms = _now_ms()
        self.store.update_mission(mission)
        self._launch_mission(mission)

        logger.info(
            "Mission [{}] started: {} milestones, {} tasks",
            mission.id, len(mission.milestones), mission.total_tasks,
        )
        return mission

    async def _run_and_cleanup(self, mission: Mission) -> None:
        """Run mission and cleanup when done."""
        try:
            await self.runner.run_mission(mission)
        except asyncio.CancelledError:
            mission.status = "cancelled"
            mission.add_log("Mission cancelled")
            self.store.update_mission(mission)
        except Exception as e:
            mission.status = "failed"
            mission.error = str(e)
            mission.add_log(f"Mission failed with error: {e}")
            mission.updated_at_ms = _now_ms()
            self.store.update_mission(mission)
            logger.exception("Mission [{}] runner error", mission.id)
        self._running_missions.pop(mission.id, None)

    async def pause_mission(self, mission_id: str) -> bool:
        """Pause a running mission."""
        mission = self.store.get_mission(mission_id)
        if not mission or mission.status != "running":
            return False

        mission.status = "paused"
        mission.add_log("Mission paused")
        self.store.update_mission(mission)

        # Cancel the runner task
        if task := self._running_missions.pop(mission_id, None):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        return True

    async def resume_mission(self, mission_id: str) -> bool:
        """Resume a paused mission."""
        mission = self.store.get_mission(mission_id)
        if not mission or mission.status != "paused":
            return False

        mission.status = "running"
        mission.add_log("Mission resumed")
        self.store.update_mission(mission)

        bg_task = asyncio.create_task(self._run_and_cleanup(mission))
        self._running_missions[mission_id] = bg_task

        return True

    async def cancel_mission(self, mission_id: str) -> bool:
        """Cancel a mission."""
        mission = self.store.get_mission(mission_id)
        if not mission or mission.status in ("completed", "cancelled"):
            return False

        mission.status = "cancelled"
        mission.add_log("Mission cancelled by user")
        mission.updated_at_ms = _now_ms()
        self.store.update_mission(mission)

        if task := self._running_missions.pop(mission_id, None):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        return True

    def get_mission(self, mission_id: str) -> Mission | None:
        return self.store.get_mission(mission_id)

    def list_missions(self, include_completed: bool = True) -> list[Mission]:
        return self.store.list_missions(include_completed)

    def format_status(self, mission: Mission) -> str:
        """Format mission status as markdown with timing and cost info."""
        status_emoji = {
            "planned": "📋",
            "planning": "🔄",
            "running": "🚀",
            "paused": "⏸️",
            "completed": "✅",
            "failed": "❌",
            "cancelled": "🚫",
        }

        tok = mission.token_usage
        lines = [
            f"## {status_emoji.get(mission.status, '❓')} Mission: {mission.goal[:60]}",
            f"**ID:** `{mission.id}` | **Type:** {mission.mission_type} | **Status:** {mission.status}",
            f"**Progress:** {mission.completed_tasks}/{mission.total_tasks} tasks ({mission.progress_pct:.0f}%)",
            f"**Duration:** {mission.wall_clock_display}",
            f"**Tokens:** {tok.total_tokens:,} (prompt: {tok.prompt_tokens:,}, completion: {tok.completion_tokens:,})",
            f"**LLM Iterations:** {tok.llm_iterations} | **Est. Cost:** ${tok.estimated_cost_usd:.4f}",
            "",
        ]

        if mission.error:
            lines.append(f"**Error:** {mission.error}")
            lines.append("")

        for ms in mission.milestones:
            ms_emoji = {"pending": "⬜", "running": "🔵", "completed": "✅", "failed": "❌", "cancelled": "🚫"}
            lines.append(f"### {ms_emoji.get(ms.status, '❓')} {ms.title}")
            for task in ms.tasks:
                t_emoji = {
                    "pending": "⬜", "running": "🔵", "completed": "✅",
                    "failed": "❌", "skipped": "⏭️", "cancelled": "🚫",
                }
                role_tag = f"[{task.role}]"
                # Show per-task timing and tokens if available
                task_detail = ""
                if task.result and task.result.status == "completed":
                    dur = _format_duration(task.result.duration_seconds)
                    ttok = task.result.token_usage.total_tokens
                    iters = task.result.token_usage.llm_iterations
                    task_detail = f" ({dur}, {iters}i, {ttok}tok)"
                elif task.result and task.result.status == "failed" and task.result.error:
                    task_detail = f" ⚠ {task.result.error[:40]}"
                lines.append(f"  {t_emoji.get(task.status, '❓')} {role_tag} {task.title}{task_detail}")

        return "\n".join(lines)

    def format_list(self, missions: list[Mission]) -> str:
        """Format a list of missions for display."""
        if not missions:
            return "No missions found."

        lines = ["## Missions\n"]
        for m in missions:
            emoji = {"planning": "🔄", "running": "🚀", "paused": "⏸️", "completed": "✅", "failed": "❌", "cancelled": "🚫"}
            dur = m.wall_clock_display
            tok = m.token_usage.total_tokens
            lines.append(
                f"- {emoji.get(m.status, '❓')} `{m.id}` — {m.goal[:50]} "
                f"({m.completed_tasks}/{m.total_tasks} tasks, {m.status}, {dur}, {tok}tok)"
            )
        return "\n".join(lines)

    async def resume_interrupted(self) -> None:
        """On startup, resume missions that were running."""
        missions = self.store.list_missions(include_completed=False)
        for mission in missions:
            if mission.status == "running":
                logger.info("Resuming interrupted mission [{}]", mission.id)
                bg_task = asyncio.create_task(self._run_and_cleanup(mission))
                self._running_missions[mission.id] = bg_task

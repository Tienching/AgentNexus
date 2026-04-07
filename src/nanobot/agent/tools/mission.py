"""Mission tool for LLM to create and manage missions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from src.nanobot.mission.service import MissionService


class MissionTool(Tool):
    """Tool for the LLM to create and manage long-running missions."""

    def __init__(self, service: MissionService):
        self._service = service
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        self._origin_channel = channel
        self._origin_chat_id = chat_id

    @property
    def name(self) -> str:
        return "mission"

    @property
    def description(self) -> str:
        return (
            "Create and manage long-running autonomous missions. "
            "Missions decompose complex goals into milestones and tasks, "
            "executed by specialized agents (planner, coder, reviewer, tester). "
            "Use this for complex, multi-step tasks that benefit from structured execution."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "plan", "approve", "status", "list", "cancel"],
                    "description": "Action to perform. 'plan' creates a plan for review; 'approve' starts a planned mission; 'create' plans and immediately starts.",
                },
                "goal": {
                    "type": "string",
                    "description": "Mission goal (required for create)",
                },
                "mission_type": {
                    "type": "string",
                    "enum": [
                        "feature_impl", "bug_fix", "code_migration",
                        "refactor", "research", "documentation", "custom",
                    ],
                    "description": "Type of mission (optional, auto-detected if omitted)",
                },
                "mission_id": {
                    "type": "string",
                    "description": "Mission ID (for status/cancel)",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context for planning (optional)",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        goal: str | None = None,
        mission_type: str | None = None,
        mission_id: str | None = None,
        context: str | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            if action == "create":
                if not goal:
                    return "Error: 'goal' is required for creating a mission."
                from src.nanobot.mission.types import MissionOrigin

                origin = MissionOrigin(
                    channel=self._origin_channel,
                    chat_id=self._origin_chat_id,
                )
                mission = await self._service.start_mission(
                    goal=goal,
                    mission_type=mission_type,
                    origin=origin,
                    context=context or "",
                )
                return (
                    f"Mission created successfully!\n\n"
                    f"ID: {mission.id}\n"
                    f"Goal: {mission.goal}\n"
                    f"Type: {mission.mission_type}\n"
                    f"Milestones: {len(mission.milestones)}\n"
                    f"Total Tasks: {mission.total_tasks}\n\n"
                    f"The mission is now running in the background. "
                    f"Use action='status' with mission_id='{mission.id}' to check progress."
                )

            elif action == "plan":
                if not goal:
                    return "Error: 'goal' is required for planning a mission."
                from src.nanobot.mission.types import MissionOrigin

                origin = MissionOrigin(
                    channel=self._origin_channel,
                    chat_id=self._origin_chat_id,
                )
                mission = await self._service.plan_mission(
                    goal=goal,
                    mission_type=mission_type,
                    origin=origin,
                    context=context or "",
                )
                plan_lines = []
                for ms in mission.milestones:
                    plan_lines.append(f"  {ms.title} ({len(ms.tasks)} tasks)")
                    for t in ms.tasks:
                        plan_lines.append(f"    - [{t.role}] {t.title}")
                plan_summary = "\n".join(plan_lines)
                return (
                    f"Mission planned (awaiting approval)!\n\n"
                    f"ID: {mission.id}\n"
                    f"Goal: {mission.goal}\n"
                    f"Type: {mission.mission_type}\n"
                    f"Plan:\n{plan_summary}\n\n"
                    f"Use action='approve' with mission_id='{mission.id}' to start execution."
                )

            elif action == "approve":
                if not mission_id:
                    return "Error: 'mission_id' is required for approving a mission."
                ok = await self._service.confirm_mission(mission_id)
                if ok:
                    return f"Mission '{mission_id}' approved and started!"
                return f"Cannot approve mission '{mission_id}'. It may not exist or is not in 'planned' status."

            elif action == "status":
                if mission_id:
                    mission = self._service.get_mission(mission_id)
                    if not mission:
                        return f"Mission '{mission_id}' not found."
                    return self._service.format_status(mission)
                else:
                    missions = self._service.list_missions()
                    return self._service.format_list(missions)

            elif action == "list":
                missions = self._service.list_missions()
                return self._service.format_list(missions)

            elif action == "cancel":
                if not mission_id:
                    return "Error: 'mission_id' is required for cancelling a mission."
                ok = await self._service.cancel_mission(mission_id)
                return f"Mission '{mission_id}' cancelled." if ok else f"Cannot cancel mission '{mission_id}'."

            else:
                return f"Unknown action: {action}. Use create, plan, approve, status, list, or cancel."

        except Exception as e:
            return f"Mission error: {e}"

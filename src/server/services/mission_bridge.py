# -*- coding: utf-8 -*-
"""Bridge between agent-nexus and nanobot's mission system.

Singleton service that lazily initializes nanobot's MissionService,
exposing a simplified async API for the mission skill CLI and REST router.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class MissionBridge:
    """Bridge to nanobot's MissionService.

    Usage::

        bridge = MissionBridge.get_instance()
        mission = await bridge.plan("Implement JWT auth", workspace="/tmp/test")
    """

    _instance: MissionBridge | None = None

    @classmethod
    def get_instance(cls) -> MissionBridge:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def __init__(self) -> None:
        self._service: Any = None  # nanobot.mission.service.MissionService

    @property
    def service(self) -> Any:
        """Lazily create and return the MissionService."""
        if self._service is None:
            self._service = self._create_service()
        return self._service

    def _create_service(self) -> Any:
        """Create MissionService with OpenAI-compatible provider."""
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider
        from nanobot.mission.service import MissionService

        api_key = os.environ.get("OPENAI_API_KEY", "")
        api_base = os.environ.get("OPENAI_API_BASE", "")
        model = os.environ.get("NANOBOT_MODEL", "gpt-4o")
        workspace_str = os.environ.get("NANOBOT_WORKSPACE", "")
        workspace = Path(workspace_str) if workspace_str else Path.home() / "Projects"

        provider = OpenAICompatProvider(
            api_key=api_key,
            api_base=api_base,
            default_model=model,
        )

        return MissionService(
            provider=provider,
            workspace=workspace,
            model=model,
        )

    # ── High-level API ─────────────────────────────────────────────────

    async def plan(
        self,
        goal: str,
        workspace: str | None = None,
        context: str = "",
    ) -> dict:
        """Plan a mission (status=planned). Returns dict representation."""
        svc = self.service
        # Override workspace if provided
        if workspace:
            svc.store = type(svc.store)(Path(workspace) / "missions.json")
            svc.planner.workspace = Path(workspace)
            svc.executor.workspace = Path(workspace)

        mission = await svc.plan_mission(goal=goal, context=context)
        return self._mission_to_dict(mission)

    async def start(
        self,
        goal: str,
        workspace: str | None = None,
        context: str = "",
    ) -> dict:
        """Plan + auto-approve + start execution. Returns dict."""
        svc = self.service
        if workspace:
            svc.store = type(svc.store)(Path(workspace) / "missions.json")
            svc.planner.workspace = Path(workspace)
            svc.executor.workspace = Path(workspace)

        mission = await svc.start_mission(goal=goal, context=context)
        return self._mission_to_dict(mission)

    async def approve(self, mission_id: str) -> bool:
        """Approve a planned mission and start execution."""
        return await self.service.confirm_mission(mission_id)

    async def status(self, mission_id: str) -> str | None:
        """Get formatted status for a mission."""
        mission = self.service.get_mission(mission_id)
        if not mission:
            return None
        return self.service.format_status(mission)

    async def list_missions(self, include_completed: bool = True) -> str:
        """Get formatted list of all missions."""
        missions = self.service.list_missions(include_completed=include_completed)
        return self.service.format_list(missions)

    async def cancel(self, mission_id: str) -> bool:
        """Cancel a mission."""
        return await self.service.cancel_mission(mission_id)

    async def pause(self, mission_id: str) -> bool:
        """Pause a running mission."""
        return await self.service.pause_mission(mission_id)

    async def resume(self, mission_id: str) -> bool:
        """Resume a paused mission."""
        return await self.service.resume_mission(mission_id)

    def get_mission_raw(self, mission_id: str) -> Any:
        """Get raw Mission object (for REST API serialization)."""
        return self.service.get_mission(mission_id)

    def get_log(self, mission_id: str, tail: int | None = None) -> list[str]:
        """Get mission log entries."""
        mission = self.service.get_mission(mission_id)
        if not mission:
            return []
        entries = mission.log
        if tail and tail > 0:
            entries = entries[-tail:]
        return entries

    # ── Serialization helpers ──────────────────────────────────────────

    @staticmethod
    def _mission_to_dict(mission: Any) -> dict:
        """Convert a Mission dataclass to a JSON-serializable dict."""
        milestones = []
        for ms in mission.milestones:
            tasks = []
            for t in ms.tasks:
                task_dict: dict[str, Any] = {
                    "id": t.id,
                    "title": t.title,
                    "description": t.description,
                    "role": t.role,
                    "status": t.status,
                    "depends_on": t.depends_on,
                }
                if t.result:
                    task_dict["result"] = {
                        "status": t.result.status,
                        "error": t.result.error,
                        "duration_seconds": t.result.duration_seconds,
                        "token_usage": {
                            "total_tokens": t.result.token_usage.total_tokens,
                            "llm_iterations": t.result.token_usage.llm_iterations,
                        },
                    }
                tasks.append(task_dict)

            milestones.append({
                "id": ms.id,
                "title": ms.title,
                "description": ms.description,
                "status": ms.status,
                "depends_on": ms.depends_on,
                "tasks": tasks,
            })

        return {
            "id": mission.id,
            "goal": mission.goal,
            "mission_type": mission.mission_type,
            "status": mission.status,
            "milestones": milestones,
            "total_tasks": mission.total_tasks,
            "completed_tasks": mission.completed_tasks,
            "progress_pct": mission.progress_pct,
            "wall_clock_display": mission.wall_clock_display,
            "token_usage": {
                "total_tokens": mission.token_usage.total_tokens,
                "prompt_tokens": mission.token_usage.prompt_tokens,
                "completion_tokens": mission.token_usage.completion_tokens,
                "llm_iterations": mission.token_usage.llm_iterations,
                "estimated_cost_usd": mission.token_usage.estimated_cost_usd,
            },
            "error": mission.error,
            "created_at_ms": mission.created_at_ms,
            "updated_at_ms": mission.updated_at_ms,
        }

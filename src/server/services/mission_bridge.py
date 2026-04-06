# -*- coding: utf-8 -*-
"""Bridge between agent-nexus and nanobot's mission system.

Singleton bridge that lazily initializes workspace-scoped MissionService
instances, exposing a simplified async API for the mission skill CLI and
REST router.
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
        self._services: dict[Path, Any] = {}

    @property
    def service(self) -> Any:
        """Lazily create and return the default MissionService."""
        return self._get_service()

    def _default_workspace(self) -> Path:
        workspace_str = os.environ.get("NANOBOT_WORKSPACE", "")
        workspace = Path(workspace_str) if workspace_str else Path.home() / "Projects"
        return workspace.expanduser().resolve(strict=False)

    def _normalize_workspace(self, workspace: str | Path | None = None) -> Path:
        if workspace is None or workspace == "":
            return self._default_workspace()
        return Path(workspace).expanduser().resolve(strict=False)

    def _create_service(self, workspace: Path | None = None) -> Any:
        """Create MissionService with OpenAI-compatible provider."""
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider
        from nanobot.mission.service import MissionService

        api_key = os.environ.get("OPENAI_API_KEY", "")
        api_base = os.environ.get("OPENAI_API_BASE", "")
        model = os.environ.get("NANOBOT_MODEL", "gpt-4o")
        workspace = self._default_workspace() if workspace is None else workspace

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

    def _get_service(self, workspace: str | Path | None = None) -> Any:
        workspace_path = self._normalize_workspace(workspace)
        service = self._services.get(workspace_path)
        if service is None:
            service = self._create_service(workspace_path)
            self._services[workspace_path] = service
        return service

    # ── High-level API ─────────────────────────────────────────────────

    async def plan(
        self,
        goal: str,
        workspace: str | None = None,
        context: str = "",
    ) -> dict[str, Any]:
        """Plan a mission (status=planned). Returns detail payload."""
        svc = self._get_service(workspace)
        mission = await svc.plan_mission(goal=goal, context=context)
        return self.serialize_mission_detail(mission)

    async def start(
        self,
        goal: str,
        workspace: str | None = None,
        context: str = "",
    ) -> dict[str, Any]:
        """Plan + auto-approve + start execution. Returns detail payload."""
        svc = self._get_service(workspace)
        mission = await svc.start_mission(goal=goal, context=context)
        return self.serialize_mission_detail(mission)

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
        """Get raw Mission object."""
        return self.service.get_mission(mission_id)

    def get_mission_detail(self, mission_id: str) -> dict[str, Any] | None:
        """Get serialized mission detail payload."""
        mission = self.get_mission_raw(mission_id)
        if not mission:
            return None
        return self.serialize_mission_detail(mission)

    async def get_status_payload(self, mission_id: str) -> dict[str, Any] | None:
        """Get response payload for the mission status endpoint."""
        text = await self.status(mission_id)
        if text is None:
            return None
        return {"mission_id": mission_id, "status_text": text}

    async def get_mission_list_payload(self, include_completed: bool = True) -> dict[str, Any]:
        """Get response payload for the mission list endpoint."""
        text = await self.list_missions(include_completed=include_completed)
        return {"missions_text": text}

    def get_log(self, mission_id: str, tail: int | None = None) -> list[str]:
        """Get mission log entries."""
        mission = self.service.get_mission(mission_id)
        if not mission:
            return []
        return self._slice_log_entries(mission.log, tail)

    def get_mission_log_payload(self, mission_id: str, tail: int | None = None) -> dict[str, Any] | None:
        """Get response payload for the mission log endpoint."""
        mission = self.service.get_mission(mission_id)
        if not mission:
            return None

        entries = self._slice_log_entries(mission.log, tail)
        return {
            "mission_id": mission_id,
            "entries": entries,
            "count": len(entries),
        }

    # ── Serialization helpers ──────────────────────────────────────────

    @staticmethod
    def _slice_log_entries(entries: list[str], tail: int | None = None) -> list[str]:
        if tail and tail > 0:
            return entries[-tail:]
        return entries

    @staticmethod
    def serialize_mission_detail(mission: Any) -> dict[str, Any]:
        """Convert a Mission dataclass to a JSON-serializable detail payload."""
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

    @staticmethod
    def _mission_to_dict(mission: Any) -> dict[str, Any]:
        """Backward-compatible alias for mission detail serialization."""
        return MissionBridge.serialize_mission_detail(mission)

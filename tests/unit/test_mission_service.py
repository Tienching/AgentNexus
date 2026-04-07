"""Regression tests for mission service failure persistence."""

from __future__ import annotations

import pytest

import src.nanobot.mission.service as mission_service_module
from src.nanobot.mission.service import MissionService
from src.nanobot.mission.types import Mission


class StubProvider:
    def get_default_model(self) -> str:
        return "stub-model"


@pytest.mark.asyncio
async def test_run_and_cleanup_persists_unexpected_runner_failures(tmp_path, monkeypatch: pytest.MonkeyPatch):
    service = MissionService(provider=StubProvider(), workspace=tmp_path)
    mission = Mission(
        id="msn-runner-failure",
        goal="Persist mission failure state",
        status="running",
        created_at_ms=1111,
        updated_at_ms=1111,
    )
    service.store.add_mission(mission)
    service._running_missions[mission.id] = object()

    async def raise_runner_failure(_mission: Mission) -> None:
        raise RuntimeError("unexpected runner failure")

    original_update_mission = service.store.update_mission

    def update_mission_and_assert_tracked(updated_mission: Mission) -> None:
        assert mission.id in service._running_missions
        original_update_mission(updated_mission)

    monkeypatch.setattr(service.runner, "run_mission", raise_runner_failure)
    monkeypatch.setattr(service.store, "update_mission", update_mission_and_assert_tracked)
    monkeypatch.setattr(mission_service_module, "_now_ms", lambda: 2222)

    await service._run_and_cleanup(mission)

    stored = service.get_mission(mission.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error == "unexpected runner failure"
    assert stored.updated_at_ms == 2222
    assert any(
        "Mission failed with error: unexpected runner failure" in entry
        for entry in stored.log
    )
    assert mission.id not in service._running_missions

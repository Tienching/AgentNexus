# -*- coding: utf-8 -*-
"""Router-focused tests for nexus mission endpoints."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.routers import nexus_missions
from src.server.routers.nexus_auth import verify_nexus_auth


MISSION_DETAIL = {
    "id": "msn-123",
    "goal": "Ship the mission router refactor",
    "mission_type": "general",
    "status": "running",
    "milestones": [
        {
            "id": "m-001",
            "title": "Plan",
            "description": "Build the response models",
            "status": "running",
            "depends_on": [],
            "tasks": [
                {
                    "id": "t-001",
                    "title": "Replace private bridge accessor",
                    "description": "Use public serialization helpers",
                    "role": "coder",
                    "status": "completed",
                    "depends_on": [],
                    "result": {
                        "status": "completed",
                        "error": None,
                        "duration_seconds": 1.25,
                        "token_usage": {
                            "total_tokens": 21,
                            "llm_iterations": 2,
                        },
                    },
                }
            ],
        }
    ],
    "total_tasks": 1,
    "completed_tasks": 1,
    "progress_pct": 100.0,
    "wall_clock_display": "1.2s",
    "token_usage": {
        "total_tokens": 34,
        "prompt_tokens": 13,
        "completion_tokens": 21,
        "llm_iterations": 3,
        "estimated_cost_usd": 0.000038,
    },
    "error": None,
    "created_at_ms": 1000,
    "updated_at_ms": 2500,
}

MISSION_STATUS = {
    "mission_id": "msn-123",
    "status_text": "**Status:** running",
}

MISSION_LIST = {
    "missions_text": "- msn-123 | running | Ship the mission router refactor",
}

MISSION_LOG = {
    "mission_id": "msn-123",
    "entries": [
        "[12:00:00] Planned mission",
        "[12:00:01] Started execution",
    ],
    "count": 2,
}


class StubMissionBridge:
    def __init__(self) -> None:
        self.last_include_completed: bool | None = None

    async def plan(self, goal: str, workspace: str | None = None, context: str = "") -> dict:
        payload = deepcopy(MISSION_DETAIL)
        payload["goal"] = goal
        return payload

    async def start(self, goal: str, workspace: str | None = None, context: str = "") -> dict:
        payload = await self.plan(goal=goal, workspace=workspace, context=context)
        payload["status"] = "running"
        return payload

    async def approve(self, mission_id: str) -> bool:
        return mission_id != "missing-mission"

    def get_mission_detail(self, mission_id: str) -> dict | None:
        if mission_id == "missing-mission":
            return None
        return deepcopy(MISSION_DETAIL)

    async def get_status_payload(self, mission_id: str) -> dict | None:
        if mission_id == "missing-mission":
            return None
        return deepcopy(MISSION_STATUS)

    async def get_mission_list_payload(self, include_completed: bool = True) -> dict:
        self.last_include_completed = include_completed
        return deepcopy(MISSION_LIST)

    async def cancel(self, mission_id: str) -> bool:
        return mission_id != "missing-mission"

    async def pause(self, mission_id: str) -> bool:
        return mission_id != "missing-mission"

    async def resume(self, mission_id: str) -> bool:
        return mission_id != "missing-mission"

    def get_mission_log_payload(self, mission_id: str, tail: int | None = None) -> dict | None:
        if mission_id == "missing-mission":
            return None

        payload = deepcopy(MISSION_LOG)
        if tail and tail > 0:
            payload["entries"] = payload["entries"][-tail:]
            payload["count"] = len(payload["entries"])
        return payload


@pytest.fixture
def bridge() -> StubMissionBridge:
    return StubMissionBridge()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, bridge: StubMissionBridge):
    app = FastAPI()
    app.include_router(nexus_missions.router)
    app.dependency_overrides[verify_nexus_auth] = lambda: True

    monkeypatch.setattr(nexus_missions, "_get_bridge", lambda: bridge)
    monkeypatch.setattr(nexus_missions, "_check_enabled", lambda: None)

    with TestClient(app) as test_client:
        yield test_client


def test_create_mission_returns_mission_detail_payload(client: TestClient):
    response = client.post("/api/nexus/missions", json={"goal": "Ship the mission router refactor"})

    assert response.status_code == 200
    assert response.json() == MISSION_DETAIL


def test_get_mission_returns_detail_payload(client: TestClient):
    response = client.get("/api/nexus/missions/msn-123")

    assert response.status_code == 200
    assert response.json() == MISSION_DETAIL


def test_get_mission_returns_404_when_missing(client: TestClient):
    response = client.get("/api/nexus/missions/missing-mission")

    assert response.status_code == 404
    assert response.json() == {"detail": "Mission missing-mission not found"}


def test_get_mission_status_returns_status_payload(client: TestClient):
    response = client.get("/api/nexus/missions/msn-123/status")

    assert response.status_code == 200
    assert response.json() == MISSION_STATUS


def test_get_mission_status_returns_404_when_missing(client: TestClient):
    response = client.get("/api/nexus/missions/missing-mission/status")

    assert response.status_code == 404
    assert response.json() == {"detail": "Mission missing-mission not found"}


def test_list_missions_returns_list_payload(client: TestClient, bridge: StubMissionBridge):
    response = client.get("/api/nexus/missions?include_completed=true")

    assert response.status_code == 200
    assert response.json() == MISSION_LIST
    assert bridge.last_include_completed is True


def test_get_mission_log_returns_log_payload(client: TestClient):
    response = client.get("/api/nexus/missions/msn-123/log?tail=1")

    assert response.status_code == 200
    assert response.json() == {
        "mission_id": "msn-123",
        "entries": ["[12:00:01] Started execution"],
        "count": 1,
    }


def test_get_mission_log_returns_404_when_missing(client: TestClient):
    response = client.get("/api/nexus/missions/missing-mission/log")

    assert response.status_code == 404
    assert response.json() == {"detail": "Mission missing-mission not found"}

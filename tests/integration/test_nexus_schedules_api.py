"""Regression tests for Nexus schedule API routing."""

import pytest


@pytest.fixture(autouse=True)
def isolated_schedule_db(monkeypatch, tmp_path):
    from src.runtime.stores.db import Database
    from src.server.routers import nexus_auth

    monkeypatch.setattr(nexus_auth.settings, "nexus_auth_token", None)
    monkeypatch.setattr(nexus_auth.settings, "nexus_password", None)
    monkeypatch.delenv("NEXUS_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("NEXUS_PASSWORD", raising=False)
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus-test.db"))
    Database.reset_instances()
    yield
    Database.reset_instances()


@pytest.mark.asyncio
async def test_schedules_list_route_is_mounted(client):
    resp = await client.get("/api/nexus/schedules", params={"exec_user": "ubuntu"})

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_schedule_create_route_is_mounted(client, tmp_path):
    workspace = tmp_path / "schedule-ws"
    workspace.mkdir()

    resp = await client.post(
        "/api/nexus/schedules",
        params={"exec_user": "ubuntu"},
        json={
            "name": "nightly",
            "description": "Run nightly task",
            "cron_expression": "0 2 * * *",
            "provider": "claude",
            "workspace": str(workspace),
        },
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "nightly"
    assert data["cron_expression"] == "0 2 * * *"
    assert data["workspace"] == str(workspace.resolve())

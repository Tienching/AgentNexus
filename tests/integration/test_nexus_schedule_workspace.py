from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest


class _MockScheduleStorage:
    def __init__(self):
        self.last_payload = None

    def add_schedule(self, **kwargs):
        self.last_payload = kwargs
        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            id="sched-1",
            name=kwargs["name"],
            cron_expression=kwargs.get("cron_expression"),
            run_at=kwargs.get("run_at"),
            timezone=kwargs.get("timezone_str", "UTC"),
            status="active",
            schedule_kind="recurring" if kwargs.get("cron_expression") else "one_time",
            evolution_phase=None,
            description=kwargs["description"],
            provider=kwargs["provider"],
            alias=kwargs["alias"],
            model=kwargs.get("model"),
            workspace=kwargs.get("workspace"),
            project_id=kwargs.get("project_id"),
            project_name=kwargs.get("project_name"),
            exec_user=kwargs.get("exec_user"),
            context=kwargs.get("context"),
            max_runs=kwargs.get("max_runs"),
            run_count=0,
            durability_mode=kwargs.get("durability_mode", "durable"),
            session_id=kwargs.get("session_id"),
            expires_at=None,
            jitter_seconds=kwargs.get("jitter_seconds", 0),
            created_at=now,
            updated_at=now,
            last_run_at=None,
            next_run_at=now,
            paused_at=None,
            cancelled_at=None,
            last_task_id=None,
            created_by=None,
        )


@pytest.mark.asyncio
async def test_create_schedule_rejects_missing_workspace(client):
    resp = await client.post(
        "/api/nexus/schedules",
        json={
            "name": "bad schedule",
            "description": "run later",
            "run_at": "2026-04-22T00:00:00Z",
            "provider": "claude",
            "workspace": "missing-workspace-folder",
        },
    )

    assert resp.status_code == 400
    assert "workspace 不存在或不是目录" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_schedule_resolves_relative_workspace(client, tmp_path, monkeypatch):
    storage = _MockScheduleStorage()
    base = tmp_path / "current"
    base.mkdir()
    workspace = base / "jobs"
    workspace.mkdir()

    monkeypatch.chdir(base)
    with patch("src.server.routers.nexus_schedules._get_schedule_storage", return_value=storage):
        resp = await client.post(
            "/api/nexus/schedules",
            json={
                "name": "good schedule",
                "description": "run later",
                "run_at": "2026-04-22T00:00:00Z",
                "provider": "claude",
                "workspace": "jobs",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["workspace"] == str(workspace.resolve())
    assert storage.last_payload["workspace"] == str(workspace.resolve())

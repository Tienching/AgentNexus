# -*- coding: utf-8 -*-

from __future__ import annotations

from fastapi.testclient import TestClient

from src.runtime.stores.db import Database
from src.server.services import reset_app_container
from src.server.services.task_storage import get_task_queue


TEST_SAFE_STARTUP_POLICY = {
    "start_task_executor": False,
    "start_task_scheduler": False,
    "start_channel_service": False,
    "start_terminal_manager": False,
    "start_evolution_service": False,
}


def test_collaboration_projects_issues_and_inbox(tmp_path, monkeypatch, app_factory):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "collab.db"))
    monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")
    Database.reset_instances()
    reset_app_container()
    reset_app_container()

    with TestClient(app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)) as client:
        headers = {"Authorization": "Bearer test-token"}
        workspace = tmp_path / "apollo"
        workspace.mkdir()

        first = client.post(
            "/api/nexus/tasks",
            headers=headers,
            json={
                "description": "Investigate flaky checkout flow",
                "project_name": "Apollo",
                "ticket_ref": "AP-42",
                "workspace": str(workspace),
            },
        )
        assert first.status_code == 200

        second = client.post(
            "/api/nexus/tasks",
            headers=headers,
            json={
                "description": "Prepare fix rollout for checkout flow",
                "project_name": "Apollo",
                "ticket_ref": "AP-42",
                "workspace": str(workspace),
            },
        )
        assert second.status_code == 200

        queue = get_task_queue("ubuntu")
        queue.start_task(second.json()["id"])
        queue.complete_task(second.json()["id"])

        issues_resp = client.get("/api/nexus/collab/issues", headers=headers)
        assert issues_resp.status_code == 200
        issues = issues_resp.json()
        assert len(issues) == 1
        assert issues[0]["issue_key"] == "AP-42"
        assert issues[0]["total_tasks"] == 2
        assert issues[0]["done_tasks"] == 1

        issue_detail = client.get("/api/nexus/collab/issues/AP-42", headers=headers)
        assert issue_detail.status_code == 200
        assert len(issue_detail.json()["tasks"]) == 2

        projects_resp = client.get("/api/nexus/collab/projects", headers=headers)
        assert projects_resp.status_code == 200
        assert projects_resp.json()[0]["project_id"] == "apollo"
        assert projects_resp.json()[0]["issue_count"] == 1

        inbox_resp = client.get("/api/nexus/collab/inbox", headers=headers)
        assert inbox_resp.status_code == 200
        inbox = inbox_resp.json()
        assert inbox["total_tasks"] == 1
        assert inbox["issues"][0]["issue_key"] == "AP-42"


def test_collaboration_create_issue_materializes_task(tmp_path, monkeypatch, app_factory):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "collab-create.db"))
    monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")
    Database.reset_instances()
    reset_app_container()

    with TestClient(app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)) as client:
        headers = {"Authorization": "Bearer test-token"}
        workspace = tmp_path / "ops"
        workspace.mkdir()
        resp = client.post(
            "/api/nexus/collab/issues",
            headers=headers,
            json={
                "title": "Triage provider outage",
                "description": "Track impact and mitigation steps",
                "project_name": "Ops",
                "workspace": str(workspace),
                "actor": "tester",
            },
        )
        assert resp.status_code == 201
        payload = resp.json()
        assert payload["issue"]["project_id"] == "ops"
        assert payload["issue"]["total_tasks"] == 1
        assert payload["task"]["ticket_ref"].startswith("ISSUE-")

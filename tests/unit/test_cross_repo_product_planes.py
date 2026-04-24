from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.runtime.stores.db import Database

TEST_SAFE_STARTUP_POLICY = {
    "start_task_executor": False,
    "start_task_scheduler": False,
    "start_channel_service": False,
    "start_terminal_manager": False,
    "start_evolution_service": False,
}


@pytest.fixture
def isolated_client(tmp_path, monkeypatch, app_factory):
    fake_home = tmp_path / "home" / "ubuntu"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus.db"))
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr("src.server.config.settings.user_home_base", str(fake_home.parent), raising=False)
    monkeypatch.setattr("src.server.config.settings.exec_user", "ubuntu", raising=False)
    Database.reset_instances()
    import src.server.services.control_plane as control_plane_module
    control_plane_module._control_plane_service = None
    with TestClient(app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)) as client:
        yield client, fake_home
    Database.reset_instances()
    control_plane_module._control_plane_service = None


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


def test_control_plane_api_roundtrip(isolated_client):
    client, _ = isolated_client

    tenant = client.post(
        "/api/nexus/control-plane/tenants",
        headers=_auth_headers(),
        json={"tenant_id": "tenant-a", "name": "Tenant A", "metadata": {"plan": "pro"}},
    )
    assert tenant.status_code == 201
    assert tenant.json()["tenant_id"] == "tenant-a"

    workspace = client.post(
        "/api/nexus/control-plane/workspaces",
        headers=_auth_headers(),
        json={
            "workspace_id": "ws-a",
            "tenant_id": "tenant-a",
            "name": "Workspace A",
            "root_path": "/tmp/ws-a",
            "default_branch": "main",
        },
    )
    assert workspace.status_code == 201
    assert workspace.json()["tenant_id"] == "tenant-a"

    membership = client.post(
        "/api/nexus/control-plane/memberships",
        headers=_auth_headers(),
        json={
            "scope_type": "tenant",
            "scope_id": "tenant-a",
            "username": "alice",
            "role": "operator",
            "scopes": ["task:write", "workspace:read"],
        },
    )
    assert membership.status_code == 200
    assert membership.json()["role"] == "operator"

    access = client.get(
        "/api/nexus/control-plane/access",
        headers=_auth_headers(),
        params={"username": "alice", "workspace_id": "ws-a"},
    )
    assert access.status_code == 200
    payload = access.json()
    assert payload["allowed"] is True
    assert payload["tenant_id"] == "tenant-a"
    assert payload["accessible_workspace_ids"] == ["ws-a"]


def test_collaboration_issue_layer_and_inbox(isolated_client):
    client, _ = isolated_client

    created = client.post(
        "/api/nexus/collab/issues",
        headers=_auth_headers(),
        json={
            "title": "Review deployment runbook",
            "description": "Track rollout readiness and follow-up tasks.",
            "project_name": "Launch Control",
            "workspace": "/tmp/launch-control",
            "ticket_ref": "OPS-42",
            "assigned_to": "alice",
            "actor": "alice",
        },
        params={"exec_user": "ubuntu"},
    )
    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload["issue"]["issue_key"] == "OPS-42"
    assert created_payload["task"]["project_id"] == "launch-control"

    issues = client.get(
        "/api/nexus/collab/issues",
        headers=_auth_headers(),
        params={"exec_user": "ubuntu"},
    )
    assert issues.status_code == 200
    issues_payload = issues.json()
    matching_issue = next((item for item in issues_payload if item["issue_key"] == "OPS-42"), None)
    assert matching_issue is not None
    assert matching_issue["open_tasks"] >= 1

    projects = client.get(
        "/api/nexus/collab/projects",
        headers=_auth_headers(),
        params={"exec_user": "ubuntu"},
    )
    assert projects.status_code == 200
    assert projects.json()[0]["project_id"] == "launch-control"

    inbox = client.get(
        "/api/nexus/collab/inbox",
        headers=_auth_headers(),
        params={"exec_user": "ubuntu"},
    )
    assert inbox.status_code == 200
    inbox_payload = inbox.json()
    assert inbox_payload["total_tasks"] >= 1
    assert inbox_payload["issues"][0]["issue_key"] == "OPS-42"


def test_extension_catalog_and_bundled_skill_import(isolated_client):
    client, fake_home = isolated_client

    bundled_root = Path("src/nanobot/skills")
    bundled_candidates = [p for p in bundled_root.iterdir() if p.is_dir() and (p / "SKILL.md").exists()]
    assert bundled_candidates, "expected at least one bundled skill in src/nanobot/skills"
    bundled_name = bundled_candidates[0].name

    alias_root = fake_home / ".claude-review"
    (alias_root / "skills" / "review-skill").mkdir(parents=True, exist_ok=True)
    (alias_root / "skills" / "review-skill" / "SKILL.md").write_text(
        "---\nname: review-skill\ndescription: review\nversion: 1.0.0\n---\n",
        encoding="utf-8",
    )

    catalog = client.get(
        "/api/nexus/extensions/catalog",
        headers=_auth_headers(),
        params={
            "exec_user": "ubuntu",
            "custom_paths": json.dumps({"claude-review": str(alias_root)}),
        },
    )
    assert catalog.status_code == 200
    payload = catalog.json()
    assert any(item["name"] == "claude" for item in payload["providers"])
    assert any(item["plugin_id"] == "cli" for item in payload["plugins"])
    assert any(item["panel_id"] == "admin.control-plane" for item in payload["panels"])
    assert "claude-review" in payload["provider_skills"]
    assert payload["provider_skills"]["claude-review"][0]["name"] == "review-skill"

    imported = client.post(
        "/api/nexus/extensions/skills/import",
        headers=_auth_headers(),
        params={"exec_user": "ubuntu"},
        json={
            "skill_name": bundled_name,
            "provider": "claude",
            "overwrite": True,
        },
    )
    assert imported.status_code == 201
    imported_payload = imported.json()
    assert imported_payload["provider"] == "claude"
    assert Path(imported_payload["path"]).exists()

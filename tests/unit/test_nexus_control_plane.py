# -*- coding: utf-8 -*-

from __future__ import annotations

from fastapi.testclient import TestClient

from src.runtime.stores.db import Database
from src.server.services import reset_app_container


TEST_SAFE_STARTUP_POLICY = {
    "start_task_executor": False,
    "start_task_scheduler": False,
    "start_channel_service": False,
    "start_terminal_manager": False,
    "start_evolution_service": False,
}


def test_control_plane_tenants_workspaces_memberships_and_audit(tmp_path, monkeypatch, app_factory):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "control-plane.db"))
    monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")
    monkeypatch.setattr("src.server.config.settings.exec_user", "authenticated-admin", raising=False)
    Database.reset_instances()
    reset_app_container()
    reset_app_container()
    import src.server.services.control_plane as control_plane_module

    control_plane_module._control_plane_services.clear()

    with TestClient(app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)) as client:
        headers = {"Authorization": "Bearer test-token", "X-Nexus-User": "spoofed-admin"}

        tenant_resp = client.post(
            "/api/nexus/control-plane/tenants",
            headers=headers,
            json={
                "tenant_id": "tenant-acme",
                "name": "Acme",
                "metadata": {"region": "apac"},
                "actor": "tester",
            },
        )
        assert tenant_resp.status_code == 201
        assert tenant_resp.json()["tenant_id"] == "tenant-acme"

        workspace_resp = client.post(
            "/api/nexus/control-plane/workspaces",
            headers=headers,
            json={
                "workspace_id": "ws-1",
                "tenant_id": "tenant-acme",
                "name": "Workspace One",
                "root_path": "/tmp/ws-1",
                "default_branch": "main",
                "actor": "tester",
            },
        )
        assert workspace_resp.status_code == 201
        assert workspace_resp.json()["workspace_id"] == "ws-1"

        tenant_membership = client.put(
            "/api/nexus/control-plane/tenants/tenant-acme/memberships/alice",
            headers=headers,
            json={"role": "operator", "scopes": ["task:read", "task:write"], "actor": "tester"},
        )
        assert tenant_membership.status_code == 200
        assert tenant_membership.json()["role"] == "operator"

        workspace_membership = client.put(
            "/api/nexus/control-plane/workspaces/ws-1/memberships/bob",
            headers=headers,
            json={"role": "viewer", "scopes": ["task:read"], "actor": "tester"},
        )
        assert workspace_membership.status_code == 200
        assert workspace_membership.json()["scope_type"] == "workspace"

        access_resp = client.get(
            "/api/nexus/control-plane/workspaces/ws-1/access",
            headers=headers,
            params={"username": "alice"},
        )
        assert access_resp.status_code == 200
        access_payload = access_resp.json()
        assert access_payload["allowed"] is True
        assert access_payload["via"] == "tenant"
        assert "ws-1" in access_payload["accessible_workspace_ids"]

        filtered_workspaces = client.get(
            "/api/nexus/control-plane/workspaces",
            headers=headers,
            params={"username": "alice", "accessible_only": "true"},
        )
        assert filtered_workspaces.status_code == 200
        assert [item["workspace_id"] for item in filtered_workspaces.json()] == ["ws-1"]

        audit_resp = client.get(
            "/api/nexus/control-plane/workspaces/ws-1/audit",
            headers=headers,
        )
        assert audit_resp.status_code == 200
        event_types = {item["event_type"] for item in audit_resp.json()}
        assert "control_plane.workspace.created" in event_types
        assert "control_plane.membership.upserted" in event_types
        membership_actors = {
            item["actor"]
            for item in audit_resp.json()
            if item["event_type"] == "control_plane.membership.upserted"
        }
        assert membership_actors == {"authenticated-admin"}

    control_plane_module._control_plane_services.clear()
    Database.reset_instances()
    reset_app_container()

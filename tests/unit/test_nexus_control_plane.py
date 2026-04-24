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
    try:
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
    finally:
        control_plane_module._control_plane_services.clear()
        Database.reset_instances()
        reset_app_container()


def test_control_plane_groups_and_workspace_join_requests(tmp_path, monkeypatch, app_factory):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "control-plane-groups.db"))
    monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")
    monkeypatch.setattr("src.server.config.settings.exec_user", "authenticated-admin", raising=False)
    Database.reset_instances()
    reset_app_container()
    import src.server.services.control_plane as control_plane_module

    control_plane_module._control_plane_services.clear()
    try:
        with TestClient(app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)) as client:
            headers = {"Authorization": "Bearer test-token", "X-Nexus-User": "spoofed-admin"}

            group_resp = client.post(
                "/api/nexus/control-plane/groups",
                headers=headers,
                json={"group_id": "group-acme", "name": "Acme Group", "metadata": {"tier": "core"}, "actor": "tester"},
            )
            assert group_resp.status_code == 201
            group_payload = group_resp.json()
            assert group_payload["group_id"] == "group-acme"

            groups_resp = client.get("/api/nexus/control-plane/groups", headers=headers)
            assert groups_resp.status_code == 200
            assert any(item["group_id"] == "group-acme" for item in groups_resp.json())

            # Backward-compatible tenant alias remains available.
            tenants_resp = client.get("/api/nexus/control-plane/tenants", headers=headers)
            assert tenants_resp.status_code == 200
            assert any(item["tenant_id"] == "group-acme" for item in tenants_resp.json())

            workspace_resp = client.post(
                "/api/nexus/control-plane/workspaces",
                headers=headers,
                json={
                    "workspace_id": "workspace-acme",
                    "tenant_id": "group-acme",
                    "name": "Acme Workspace",
                    "root_path": "/tmp/workspace-acme",
                    "default_branch": "main",
                    "actor": "tester",
                },
            )
            assert workspace_resp.status_code == 201

            create_req = client.post(
                "/api/nexus/control-plane/workspaces/workspace-acme/join-requests",
                headers=headers,
                json={"username": "zara", "role": "viewer", "scopes": ["task:read"], "note": "request access"},
            )
            assert create_req.status_code == 201
            request_payload = create_req.json()
            assert request_payload["status"] == "pending"
            request_id = request_payload["request_id"]
            assert request_payload["group_id"] == "group-acme"

            duplicate_req = client.post(
                "/api/nexus/control-plane/workspaces/workspace-acme/join-requests",
                headers=headers,
                json={"username": "zara", "role": "viewer", "scopes": ["task:read"], "note": "dup"},
            )
            assert duplicate_req.status_code == 400
            assert "pending join request already exists" in duplicate_req.json()["detail"]

            list_req = client.get(
                "/api/nexus/control-plane/workspaces/workspace-acme/join-requests",
                headers=headers,
            )
            assert list_req.status_code == 200
            request_list = list_req.json()
            assert any(item["request_id"] == request_id for item in request_list)

            # alias status filter
            list_alias = client.get(
                "/api/nexus/control-plane/workspaces/workspace-acme/join-requests",
                headers=headers,
                params={"status": "pending"},
            )
            assert list_alias.status_code == 200
            assert any(item["request_id"] == request_id for item in list_alias.json())

            resolve_req = client.patch(
                f"/api/nexus/control-plane/workspaces/workspace-acme/join-requests/{request_id}",
                headers=headers,
                json={"status": "approve", "review_note": "welcome aboard"},
            )
            assert resolve_req.status_code == 200
            assert resolve_req.json()["status"] == "approved"

            membership = client.get(
                "/api/nexus/control-plane/memberships",
                headers=headers,
                params={"scope_type": "workspace", "scope_id": "workspace-acme", "username": "zara"},
            )
            assert membership.status_code == 200
            membership_payload = membership.json()
            assert len(membership_payload) == 1
            assert membership_payload[0]["username"] == "zara"
            assert membership_payload[0]["role"] == "viewer"

            db_rows = control_plane_module.get_control_plane_service()._db.execute_fetchall(
                "SELECT group_id, workspace_id FROM control_plane_memberships "
                "WHERE scope_type = ? AND scope_id = ? AND username = ?",
                ("workspace", "workspace-acme", "zara"),
            )
            assert len(db_rows) == 1
            assert db_rows[0]["group_id"] == "group-acme"
            assert db_rows[0]["workspace_id"] == "workspace-acme"

            resolved_list = client.get(
                "/api/nexus/control-plane/workspaces/workspace-acme/join-requests",
                headers=headers,
                params={"status": "approve"},
            )
            assert resolved_list.status_code == 200
            assert resolved_list.json()[0]["request_id"] == request_id
            assert resolved_list.json()[0]["status"] == "approved"

            assert (
                client.patch(
                    f"/api/nexus/control-plane/workspaces/workspace-acme/join-requests/{request_id}",
                    headers=headers,
                    json={"status": "approve", "review_note": "double"},
                ).status_code
                == 400
            )
    finally:
        control_plane_module._control_plane_services.clear()
        Database.reset_instances()
        reset_app_container()

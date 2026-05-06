from __future__ import annotations

import json

import pytest

from scripts import nexusctl
from src.runtime.stores.db import Database
from src.server.services.collaboration_service import CollaborationService
from src.server.services.control_plane import get_control_plane_service
from src.server.services.domain_events import query_domain_events
from src.server.services.worktree_registry import get_repo_worktree_registry


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexusctl.db"))
    Database.reset_instances()
    import src.server.services.control_plane as control_plane_module
    import src.server.services.worktree_registry as worktree_module
    control_plane_module._control_plane_service = None
    worktree_module._repo_worktree_registry = None
    yield tmp_path
    Database.reset_instances()
    control_plane_module._control_plane_service = None
    worktree_module._repo_worktree_registry = None


def test_nexusctl_control_plane_and_repos_outputs_json(isolated_state, capsys):
    service = get_control_plane_service()
    service.create_tenant("tenant-a", "Tenant A")
    service.create_workspace("ws-a", "tenant-a", "Workspace A", root_path="/tmp/ws-a")
    service.upsert_membership(scope_type="tenant", scope_id="tenant-a", username="alice", role="admin")

    registry = get_repo_worktree_registry()
    registry.register(repo_url="https://example.com/acme/demo.git", repo_root="/tmp/repo", worktree_path="/tmp/repo_feature_a")
    registry.register_cache(repo_url="https://example.com/acme/demo.git", cache_path="/tmp/cache/demo.git")

    assert nexusctl.main(["control-plane", "tenants"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["tenant_id"] == "tenant-a"

    assert nexusctl.main(["control-plane", "access", "--username", "alice", "--workspace-id", "ws-a"]) == 0
    access_payload = json.loads(capsys.readouterr().out)
    assert access_payload["allowed"] is True

    assert nexusctl.main(["repos", "caches"]) == 0
    cache_payload = json.loads(capsys.readouterr().out)
    assert cache_payload[0]["cache_path"] == "/tmp/cache/demo.git"


def test_nexusctl_collab_and_extensions_outputs_json(isolated_state, capsys):
    collab = CollaborationService(exec_user="default")
    collab.create_issue(title="Prepare launch checklist", project_name="Launch", actor="alice")

    assert nexusctl.main(["collab", "issues"]) == 0
    issues_payload = json.loads(capsys.readouterr().out)
    assert issues_payload[0]["project_id"] == "launch"

    assert nexusctl.main(["extensions", "catalog"]) == 0
    ext_payload = json.loads(capsys.readouterr().out)
    assert any(item["name"] == "claude" for item in ext_payload["providers"])
    assert any(item["panel_id"] == "admin.control-plane" for item in ext_payload["panels"])


def test_nexusctl_dashboard_table_and_exit_codes(isolated_state, capsys):
    service = get_control_plane_service()
    service.create_tenant("tenant-a", "Tenant A")
    service.create_workspace("ws-a", "tenant-a", "Workspace A", root_path="/tmp/ws-a")

    collab = CollaborationService(exec_user="default")
    collab.create_issue(title="Review deploy checklist", project_name="Launch", actor="alice")

    registry = get_repo_worktree_registry()
    registry.register(repo_url="https://example.com/acme/demo.git", repo_root="/tmp/repo", worktree_path="/tmp/repo_feature_a")
    registry.register_cache(repo_url="https://example.com/acme/demo.git", cache_path="/tmp/cache/demo.git")

    assert nexusctl.main(["--format", "table", "dashboard"]) == 0
    output = capsys.readouterr().out
    assert "summary" in output.lower()
    assert "tenants" in output.lower()
    assert "repo_caches" in output.lower()

    assert nexusctl.main([]) == 2
    assert "Agent Nexus operator CLI" in capsys.readouterr().out


def test_nexusctl_control_plane_audit_parity(isolated_state, capsys):
    service = get_control_plane_service()
    service.create_tenant("tenant-a", "Tenant A")
    service.create_workspace("ws-a", "tenant-a", "Workspace A", root_path="/tmp/ws-a")
    service.upsert_membership(scope_type="workspace", scope_id="ws-a", username="alice", role="operator")

    expected = [item.to_dict() for item in query_domain_events(workspace_id="ws-a", limit=100)]
    assert nexusctl.main(["control-plane", "audit", "--workspace-id", "ws-a"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == expected

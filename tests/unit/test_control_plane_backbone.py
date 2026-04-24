# -*- coding: utf-8 -*-
"""Control-plane backbone tests for sessions, tasks, runtime daemons, and cost attribution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from src.core.cost.tracker import get_token_tracker
from src.core.events.activity import log_activity
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
    monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus.db"))
    Database.reset_instances()
    import src.core.cost.tracker as token_tracker_module
    import src.server.services.agent_runtimes as agent_runtimes_module
    import src.server.services.worktree_registry as worktree_registry_module
    token_tracker_module._token_tracker = None
    agent_runtimes_module._runtime_daemon_registry = None
    worktree_registry_module._repo_worktree_registry = None
    with TestClient(app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)) as client:
        yield client
    Database.reset_instances()
    token_tracker_module._token_tracker = None
    agent_runtimes_module._runtime_daemon_registry = None
    worktree_registry_module._repo_worktree_registry = None


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


def test_task_timeline_and_cost_summary(isolated_client, tmp_path):
    workspace = tmp_path / "workspace-a"
    workspace.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree_path = tmp_path / "repo_feature_1234"
    worktree_path.mkdir()
    prior_work_dir = tmp_path / "old-workspace"
    prior_work_dir.mkdir()

    create_resp = isolated_client.post(
        "/api/nexus/tasks",
        headers=_auth_headers(),
        json={
            "description": "Implement control-plane timeline logging",
            "workspace": str(workspace),
            "repo_url": "https://example.com/acme/repo.git",
            "repo_root": str(repo_root),
            "worktree_path": str(worktree_path),
            "prior_session_id": "session-prior",
            "prior_work_dir": str(prior_work_dir),
        },
    )
    assert create_resp.status_code == 200
    task = create_resp.json()

    timeline_resp = isolated_client.get(
        f"/api/nexus/tasks/{task['id']}/timeline",
        headers=_auth_headers(),
    )
    assert timeline_resp.status_code == 200
    timeline = timeline_resp.json()
    assert timeline["task_id"] == task["id"]
    assert timeline["total"] >= 1
    assert any(evt["event_type"] == "task.created" for evt in timeline["events"])

    tracker = get_token_tracker()
    tracker.record_attributed(
        model="gpt-4o",
        prompt_tokens=100,
        completion_tokens=50,
        workspace=str(workspace),
        agent_id="agent-1",
        runtime="codex",
        session_id="session-a",
        task_id=task["id"],
        tenant_id="tenant-a",
    )

    costs_resp = isolated_client.get("/api/nexus/costs", headers=_auth_headers())
    assert costs_resp.status_code == 200
    costs = costs_resp.json()
    assert costs["total_requests"] >= 1
    assert costs["total_tokens"] >= 150
    assert any(item["key"] == str(workspace) for item in costs["by_workspace"])
    assert any(item["key"] == "agent-1" for item in costs["by_agent"])
    assert any(item["key"] == "codex" for item in costs["by_runtime"])


def test_session_events_include_domain_events(isolated_client):
    create_resp = isolated_client.post(
        "/api/nexus/sessions",
        headers=_auth_headers(),
        json={
            "title": "Lifecycle session",
            "username": "tester",
            "exec_user": "tester",
            "provider": "claude",
            "alias": "claude",
            "exec_dir": "/tmp/session-work",
        },
    )
    assert create_resp.status_code == 200
    session = create_resp.json()

    archive_resp = isolated_client.post(
        f"/api/nexus/sessions/{session['id']}/archive",
        headers=_auth_headers(),
    )
    assert archive_resp.status_code == 200

    events_resp = isolated_client.get(
        f"/api/nexus/sessions/{session['id']}/events",
        headers=_auth_headers(),
    )
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert events["count"] >= 0
    assert events["domain_event_count"] >= 2
    assert any(evt["event_type"] == "session.created" for evt in events["domain_events"])
    assert any(evt["event_type"] == "session.status_changed" for evt in events["domain_events"])


def test_runtime_daemon_registry_endpoints(isolated_client):
    register_resp = isolated_client.post(
        "/api/nexus/runtimes/daemons/register",
        headers=_auth_headers(),
        json={
            "daemon_id": "daemon-1",
            "runtime_id": "codex",
            "device_name": "workstation-1",
            "cli_version": "1.0.0",
            "provider_version": "2.0.0",
            "status": "idle",
            "health_endpoint": "http://localhost:8080/health",
            "metadata": {"region": "local"},
        },
    )
    assert register_resp.status_code == 201
    daemon = register_resp.json()
    assert daemon["daemon_id"] == "daemon-1"
    assert daemon["runtime_id"] == "codex"

    heartbeat_resp = isolated_client.post(
        "/api/nexus/runtimes/daemons/daemon-1/heartbeat",
        headers=_auth_headers(),
        json={"status": "running", "pending_operations": 2},
    )
    assert heartbeat_resp.status_code == 200
    assert heartbeat_resp.json()["status"] == "running"
    assert heartbeat_resp.json()["pending_operations"] == 2

    list_resp = isolated_client.get("/api/nexus/runtimes/daemons", headers=_auth_headers())
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert payload["total"] == 1
    assert payload["daemons"][0]["daemon_id"] == "daemon-1"


def test_repo_worktree_registry_locking(isolated_client, tmp_path):
    from src.server.services.worktree_registry import get_repo_worktree_registry

    registry = get_repo_worktree_registry()
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    worktree_path = tmp_path / "repo-root_feature_task-1234"
    worktree_path.mkdir()
    workspace = tmp_path / "workspace-b"
    workspace.mkdir()
    prior_work_dir = tmp_path / "old-workspace"
    prior_work_dir.mkdir()
    record = registry.register_task_handoff(
        task_id="task-1234",
        repo_url="https://example.com/acme/repo.git",
        repo_root=str(repo_root),
        worktree_path=str(worktree_path),
        workspace=str(workspace),
        prior_session_id="session-prev",
        prior_work_dir=str(prior_work_dir),
    )

    assert record.repo_key
    assert registry.acquire_lock(record.repo_key, owner="operator-a") is True
    assert registry.acquire_lock(record.repo_key, owner="operator-b") is False
    assert registry.release_lock(record.repo_key, owner="operator-a") is True
    listed = registry.list_records(repo_root=str(repo_root))
    assert listed and listed[0].task_id == "task-1234"


def test_events_and_activities_api(isolated_client):
    from src.server.services.domain_events import record_domain_event

    evt = record_domain_event(
        "notification.created",
        "notification",
        "notif-1",
        actor="tester",
        payload={"title": "Hello"},
        workspace_id="/tmp/workspace-events",
    )
    assert evt is not None

    activity = log_activity(
        type="info",
        entity_type="notification",
        entity_id=1,
        actor="tester",
        description="Notification queued",
        data={"channel": "ui"},
    )
    assert activity is not None

    events_resp = isolated_client.get(
        "/api/nexus/events?aggregate_type=notification&aggregate_id=notif-1",
        headers=_auth_headers(),
    )
    assert events_resp.status_code == 200
    events_payload = events_resp.json()
    assert events_payload["count"] >= 1
    assert any(item["event_type"] == "notification.created" for item in events_payload["items"])

    activities_resp = isolated_client.get(
        "/api/nexus/activities?entity_type=notification",
        headers=_auth_headers(),
    )
    assert activities_resp.status_code == 200
    activities_payload = activities_resp.json()
    assert activities_payload["count"] >= 1
    assert any(item["description"] == "Notification queued" for item in activities_payload["items"])


def test_runtime_stale_sweep_endpoint(isolated_client):
    from src.server.services.agent_runtimes import get_runtime_daemon_registry
    from src.server.services.task_storage import get_task_queue

    register_resp = isolated_client.post(
        "/api/nexus/runtimes/daemons/register",
        headers=_auth_headers(),
        json={
            "daemon_id": "daemon-stale",
            "runtime_id": "codex",
            "device_name": "workstation-2",
            "status": "running",
        },
    )
    assert register_resp.status_code == 201

    registry = get_runtime_daemon_registry()
    stale_at = datetime.now(timezone.utc).timestamp() - 3600
    with registry._db.transaction() as conn:
        conn.execute(
            "UPDATE runtime_daemons SET last_heartbeat = ?, updated_at = ? WHERE daemon_id = ?",
            (stale_at, stale_at, "daemon-stale"),
        )

    queue = get_task_queue("default")
    task = queue.add_task(description="Stale background task", workspace="/tmp/stale-work")
    queue.start_task(task.id)
    running = queue.get_task(task.id)
    running.started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    running.runtime_last_heartbeat = datetime.now(timezone.utc) - timedelta(hours=2)
    assert queue.update_task(running) is True

    sweep_resp = isolated_client.post(
        "/api/nexus/runtimes/sweep/stale?stale_after_seconds=1&task_stale_after_seconds=1",
        headers=_auth_headers(),
    )
    assert sweep_resp.status_code == 200
    payload = sweep_resp.json()
    assert payload["offline_count"] == 1
    assert payload["requeued_tasks"] == 1

    daemon = registry.get_daemon("daemon-stale")
    assert daemon is not None
    assert daemon.status == "offline"

    refreshed = queue.get_task(task.id)
    assert refreshed is not None
    assert refreshed.status == "pending"

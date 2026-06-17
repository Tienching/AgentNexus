# -*- coding: utf-8 -*-
"""Tests for nexus_runtimes endpoint: /api/nexus/agent-runtimes.

Ported from mission-control agent-runtimes tests, adapted for Nexus.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


TEST_SAFE_STARTUP_POLICY = {
    "start_task_executor": False,
    "start_task_scheduler": False,
    "start_channel_service": False,
    "start_terminal_manager": False,
    "start_evolution_service": False,
}


@pytest.fixture
def client(monkeypatch, app_factory):
    monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")
    with TestClient(app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)) as c:
        yield c


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


class TestAgentRuntimes:
    def test_bootstrap_isolated_from_ambient_settings(self, monkeypatch, app_factory):
        monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")
        monkeypatch.setattr("src.server.app.settings.executor_enabled", False)
        monkeypatch.setattr("src.server.app.settings.scheduler_enabled", True)

        with TestClient(app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)) as client:
            resp = client.get("/api/nexus/agent-runtimes", headers=_auth_headers())

        assert resp.status_code == 200

    def test_returns_200(self, client):
        resp = client.get("/api/nexus/agent-runtimes", headers=_auth_headers())
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/nexus/agent-runtimes", headers=_auth_headers())
        data = resp.json()
        assert "runtimes" in data
        assert "total" in data
        assert "installed_count" in data
        assert isinstance(data["runtimes"], list)
        assert data["total"] >= 1  # at least one nexus-compatible runtime should be detected

    def test_runtime_item_shape(self, client):
        resp = client.get("/api/nexus/agent-runtimes", headers=_auth_headers())
        data = resp.json()
        for rt in data["runtimes"]:
            assert "id" in rt
            assert "name" in rt
            assert "installed" in rt
            assert "authenticated" in rt
            assert "auth_required" in rt
            assert isinstance(rt["installed"], bool)
            assert isinstance(rt["authenticated"], bool)

    def test_all_known_runtimes_present(self, client):
        resp = client.get("/api/nexus/agent-runtimes", headers=_auth_headers())
        data = resp.json()
        ids = {r["id"] for r in data["runtimes"]}
        # The 4 canonical CLI runtimes should be returned (nexus/nanobot removed)
        assert "claude" in ids
        assert "codex" in ids
        assert "gemini" in ids
        assert "codebuddy" in ids
        assert not ({"nanobot", "nexus"} & ids)

    def test_single_runtime_filter(self, client):
        resp = client.get(
            "/api/nexus/agent-runtimes?runtime_id=claude",
            headers=_auth_headers(),
        )
        data = resp.json()
        assert data["total"] == 1
        assert data["runtimes"][0]["id"] == "claude"

    def test_unknown_runtime_returns_result(self, client):
        resp = client.get(
            "/api/nexus/agent-runtimes?runtime_id=unknown_tool",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["runtimes"][0]["id"] == "unknown_tool"
        assert data["runtimes"][0]["installed"] is False

    def test_installed_count_matches(self, client):
        resp = client.get("/api/nexus/agent-runtimes", headers=_auth_headers())
        data = resp.json()
        expected = sum(1 for r in data["runtimes"] if r["installed"])
        assert data["installed_count"] == expected


class TestAgentRuntimesService:
    """Unit tests for the agent_runtimes service module."""

    def test_detect_binary_found(self):
        from src.server.services.agent_runtimes import _detect_binary
        # python should always be available
        installed, version, path = _detect_binary(["python3", "python"])
        assert installed is True
        assert version is not None
        assert path is not None

    def test_detect_binary_not_found(self):
        from src.server.services.agent_runtimes import _detect_binary
        installed, version, path = _detect_binary(["nonexistent_binary_xyz123"])
        assert installed is False
        assert version is None
        assert path is None

    def test_detect_runtime_unknown(self):
        from src.server.services.agent_runtimes import detect_runtime
        result = detect_runtime("totally_fake_runtime")
        assert result.id == "totally_fake_runtime"
        assert result.installed is False

    def test_detect_all_runtimes_returns_list(self):
        from src.server.services.agent_runtimes import detect_all_runtimes
        results = detect_all_runtimes()
        assert isinstance(results, list)
        assert len(results) == 4  # claude, codex, gemini, codebuddy (nexus/nanobot removed)

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_detect_binary_with_mock(self, mock_run, mock_which):
        from src.server.services.agent_runtimes import _detect_binary
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="claude v1.2.3\n",
            stderr="",
        )
        installed, version, path = _detect_binary(["claude"])
        assert installed is True
        assert version == "claude v1.2.3"
        assert path == "/usr/local/bin/claude"


class TestSecurityScanExecutorFix:
    """Verify the executor-enabled check no longer penalizes score."""

    def test_executor_enabled_is_pass(self, client):
        resp = client.get("/api/nexus/security-scan", headers=_auth_headers())
        data = resp.json()
        runtime_cat = data["categories"].get("runtime", {})
        checks = runtime_cat.get("checks", [])
        executor_check = next((c for c in checks if c["id"] == "executor_enabled"), None)
        assert executor_check is not None
        assert executor_check["status"] == "pass"
        assert executor_check["severity"] == "low"

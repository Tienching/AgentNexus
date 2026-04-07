# -*- coding: utf-8 -*-
"""Tests for nexus_ops endpoints: /api/nexus/search and /api/nexus/cleanup."""

from __future__ import annotations

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


def _auth():
    return {"Authorization": "Bearer test-token"}


# ═══════════════════════════════════════════════════════════════════════════
# Search tests
# ═══════════════════════════════════════════════════════════════════════════

class TestGlobalSearch:
    def test_bootstrap_isolated_from_ambient_settings(self, monkeypatch, app_factory):
        monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")
        monkeypatch.setattr("src.server.app.settings.executor_enabled", False)
        monkeypatch.setattr("src.server.app.settings.scheduler_enabled", True)

        with TestClient(app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)) as client:
            resp = client.get("/api/nexus/search?q=test", headers=_auth())

        assert resp.status_code == 200

    def test_returns_200(self, client):
        resp = client.get("/api/nexus/search?q=test", headers=_auth())
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/nexus/search?q=test", headers=_auth())
        data = resp.json()
        assert "query" in data
        assert "count" in data
        assert "results" in data
        assert data["query"] == "test"
        assert isinstance(data["results"], list)
        assert isinstance(data["count"], int)

    def test_query_too_short(self, client):
        resp = client.get("/api/nexus/search?q=x", headers=_auth())
        assert resp.status_code == 422  # validation error

    def test_query_missing(self, client):
        resp = client.get("/api/nexus/search", headers=_auth())
        assert resp.status_code == 422

    def test_type_filter_task(self, client):
        resp = client.get("/api/nexus/search?q=test&type=task", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        for r in data["results"]:
            assert r["type"] == "task"

    def test_type_filter_session(self, client):
        resp = client.get("/api/nexus/search?q=test&type=session", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        for r in data["results"]:
            assert r["type"] == "session"

    def test_limit_param(self, client):
        resp = client.get("/api/nexus/search?q=test&limit=5", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) <= 5

    def test_result_fields(self, client):
        """If there are any results, verify field structure."""
        resp = client.get("/api/nexus/search?q=ab", headers=_auth())
        assert resp.status_code == 200
        for r in resp.json()["results"]:
            assert "type" in r
            assert r["type"] in ("task", "session")
            assert "id" in r
            assert "title" in r
            assert "relevance" in r
            assert isinstance(r["relevance"], int)

    def test_requires_auth_when_password_set(self, client, monkeypatch):
        from src.server import config as _cfg
        monkeypatch.setattr(_cfg.settings, "nexus_password", "strongpass")
        resp = client.get("/api/nexus/search?q=test")
        assert resp.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════
# Cleanup tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCleanupPreview:
    def test_returns_200(self, client):
        resp = client.get("/api/nexus/cleanup", headers=_auth())
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/nexus/cleanup", headers=_auth())
        data = resp.json()
        assert "retention" in data
        assert "preview" in data
        assert "total_stale" in data
        assert isinstance(data["retention"], dict)
        assert isinstance(data["preview"], list)
        assert isinstance(data["total_stale"], int)

    def test_retention_keys(self, client):
        resp = client.get("/api/nexus/cleanup", headers=_auth())
        retention = resp.json()["retention"]
        assert "tasks_done" in retention
        assert "tasks_failed" in retention
        assert "sessions" in retention

    def test_preview_items_structure(self, client):
        resp = client.get("/api/nexus/cleanup", headers=_auth())
        for item in resp.json()["preview"]:
            assert "category" in item
            assert "retention_days" in item
            assert "cutoff_date" in item
            assert "stale_count" in item
            assert isinstance(item["retention_days"], int)
            assert isinstance(item["stale_count"], int)

    def test_total_stale_matches_sum(self, client):
        resp = client.get("/api/nexus/cleanup", headers=_auth())
        data = resp.json()
        total = sum(i["stale_count"] for i in data["preview"])
        assert data["total_stale"] == total

    def test_requires_auth_when_password_set(self, client, monkeypatch):
        from src.server import config as _cfg
        monkeypatch.setattr(_cfg.settings, "nexus_password", "strongpass")
        resp = client.get("/api/nexus/cleanup")
        assert resp.status_code in (401, 403)


class TestCleanupExecute:
    def test_dry_run_returns_200(self, client):
        resp = client.post("/api/nexus/cleanup?dry_run=true", headers=_auth())
        assert resp.status_code == 200

    def test_dry_run_response_shape(self, client):
        resp = client.post("/api/nexus/cleanup?dry_run=true", headers=_auth())
        data = resp.json()
        assert "deleted" in data
        assert "total_deleted" in data
        assert "duration_ms" in data
        assert isinstance(data["deleted"], dict)
        assert isinstance(data["total_deleted"], int)
        assert isinstance(data["duration_ms"], int)

    def test_dry_run_deleted_keys(self, client):
        resp = client.post("/api/nexus/cleanup?dry_run=true", headers=_auth())
        deleted = resp.json()["deleted"]
        assert "tasks_done" in deleted
        assert "tasks_failed" in deleted
        assert "sessions" in deleted

    def test_execute_returns_200(self, client):
        resp = client.post("/api/nexus/cleanup", headers=_auth())
        assert resp.status_code == 200

    def test_requires_auth_when_password_set(self, client, monkeypatch):
        from src.server import config as _cfg
        monkeypatch.setattr(_cfg.settings, "nexus_password", "strongpass")
        resp = client.post("/api/nexus/cleanup")
        assert resp.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════
# Helper tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSearchHelpers:
    def test_truncate_match_found(self):
        from src.server.routers.nexus_ops import _truncate_match
        result = _truncate_match("This is a long text with the keyword inside it", "keyword")
        assert result is not None
        assert "keyword" in result

    def test_truncate_match_not_found(self):
        from src.server.routers.nexus_ops import _truncate_match
        result = _truncate_match("short text", "missing")
        assert result == "short text"

    def test_truncate_match_none(self):
        from src.server.routers.nexus_ops import _truncate_match
        result = _truncate_match(None, "query")
        assert result is None

    def test_truncate_long_text(self):
        from src.server.routers.nexus_ops import _truncate_match
        long_text = "x" * 200
        result = _truncate_match(long_text, "missing", max_len=50)
        assert result is not None
        assert len(result) <= 55  # 50 + "..."

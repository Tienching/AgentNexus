# -*- coding: utf-8 -*-
"""Tests for nexus_admin: /api/nexus/diagnostics and /api/nexus/audit."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from src.server.app import AppStartupPolicy


TEST_SAFE_STARTUP_POLICY = AppStartupPolicy(
    start_task_executor=False,
    start_task_scheduler=False,
    start_channel_service=False,
    start_terminal_manager=False,
    start_evolution_service=False,
)


@pytest.fixture
def client(monkeypatch, app_factory):
    monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")
    with TestClient(app_factory(startup_policy=TEST_SAFE_STARTUP_POLICY)) as c:
        yield c


def _auth():
    return {"Authorization": "Bearer test-token"}


# ═══════════════════════════════════════════════════════════════════════════
# Diagnostics tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDiagnostics:
    def test_bootstrap_isolated_from_ambient_settings(self, monkeypatch, app_factory):
        monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")
        monkeypatch.setattr("src.server.app.settings.executor_enabled", False)
        monkeypatch.setattr("src.server.app.settings.scheduler_enabled", True)

        with TestClient(app_factory(startup_policy=TEST_SAFE_STARTUP_POLICY)) as client:
            r = client.get("/api/nexus/diagnostics", headers=_auth())

        assert r.status_code == 200

    def test_returns_200(self, client):
        r = client.get("/api/nexus/diagnostics", headers=_auth())
        assert r.status_code == 200

    def test_response_top_keys(self, client):
        r = client.get("/api/nexus/diagnostics", headers=_auth())
        d = r.json()
        for key in ["system", "version", "security", "redis", "tasks", "sessions", "retention"]:
            assert key in d, f"Missing top-level key: {key}"

    def test_system_fields(self, client):
        d = client.get("/api/nexus/diagnostics", headers=_auth()).json()
        sys = d["system"]
        assert "python_version" in sys
        assert "platform" in sys
        assert "arch" in sys
        assert "process_memory_mb" in sys
        assert "process_uptime_seconds" in sys
        assert "is_docker" in sys
        assert "pid" in sys
        assert isinstance(sys["cpu_count"], int)
        assert sys["cpu_count"] >= 1

    def test_version_fields(self, client):
        d = client.get("/api/nexus/diagnostics", headers=_auth()).json()
        ver = d["version"]
        assert "app" in ver
        assert "python" in ver
        assert "3." in ver["python"]

    def test_security_has_score_and_checks(self, client):
        d = client.get("/api/nexus/diagnostics", headers=_auth()).json()
        sec = d["security"]
        assert "score" in sec
        assert "checks" in sec
        assert 0 <= sec["score"] <= 100
        assert isinstance(sec["checks"], list)
        for check in sec["checks"]:
            assert "name" in check
            assert "pass" in check
            assert "detail" in check

    def test_redis_fields(self, client):
        d = client.get("/api/nexus/diagnostics", headers=_auth()).json()
        redis = d["redis"]
        assert "connected" in redis
        if redis["connected"]:
            assert "version" in redis
            assert "used_memory_mb" in redis
            assert "total_keys" in redis

    def test_tasks_fields(self, client):
        d = client.get("/api/nexus/diagnostics", headers=_auth()).json()
        tasks = d["tasks"]
        assert "total" in tasks
        assert "by_status" in tasks
        assert isinstance(tasks["by_status"], dict)

    def test_sessions_total(self, client):
        d = client.get("/api/nexus/diagnostics", headers=_auth()).json()
        assert "total" in d["sessions"]
        assert isinstance(d["sessions"]["total"], int)

    def test_retention_fields(self, client):
        d = client.get("/api/nexus/diagnostics", headers=_auth()).json()
        ret = d["retention"]
        assert "tasks_done_days" in ret
        assert "tasks_failed_days" in ret
        assert "sessions_days" in ret

    def test_audit_events_count(self, client):
        d = client.get("/api/nexus/diagnostics", headers=_auth()).json()
        assert "audit_events_count" in d
        assert isinstance(d["audit_events_count"], int)

    def test_requires_auth_when_password_set(self, client, monkeypatch):
        from src.server import config as _cfg
        monkeypatch.setattr(_cfg.settings, "nexus_password", "strongpass")
        r = client.get("/api/nexus/diagnostics")
        assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════
# Audit Log tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAuditLog:
    def test_returns_200(self, client):
        r = client.get("/api/nexus/audit", headers=_auth())
        assert r.status_code == 200

    def test_response_shape(self, client):
        r = client.get("/api/nexus/audit", headers=_auth())
        d = r.json()
        assert "events" in d
        assert "total" in d
        assert "limit" in d
        assert "offset" in d
        assert isinstance(d["events"], list)

    def test_record_and_query(self, client):
        """Record an event and verify it appears in the audit log."""
        from src.server.routers.nexus_admin import record_audit_event
        record_audit_event("test_action", actor="test_user", detail={"key": "value"})

        r = client.get("/api/nexus/audit?action=test_action", headers=_auth())
        d = r.json()
        assert d["total"] >= 1
        found = [e for e in d["events"] if e["action"] == "test_action"]
        assert len(found) >= 1
        assert found[0]["actor"] == "test_user"

    def test_filter_by_action(self, client):
        from src.server.routers.nexus_admin import record_audit_event
        record_audit_event("filter_test_action", actor="bot")

        r = client.get("/api/nexus/audit?action=filter_test_action", headers=_auth())
        for e in r.json()["events"]:
            assert e["action"] == "filter_test_action"

    def test_filter_by_actor(self, client):
        from src.server.routers.nexus_admin import record_audit_event
        record_audit_event("any_action", actor="specific_actor")

        r = client.get("/api/nexus/audit?actor=specific_actor", headers=_auth())
        for e in r.json()["events"]:
            assert e["actor"] == "specific_actor"

    def test_pagination(self, client):
        r = client.get("/api/nexus/audit?limit=2&offset=0", headers=_auth())
        d = r.json()
        assert d["limit"] == 2
        assert d["offset"] == 0
        assert len(d["events"]) <= 2

    def test_time_filter_since(self, client):
        from src.server.routers.nexus_admin import record_audit_event
        record_audit_event("recent_action", actor="timer")
        future_ts = int(time.time()) + 3600

        r = client.get(f"/api/nexus/audit?since={future_ts}", headers=_auth())
        assert r.json()["total"] == 0

    def test_event_fields(self, client):
        from src.server.routers.nexus_admin import record_audit_event
        record_audit_event("field_check", actor="tester", ip_address="127.0.0.1")

        r = client.get("/api/nexus/audit?action=field_check", headers=_auth())
        events = r.json()["events"]
        if events:
            e = events[0]
            assert "id" in e
            assert "action" in e
            assert "actor" in e
            assert "timestamp" in e
            assert isinstance(e["timestamp"], int)

    def test_diagnostics_creates_audit_event(self, client):
        """Calling /diagnostics should record a 'diagnostics_view' audit event."""
        client.get("/api/nexus/diagnostics", headers=_auth())

        r = client.get("/api/nexus/audit?action=diagnostics_view", headers=_auth())
        assert r.json()["total"] >= 1

    def test_requires_auth_when_password_set(self, client, monkeypatch):
        from src.server import config as _cfg
        monkeypatch.setattr(_cfg.settings, "nexus_password", "strongpass")
        r = client.get("/api/nexus/audit")
        assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests for record_audit_event
# ═══════════════════════════════════════════════════════════════════════════

class TestRecordAuditEvent:
    def test_does_not_raise(self):
        """record_audit_event should never raise, even on error."""
        from src.server.routers.nexus_admin import record_audit_event
        # Should not raise even if Redis is down
        record_audit_event("safe_test", actor="unit_test")

    def test_detail_can_be_dict(self):
        from src.server.routers.nexus_admin import record_audit_event
        record_audit_event("dict_detail", detail={"foo": "bar", "count": 42})

    def test_detail_can_be_string(self):
        from src.server.routers.nexus_admin import record_audit_event
        record_audit_event("str_detail", detail="simple string")

    def test_detail_can_be_none(self):
        from src.server.routers.nexus_admin import record_audit_event
        record_audit_event("none_detail")

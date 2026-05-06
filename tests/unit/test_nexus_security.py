# -*- coding: utf-8 -*-
"""Tests for nexus_security endpoint: /api/nexus/security-scan.

Ported from mission-control security-scan tests, adapted for Nexus.
"""

from __future__ import annotations

import os

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
    app = app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)
    with TestClient(app) as c:
        yield c


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


class TestSecurityScan:
    def test_returns_200(self, client):
        resp = client.get("/api/nexus/security-scan", headers=_auth_headers())
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/nexus/security-scan", headers=_auth_headers())
        data = resp.json()
        assert "overall" in data
        assert "score" in data
        assert "timestamp" in data
        assert "categories" in data
        assert data["overall"] in ("hardened", "secure", "needs-attention", "at-risk")
        assert 0 <= data["score"] <= 100

    def test_categories_present(self, client):
        resp = client.get("/api/nexus/security-scan", headers=_auth_headers())
        cats = resp.json()["categories"]
        assert "credentials" in cats
        assert "network" in cats
        assert "runtime" in cats
        assert "os" in cats
        assert "redis" in cats

    def test_each_category_has_checks(self, client):
        resp = client.get("/api/nexus/security-scan", headers=_auth_headers())
        for name, cat in resp.json()["categories"].items():
            assert "score" in cat, f"{name} missing score"
            assert "checks" in cat, f"{name} missing checks"
            assert 0 <= cat["score"] <= 100, f"{name} score out of range"

    def test_check_fields(self, client):
        resp = client.get("/api/nexus/security-scan", headers=_auth_headers())
        all_checks = []
        for cat in resp.json()["categories"].values():
            all_checks.extend(cat["checks"])
        assert len(all_checks) > 0
        for check in all_checks:
            assert "id" in check
            assert "name" in check
            assert "status" in check
            assert check["status"] in ("pass", "fail", "warn")
            assert "detail" in check
            assert "severity" in check
            assert check["severity"] in ("critical", "high", "medium", "low")

    def test_not_running_as_root(self, client):
        """Verify runtime check: not running as root."""
        resp = client.get("/api/nexus/security-scan", headers=_auth_headers())
        runtime_checks = resp.json()["categories"]["runtime"]["checks"]
        root_check = next((c for c in runtime_checks if c["id"] == "not_root"), None)
        assert root_check is not None
        # In test env, we should not be root
        if os.geteuid() != 0:
            assert root_check["status"] == "pass"

    def test_python_version_check(self, client):
        resp = client.get("/api/nexus/security-scan", headers=_auth_headers())
        runtime_checks = resp.json()["categories"]["runtime"]["checks"]
        py_check = next((c for c in runtime_checks if c["id"] == "python_version"), None)
        assert py_check is not None
        assert "Python" in py_check["detail"]

    def test_redis_checks_present(self, client):
        resp = client.get("/api/nexus/security-scan", headers=_auth_headers())
        redis_checks = resp.json()["categories"]["redis"]["checks"]
        check_ids = [c["id"] for c in redis_checks]
        assert "redis_reachable" in check_ids

    def test_requires_auth_when_password_set(self, client, monkeypatch):
        from src.server import config as _cfg
        monkeypatch.setattr(_cfg.settings, "nexus_password", "strongpass")
        resp = client.get("/api/nexus/security-scan")
        assert resp.status_code in (401, 403)

    def test_timestamp_is_recent(self, client):
        import time
        resp = client.get("/api/nexus/security-scan", headers=_auth_headers())
        ts = resp.json()["timestamp"]
        now_ms = int(time.time() * 1000)
        assert abs(now_ms - ts) < 10000  # within 10 seconds

    def test_bind_address_check(self, client):
        resp = client.get("/api/nexus/security-scan", headers=_auth_headers())
        net_checks = resp.json()["categories"]["network"]["checks"]
        bind_check = next((c for c in net_checks if c["id"] == "bind_address"), None)
        assert bind_check is not None


class TestSecurityScanScoring:
    """Test the scoring logic."""

    def test_score_calculation(self):
        from src.server.routers.nexus_security import (
            _score_category, SecurityCheck
        )
        checks = [
            SecurityCheck(id="a", name="A", status="pass", detail="ok", severity="critical"),
            SecurityCheck(id="b", name="B", status="fail", detail="bad", severity="low"),
        ]
        cat = _score_category(checks)
        # critical=4 pass, low=1 fail → 4/(4+1) = 80%
        assert cat.score == 80

    def test_all_pass_is_100(self):
        from src.server.routers.nexus_security import (
            _score_category, SecurityCheck
        )
        checks = [
            SecurityCheck(id="a", name="A", status="pass", detail="ok", severity="high"),
            SecurityCheck(id="b", name="B", status="pass", detail="ok", severity="medium"),
        ]
        cat = _score_category(checks)
        assert cat.score == 100

    def test_all_fail_is_0(self):
        from src.server.routers.nexus_security import (
            _score_category, SecurityCheck
        )
        checks = [
            SecurityCheck(id="a", name="A", status="fail", detail="bad", severity="high"),
            SecurityCheck(id="b", name="B", status="fail", detail="bad", severity="medium"),
        ]
        cat = _score_category(checks)
        assert cat.score == 0

    def test_empty_checks_is_100(self):
        from src.server.routers.nexus_security import _score_category
        cat = _score_category([])
        assert cat.score == 100

    def test_overall_thresholds(self):
        from src.server.routers.nexus_security import run_security_scan
        result = run_security_scan()
        score = result.score
        if score >= 90:
            assert result.overall == "hardened"
        elif score >= 70:
            assert result.overall == "secure"
        elif score >= 40:
            assert result.overall == "needs-attention"
        else:
            assert result.overall == "at-risk"

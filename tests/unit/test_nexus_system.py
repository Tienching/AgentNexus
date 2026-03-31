# -*- coding: utf-8 -*-
"""Tests for nexus_system endpoints: system-monitor, workload, standup.

Ported from mission-control:
  - GET /api/nexus/system-monitor
  - GET /api/nexus/workload
  - GET|POST /api/nexus/standup
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    """Return a TestClient with auth bypassed."""
    monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")

    from src.server.app import app

    with TestClient(app) as c:
        yield c


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


# ---------------------------------------------------------------------------
# /api/nexus/system-monitor
# ---------------------------------------------------------------------------

class TestSystemMonitor:
    def test_returns_200(self, client):
        resp = client.get("/api/nexus/system-monitor", headers=_auth_headers())
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/nexus/system-monitor", headers=_auth_headers())
        data = resp.json()
        assert "timestamp" in data
        assert "cpu" in data
        assert "memory" in data
        assert "disk" in data
        assert "network" in data

    def test_cpu_fields(self, client):
        resp = client.get("/api/nexus/system-monitor", headers=_auth_headers())
        cpu = resp.json()["cpu"]
        assert "usage_percent" in cpu
        assert "cores" in cpu
        assert "model" in cpu
        assert "load_avg" in cpu
        assert isinstance(cpu["cores"], int)
        assert cpu["cores"] >= 1
        assert 0 <= cpu["usage_percent"] <= 100

    def test_memory_fields(self, client):
        resp = client.get("/api/nexus/system-monitor", headers=_auth_headers())
        mem = resp.json()["memory"]
        assert "total_bytes" in mem
        assert "used_bytes" in mem
        assert "available_bytes" in mem
        assert "usage_percent" in mem
        assert mem["total_bytes"] >= 0
        assert 0 <= mem["usage_percent"] <= 100

    def test_disk_list(self, client):
        resp = client.get("/api/nexus/system-monitor", headers=_auth_headers())
        disk = resp.json()["disk"]
        assert isinstance(disk, list)
        for partition in disk:
            assert "mountpoint" in partition
            assert "total_bytes" in partition
            assert "usage_percent" in partition

    def test_network_list(self, client):
        resp = client.get("/api/nexus/system-monitor", headers=_auth_headers())
        network = resp.json()["network"]
        assert isinstance(network, list)

    def test_requires_auth_when_password_set(self, client, monkeypatch):
        """When NEXUS_PASSWORD is configured, unauthenticated requests must be rejected."""
        from src.server import config as _cfg
        monkeypatch.setattr(_cfg.settings, "nexus_password", "strongpass")
        resp = client.get("/api/nexus/system-monitor")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# /api/nexus/workload
# ---------------------------------------------------------------------------

class TestWorkload:
    def test_returns_200(self, client):
        resp = client.get("/api/nexus/workload", headers=_auth_headers())
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/nexus/workload", headers=_auth_headers())
        data = resp.json()
        assert "timestamp" in data
        assert "capacity" in data
        assert "queue" in data
        assert "recommendation" in data
        assert "thresholds" in data

    def test_capacity_fields(self, client):
        resp = client.get("/api/nexus/workload", headers=_auth_headers())
        cap = resp.json()["capacity"]
        assert "active_tasks" in cap
        assert "error_rate_5m" in cap
        assert isinstance(cap["active_tasks"], int)

    def test_queue_fields(self, client):
        resp = client.get("/api/nexus/workload", headers=_auth_headers())
        queue = resp.json()["queue"]
        assert "total_pending" in queue
        assert "by_status" in queue
        assert "estimated_wait_confidence" in queue
        assert isinstance(queue["total_pending"], int)

    def test_recommendation_fields(self, client):
        resp = client.get("/api/nexus/workload", headers=_auth_headers())
        rec = resp.json()["recommendation"]
        assert "action" in rec
        assert "reason" in rec
        assert "details" in rec
        assert "submit_ok" in rec
        assert "suggested_delay_ms" in rec
        assert rec["action"] in ("normal", "throttle", "shed", "pause")

    def test_recommendation_normal_on_empty_queue(self, client):
        """With no tasks queued, recommendation should be normal."""
        resp = client.get("/api/nexus/workload", headers=_auth_headers())
        data = resp.json()
        # Empty queue means normal or possibly pause (no agents) — not shed
        assert data["recommendation"]["action"] in ("normal", "pause")

    def test_thresholds_present(self, client):
        resp = client.get("/api/nexus/workload", headers=_auth_headers())
        thresholds = resp.json()["thresholds"]
        assert "queue_depth_normal" in thresholds
        assert "queue_depth_throttle" in thresholds
        assert "queue_depth_shed" in thresholds
        assert "busy_agent_ratio_throttle" in thresholds

    def test_requires_auth_when_password_set(self, client, monkeypatch):
        """When NEXUS_PASSWORD is configured, unauthenticated requests must be rejected."""
        from src.server import config as _cfg
        monkeypatch.setattr(_cfg.settings, "nexus_password", "strongpass")
        resp = client.get("/api/nexus/workload")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# /api/nexus/standup
# ---------------------------------------------------------------------------

class TestStandup:
    def test_get_returns_200(self, client):
        resp = client.get("/api/nexus/standup", headers=_auth_headers())
        assert resp.status_code == 200

    def test_post_returns_200(self, client):
        resp = client.post("/api/nexus/standup", headers=_auth_headers())
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/nexus/standup", headers=_auth_headers())
        data = resp.json()
        assert "standup" in data
        report = data["standup"]
        assert "generated_at" in report
        assert "exec_user" in report
        assert "summary" in report
        assert "agents" in report

    def test_summary_fields(self, client):
        resp = client.get("/api/nexus/standup", headers=_auth_headers())
        summary = resp.json()["standup"]["summary"]
        assert "total_todo" in summary
        assert "total_doing" in summary
        assert "total_done" in summary
        assert "total_failed" in summary
        assert isinstance(summary["total_todo"], int)
        assert isinstance(summary["total_doing"], int)

    def test_agents_list(self, client):
        resp = client.get("/api/nexus/standup", headers=_auth_headers())
        agents = resp.json()["standup"]["agents"]
        assert isinstance(agents, list)
        if agents:
            agent = agents[0]
            assert "agent" in agent
            assert "todo_tasks" in agent
            assert "doing_tasks" in agent
            assert "done_tasks" in agent
            assert "failed_tasks" in agent

    def test_generated_at_is_iso(self, client):
        resp = client.get("/api/nexus/standup", headers=_auth_headers())
        generated_at = resp.json()["standup"]["generated_at"]
        # Should be a valid ISO datetime string
        from datetime import datetime
        # Accept any parseable ISO format
        assert "T" in generated_at or "-" in generated_at

    def test_exec_user_present(self, client):
        resp = client.get("/api/nexus/standup", headers=_auth_headers())
        exec_user = resp.json()["standup"]["exec_user"]
        assert isinstance(exec_user, str)
        assert len(exec_user) > 0

    def test_requires_auth_when_password_set(self, client, monkeypatch):
        """When NEXUS_PASSWORD is configured, unauthenticated requests must be rejected."""
        from src.server import config as _cfg
        monkeypatch.setattr(_cfg.settings, "nexus_password", "strongpass")
        resp = client.get("/api/nexus/standup")
        assert resp.status_code in (401, 403)

    def test_get_and_post_same_structure(self, client):
        """GET and POST should return the same schema."""
        get_resp = client.get("/api/nexus/standup", headers=_auth_headers())
        post_resp = client.post("/api/nexus/standup", headers=_auth_headers())
        assert set(get_resp.json().keys()) == set(post_resp.json().keys())
        assert set(get_resp.json()["standup"].keys()) == set(post_resp.json()["standup"].keys())


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

class TestWorkloadHelpers:
    def test_escalate_normal_to_throttle(self):
        from src.server.routers.nexus_system import _escalate
        assert _escalate("normal", "throttle") == "throttle"

    def test_escalate_throttle_stays_shed(self):
        from src.server.routers.nexus_system import _escalate
        assert _escalate("shed", "throttle") == "shed"

    def test_escalate_to_pause(self):
        from src.server.routers.nexus_system import _escalate
        assert _escalate("shed", "pause") == "pause"

    def test_escalate_same_level(self):
        from src.server.routers.nexus_system import _escalate
        assert _escalate("normal", "normal") == "normal"


class TestSystemMonitorHelpers:
    def test_get_memory_info_returns_model(self):
        from src.server.routers.nexus_system import _get_memory_info
        m = _get_memory_info()
        assert m.total_bytes >= 0
        assert 0 <= m.usage_percent <= 100

    def test_get_network_info_returns_list(self):
        from src.server.routers.nexus_system import _get_network_info
        ifaces = _get_network_info()
        assert isinstance(ifaces, list)
        for iface in ifaces:
            assert hasattr(iface, "interface")
            assert hasattr(iface, "rx_bytes")
            assert hasattr(iface, "tx_bytes")

    def test_get_disk_info_returns_list(self):
        from src.server.routers.nexus_system import _get_disk_info
        disks = _get_disk_info()
        assert isinstance(disks, list)
        for d in disks:
            assert 0 <= d.usage_percent <= 100

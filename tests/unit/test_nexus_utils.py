# -*- coding: utf-8 -*-
"""Tests for nexus_utils: /api/nexus/schedule-parse and /api/nexus/export."""

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
    app = app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)
    with TestClient(app) as c:
        yield c


def _auth():
    return {"Authorization": "Bearer test-token"}


# ═══════════════════════════════════════════════════════════════════════════
# Schedule Parser tests
# ═══════════════════════════════════════════════════════════════════════════

class TestScheduleParser:
    def test_hourly(self, client):
        r = client.get("/api/nexus/schedule-parse?input=hourly", headers=_auth())
        assert r.status_code == 200
        d = r.json()
        assert d["cronExpr"] == "0 * * * *"
        assert "hour" in d["humanReadable"].lower()

    def test_daily(self, client):
        r = client.get("/api/nexus/schedule-parse?input=daily", headers=_auth())
        assert r.status_code == 200
        assert r.json()["cronExpr"] == "0 9 * * *"

    def test_every_day(self, client):
        r = client.get("/api/nexus/schedule-parse?input=every+day", headers=_auth())
        assert r.status_code == 200
        assert r.json()["cronExpr"] == "0 9 * * *"

    def test_weekly(self, client):
        r = client.get("/api/nexus/schedule-parse?input=weekly", headers=_auth())
        assert r.status_code == 200
        assert r.json()["cronExpr"] == "0 9 * * 1"

    def test_every_5_minutes(self, client):
        r = client.get("/api/nexus/schedule-parse?input=every+5+minutes", headers=_auth())
        assert r.status_code == 200
        assert r.json()["cronExpr"] == "*/5 * * * *"

    def test_every_2_hours(self, client):
        r = client.get("/api/nexus/schedule-parse?input=every+2+hours", headers=_auth())
        assert r.status_code == 200
        assert r.json()["cronExpr"] == "0 */2 * * *"

    def test_daily_at_9am(self, client):
        r = client.get("/api/nexus/schedule-parse?input=daily+at+9am", headers=_auth())
        assert r.status_code == 200
        assert r.json()["cronExpr"] == "0 9 * * *"

    def test_daily_at_2_30pm(self, client):
        r = client.get("/api/nexus/schedule-parse?input=daily+at+2:30pm", headers=_auth())
        assert r.status_code == 200
        assert r.json()["cronExpr"] == "30 14 * * *"

    def test_every_monday(self, client):
        r = client.get("/api/nexus/schedule-parse?input=every+monday", headers=_auth())
        assert r.status_code == 200
        assert r.json()["cronExpr"] == "0 9 * * 1"

    def test_every_friday_at_3pm(self, client):
        r = client.get("/api/nexus/schedule-parse?input=every+friday+at+3pm", headers=_auth())
        assert r.status_code == 200
        assert r.json()["cronExpr"] == "0 15 * * 5"

    def test_raw_cron_passthrough(self, client):
        r = client.get("/api/nexus/schedule-parse?input=*/10+*+*+*+*", headers=_auth())
        assert r.status_code == 200
        assert r.json()["cronExpr"] == "*/10 * * * *"

    def test_unparseable_returns_error(self, client):
        r = client.get("/api/nexus/schedule-parse?input=whenever+you+feel+like+it", headers=_auth())
        assert r.status_code == 200
        d = r.json()
        assert "error" in d

    def test_missing_input(self, client):
        r = client.get("/api/nexus/schedule-parse", headers=_auth())
        assert r.status_code == 422

    def test_at_time_every_day(self, client):
        r = client.get("/api/nexus/schedule-parse?input=at+8am+every+day", headers=_auth())
        assert r.status_code == 200
        assert r.json()["cronExpr"] == "0 8 * * *"

    def test_every_morning_at_time(self, client):
        r = client.get("/api/nexus/schedule-parse?input=every+morning+at+7am", headers=_auth())
        assert r.status_code == 200
        assert r.json()["cronExpr"] == "0 7 * * *"

    def test_requires_auth_when_password_set(self, client, monkeypatch):
        from src.server import config as _cfg
        monkeypatch.setattr(_cfg.settings, "nexus_password", "strongpass")
        r = client.get("/api/nexus/schedule-parse?input=hourly")
        assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════
# Schedule Parser unit tests (no HTTP)
# ═══════════════════════════════════════════════════════════════════════════

class TestParseNaturalScheduleUnit:
    def test_none_for_empty(self):
        from src.server.routers.nexus_utils import parse_natural_schedule
        assert parse_natural_schedule("") is None
        assert parse_natural_schedule("  ") is None

    def test_none_for_gibberish(self):
        from src.server.routers.nexus_utils import parse_natural_schedule
        assert parse_natural_schedule("asdf") is None

    def test_raw_cron(self):
        from src.server.routers.nexus_utils import parse_natural_schedule
        r = parse_natural_schedule("0 9 * * 1-5")
        assert r is not None
        assert r.cron_expr == "0 9 * * 1-5"

    def test_every_sunday_at_noon(self):
        from src.server.routers.nexus_utils import parse_natural_schedule
        r = parse_natural_schedule("every sunday at 12pm")
        assert r is not None
        assert r.cron_expr == "0 12 * * 0"

    def test_12am_is_midnight(self):
        from src.server.routers.nexus_utils import parse_natural_schedule
        r = parse_natural_schedule("daily at 12am")
        assert r is not None
        assert r.cron_expr == "0 0 * * *"


# ═══════════════════════════════════════════════════════════════════════════
# Export tests
# ═══════════════════════════════════════════════════════════════════════════

class TestExport:
    def test_export_tasks_json(self, client):
        r = client.get("/api/nexus/export?type=tasks&format=json", headers=_auth())
        assert r.status_code == 200
        d = r.json()
        assert d["type"] == "tasks"
        assert "exported_at" in d
        assert "count" in d
        assert "data" in d
        assert isinstance(d["data"], list)

    def test_export_sessions_json(self, client):
        r = client.get("/api/nexus/export?type=sessions&format=json", headers=_auth())
        assert r.status_code == 200
        d = r.json()
        assert d["type"] == "sessions"
        assert isinstance(d["data"], list)

    def test_export_tasks_csv(self, client):
        r = client.get("/api/nexus/export?type=tasks&format=csv", headers=_auth())
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")

    def test_export_sessions_csv(self, client):
        r = client.get("/api/nexus/export?type=sessions&format=csv", headers=_auth())
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")

    def test_export_invalid_type(self, client):
        r = client.get("/api/nexus/export?type=invalid&format=json", headers=_auth())
        assert r.status_code == 200
        assert "error" in r.json()

    def test_export_missing_type(self, client):
        r = client.get("/api/nexus/export", headers=_auth())
        assert r.status_code == 422

    def test_export_with_since_filter(self, client):
        r = client.get("/api/nexus/export?type=tasks&since=0&format=json", headers=_auth())
        assert r.status_code == 200

    def test_export_default_format_is_json(self, client):
        r = client.get("/api/nexus/export?type=tasks", headers=_auth())
        assert r.status_code == 200
        d = r.json()
        assert "data" in d

    def test_requires_auth_when_password_set(self, client, monkeypatch):
        from src.server import config as _cfg
        monkeypatch.setattr(_cfg.settings, "nexus_password", "strongpass")
        r = client.get("/api/nexus/export?type=tasks")
        assert r.status_code in (401, 403)

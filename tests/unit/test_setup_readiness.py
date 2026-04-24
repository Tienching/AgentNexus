# -*- coding: utf-8 -*-
"""Tests for the onboarding/setup readiness snapshot."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_setup_readiness_reports_sqlite_and_cli_ready(client, monkeypatch):
    monkeypatch.setattr("src.server.routers.nexus_config.shutil.which", lambda cmd: f"/usr/bin/{cmd}")

    fake_db = SimpleNamespace(
        db_path="/tmp/test-nexus.db",
        execute_fetchone=lambda sql: {"ok": 1},
    )
    monkeypatch.setattr("src.runtime.stores.db.get_db", lambda: fake_db)

    response = await client.get("/api/nexus/setup/readiness")
    assert response.status_code == 200
    data = response.json()
    assert data["backend"] == "sqlite"
    assert data["ready"] is True
    assert any(check["name"] == "SQLite database" for check in data["checks"])
    assert any(check["name"] == "Provider CLI" for check in data["checks"])


@pytest.mark.asyncio
async def test_setup_readiness_marks_cli_as_blocked_when_missing(client, monkeypatch):
    monkeypatch.setattr("src.server.routers.nexus_config.shutil.which", lambda cmd: None)

    fake_db = SimpleNamespace(
        db_path="/tmp/test-nexus.db",
        execute_fetchone=lambda sql: {"ok": 1},
    )
    monkeypatch.setattr("src.runtime.stores.db.get_db", lambda: fake_db)

    response = await client.get("/api/nexus/setup/readiness")
    data = response.json()
    assert response.status_code == 200
    assert data["ready"] is False
    assert any(check["status"] == "blocked" for check in data["checks"])

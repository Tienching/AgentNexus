# -*- coding: utf-8 -*-
"""API contracts for configurable agent templates."""

from __future__ import annotations

import pytest

from src.runtime.stores.db import Database
from src.server.services.agent_templates import reset_agent_template_store


@pytest.fixture(autouse=True)
def isolated_agent_template_db(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "agent-templates-api.db"))
    reset_agent_template_store()
    Database.reset_instances()
    yield
    reset_agent_template_store()
    Database.reset_instances()


@pytest.mark.asyncio
async def test_agent_template_api_lists_updates_creates_and_resets(client):
    response = await client.get("/api/nexus/agent-templates")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 3
    assert payload["items"][0]["name"] == "nexus"
    assert payload["items"][0]["hasDefault"] is True

    patch_response = await client.patch(
        "/api/nexus/agent-templates/nexus",
        json={
            "description": "Edited default template",
            "toolConfig": {"baseTools": ["Read"], "deferredTools": [], "disabledTools": [], "mcp": []},
            "capabilities": ["coding"],
        },
    )
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["description"] == "Edited default template"
    assert patched["toolConfig"]["baseTools"] == ["Read"]
    assert patched["capabilities"] == ["coding"]

    create_response = await client.post(
        "/api/nexus/agent-templates",
        json={"name": "plan-agent", "role": "Planner", "systemPrompt": "Plan carefully."},
    )
    assert create_response.status_code == 201
    assert create_response.json()["source"] == "custom"

    reset_response = await client.post("/api/nexus/agent-templates/nexus/reset")
    assert reset_response.status_code == 200
    assert reset_response.json()["description"] != "Edited default template"

    delete_response = await client.delete("/api/nexus/agent-templates/plan-agent")
    assert delete_response.status_code == 200

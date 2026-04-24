# -*- coding: utf-8 -*-
"""Tests for configurable agent templates."""

from __future__ import annotations

from src.runtime.stores.db import Database
from src.server.services.agent_templates import AgentTemplateStore, reset_agent_template_store


def setup_function():
    reset_agent_template_store()
    Database.reset_instances()


def teardown_function():
    reset_agent_template_store()
    Database.reset_instances()


def test_agent_template_store_seeds_presets_insert_only(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "templates.db"))

    store = AgentTemplateStore()
    names = [item["name"] for item in store.list_templates()]

    assert names[:3] == ["nexus", "explorer", "worker"]
    assert store.get("nexus")["hasDefault"] is True

    store.patch("nexus", {"description": "user edited", "toolConfig": {"baseTools": ["Read"]}})
    second_store = AgentTemplateStore()

    edited = second_store.get("nexus")
    assert edited["description"] == "user edited"
    assert edited["toolConfig"] == {"baseTools": ["Read"]}


def test_agent_template_store_crud_and_reset_from_top_level_agent_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "templates.db"))
    templates_dir = tmp_path / "agent" / "templates"
    templates_dir.mkdir(parents=True)
    (templates_dir / "main-agent.md").write_text(
        """---
name: main-agent
role: 主智能体
base_tools: [Read, Write]
capabilities: [coding, review]
max_iterations: 22
---
你是主智能体。
""",
        encoding="utf-8",
    )

    store = AgentTemplateStore(templates_dir=templates_dir)
    preset = store.get("main-agent")
    assert preset["role"] == "主智能体"
    assert preset["toolConfig"]["baseTools"] == ["Read", "Write"]
    assert preset["capabilities"] == ["coding", "review"]
    assert preset["maxIterations"] == 22

    created = store.create({"name": "custom-agent", "role": "Custom", "systemPrompt": "Hello"})
    assert created["source"] == "custom"
    assert created["hasDefault"] is False

    updated = store.patch(
        "custom-agent",
        {
            "modelProvider": "openai",
            "modelName": "gpt-5.4",
            "temperature": 0.2,
            "surfaces": ["messages"],
        },
    )
    assert updated["modelProvider"] == "openai"
    assert updated["modelName"] == "gpt-5.4"
    assert updated["temperature"] == 0.2
    assert updated["surfaces"] == ["messages"]

    store.patch("main-agent", {"role": "Edited"})
    reset = store.reset("main-agent")
    assert reset["role"] == "主智能体"

    store.delete("custom-agent")
    assert store.get("custom-agent") is None

# -*- coding: utf-8 -*-
"""Tests for the Nexus skills router."""

from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_get_skills_uses_shared_alias_resolution_for_custom_aliases(client, tmp_path, monkeypatch):
    fake_home = tmp_path / "home" / "ubuntu"
    (fake_home / ".claude" / "skills" / "default-skill").mkdir(parents=True)
    (fake_home / ".claude" / "skills" / "default-skill" / "SKILL.md").write_text(
        "---\nname: default-skill\ndescription: default\n---\n",
        encoding="utf-8",
    )

    alias_root = fake_home / ".claude-review"
    (alias_root / "skills" / "review-skill").mkdir(parents=True)
    (alias_root / "skills" / "review-skill" / "SKILL.md").write_text(
        "---\nname: review-skill\ndescription: review\n---\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("src.server.routers.nexus_skills.settings.exec_user", "ubuntu")
    monkeypatch.setattr("src.server.routers.nexus_skills.settings.user_home_base", str(fake_home.parent))

    response = await client.get(
        "/api/nexus/skills",
        params={
            "exec_user": "ubuntu",
            "custom_paths": json.dumps({"claude-review": str(alias_root)}),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "claude" in data["providers"]
    assert "claude-review" in data["providers"]
    assert any(skill["name"] == "review-skill" for skill in data["providers"]["claude-review"])

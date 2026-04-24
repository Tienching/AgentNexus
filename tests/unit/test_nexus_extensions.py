# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.runtime.stores.db import Database
from src.server.services import reset_app_container


TEST_SAFE_STARTUP_POLICY = {
    "start_task_executor": False,
    "start_task_scheduler": False,
    "start_channel_service": False,
    "start_terminal_manager": False,
    "start_evolution_service": False,
}


def test_extension_catalog_and_bundled_skill_import(tmp_path, monkeypatch, app_factory):
    fake_home_root = tmp_path / "home"
    fake_user_home = fake_home_root / "ubuntu"
    provider_skill = fake_user_home / ".claude" / "skills" / "review-helper"
    provider_skill.mkdir(parents=True, exist_ok=True)
    (provider_skill / "SKILL.md").write_text(
        "---\nname: review-helper\ndescription: Review code\nversion: 1.2.3\n---\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "extensions.db"))
    monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")
    monkeypatch.setattr("src.server.config.settings.user_home_base", str(fake_home_root))
    monkeypatch.setattr("src.server.config.settings.exec_user", "ubuntu")
    Database.reset_instances()
    reset_app_container()
    reset_app_container()

    with TestClient(app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)) as client:
        headers = {"Authorization": "Bearer test-token"}
        catalog_resp = client.get("/api/nexus/extensions/catalog", headers=headers)
        assert catalog_resp.status_code == 200
        payload = catalog_resp.json()
        assert any(item["name"] == "claude" for item in payload["providers"])
        assert any(item["plugin_id"] == "cli" for item in payload["plugins"])
        assert any(item["name"] == "github" for item in payload["bundled_skills"])
        assert payload["provider_skills"]["claude"][0]["name"] == "review-helper"
        assert any(item["panel_id"] == "admin.control-plane" for item in payload["panels"])

        import_resp = client.post(
            "/api/nexus/extensions/skills/import",
            headers=headers,
            json={"skill_name": "github", "provider": "claude"},
        )
        assert import_resp.status_code == 201
        imported = import_resp.json()
        assert imported["name"] == "github"
        assert imported["source"] == "imported"
        assert Path(imported["path"]).exists()
        assert (Path(imported["path"]) / "SKILL.md").is_file()


def test_extension_import_rejects_arbitrary_skills_path(tmp_path, monkeypatch, app_factory):
    fake_home_root = tmp_path / "home"
    fake_user_home = fake_home_root / "ubuntu"
    (fake_user_home / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    outside_root = tmp_path / "outside-skills"
    outside_root.mkdir()

    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "extensions-reject.db"))
    monkeypatch.setenv("NEXUS_AUTH_TOKEN", "test-token")
    monkeypatch.setattr("src.server.config.settings.user_home_base", str(fake_home_root))
    monkeypatch.setattr("src.server.config.settings.exec_user", "ubuntu")
    Database.reset_instances()
    reset_app_container()

    with TestClient(app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)) as client:
        headers = {"Authorization": "Bearer test-token"}
        import_resp = client.post(
            "/api/nexus/extensions/skills/import",
            headers=headers,
            json={
                "skill_name": "github",
                "provider": "claude",
                "skills_path": str(outside_root),
            },
        )
        assert import_resp.status_code == 400
        assert "skills_path" in import_resp.json()["detail"]

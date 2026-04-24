# -*- coding: utf-8 -*-
"""Regression tests for history/skills provider alias resolution and compat flows."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Response

from src.server.config import settings
from src.server.models import SessionMessagesResponse, SessionMeta
from src.runtime.models.execution_binding import ExecutionBinding
from src.server.routers.nexus_history import PromoteHistoryRequest, _resume_history_session
from src.server.services.stream_handler import StreamHandler
from src.server.routers.nexus_history_helpers import (
    resolve_base_provider,
    resolve_history_candidate_configs,
    resolve_provider_config_path,
)
from src.server.routers.nexus_skills import get_skills


def test_history_provider_and_alias_paths_resolve_to_expected_config_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "user_home_base", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "exec_user", "alice", raising=False)

    user_home = tmp_path / "alice"

    assert resolve_base_provider("claude-internal") == "claude"
    assert resolve_base_provider("codex-lab") == "codex"
    assert resolve_provider_config_path("claude", user_home=user_home) == user_home / ".claude"
    assert resolve_provider_config_path("claude-internal", user_home=user_home) == user_home / ".claude-internal"

    assert resolve_history_candidate_configs("claude", exec_user="alice") == [user_home / ".claude"]
    assert resolve_history_candidate_configs("claude-internal", exec_user="alice") == [
        user_home / ".claude-internal"
    ]
    assert resolve_history_candidate_configs(
        "custom-alias",
        exec_user="alice",
        config_path="~/.custom-alias",
    ) == [user_home / ".custom-alias"]

    with pytest.raises(HTTPException):
        resolve_history_candidate_configs("custom-alias", exec_user="alice")


@pytest.mark.asyncio
async def test_get_skills_scans_default_provider_and_custom_alias_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "user_home_base", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "exec_user", "alice", raising=False)

    user_home = tmp_path / "alice"
    default_skill_dir = user_home / ".claude" / "skills" / "draft-review"
    alias_root = tmp_path / "shared"
    alias_skill_dir = alias_root / "skills" / "history-lookup"
    default_skill_dir.mkdir(parents=True)
    alias_skill_dir.mkdir(parents=True)

    (default_skill_dir / "SKILL.md").write_text(
        "---\nname: draft-review\ndescription: Default skill\n---\n\nBody",
        encoding="utf-8",
    )
    (alias_skill_dir / "SKILL.md").write_text(
        "---\nname: history-lookup\ndescription: Alias skill\n---\n\nBody",
        encoding="utf-8",
    )

    response = await get_skills(
        exec_user="alice",
        # Custom alias paths are config roots; the router scans their direct skill subdirs.
        custom_paths=json.dumps({"claude-internal": str(alias_root)}),
    )

    assert "claude" in response.providers
    assert "claude-internal" in response.providers
    assert response.providers["claude"][0].path == str(default_skill_dir)
    assert response.providers["claude-internal"][0].path == str(alias_skill_dir)
    assert response.providers["claude"][0].provider == "claude"
    assert response.providers["claude-internal"][0].provider == "claude-internal"


class _FakeHistoryService:
    def __init__(self, detail: SessionMessagesResponse):
        self.detail = detail
        self.calls: list[tuple[str, Path, str]] = []

    async def get_session_detail(self, provider: str, config_path: Path, session_id: str):
        self.calls.append((provider, config_path, session_id))
        return self.detail


class _FakeCompatStorage:
    def __init__(self):
        self.runtime_meta = SessionMeta(
            id="runtime-1",
            thread_id="runtime-1",
            username="alice",
            exec_user="alice",
            provider="claude",
            alias="claude-internal",
        )
        self._mapping = {("claude-internal", "hist-001", "/projects/demo"): "runtime-1"}
        self._cli_session_ids: dict[str, str] = {}
        self.upserts: list[tuple[str, dict]] = []

    def get_history_runtime_mapping(self, provider: str, session_id: str, project_path: str):
        return self._mapping.get((provider, session_id, project_path))

    def get_session_meta(self, session_id: str):
        if session_id == "runtime-1":
            return self.runtime_meta
        return None

    def get_cli_session_id(self, session_id: str):
        return self._cli_session_ids.get(session_id)

    def set_cli_session_id(self, session_id: str, cli_session_id: str):
        self._cli_session_ids[session_id] = cli_session_id
        if session_id == self.runtime_meta.id:
            self.runtime_meta.cli_session_id = cli_session_id

    def upsert_execution_binding(self, session_id: str, **kwargs):
        self.upserts.append((session_id, kwargs))


@pytest.mark.asyncio
async def test_resume_history_session_compat_reuses_existing_mapping(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "user_home_base", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "exec_user", "ubuntu", raising=False)

    detail = SessionMessagesResponse(
        session_id="hist-001",
        session=SessionMeta(
            id="hist-001",
            thread_id="hist-001",
            username="alice",
            exec_user="alice",
            provider="claude",
            alias="claude-internal",
            exec_dir="/projects/demo",
        ),
    )
    fake_service = _FakeHistoryService(detail)
    fake_storage = _FakeCompatStorage()
    compat_hit = MagicMock()
    response = Response()

    with patch("src.server.routers.nexus_history._get_history_service", return_value=fake_service), patch(
        "src.server.routers.nexus_history.get_session_storage",
        return_value=fake_storage,
    ), patch("src.server.routers.nexus_history._record_history_compat_hit", compat_hit):
        result = await _resume_history_session(
            "claude-internal",
            "hist-001",
            PromoteHistoryRequest(project_path="/projects/demo", exec_user="alice", mode="full"),
            compat_route=True,
            response=response,
        )

    assert result.runtime_session_id == "runtime-1"
    assert result.created is False
    assert response.headers["X-Nexus-History-Compat"] == "promote"
    assert fake_service.calls == [
        ("claude-internal", tmp_path / "alice" / ".claude-internal", "hist-001"),
    ]
    assert fake_storage._cli_session_ids["runtime-1"] == "hist-001"
    assert fake_storage.upserts == [
        (
            "runtime-1",
            {
                "cli_session_id": "hist-001",
                "provider": "claude",
                "alias": "claude-internal",
                "exec_user": "alice",
                "work_dir": "/projects/demo",
                "source_type": "history",
                "source_session_id": "hist-001",
                "session_kind": "chat",
            },
        )
    ]
    compat_hit.assert_called_once()


class _FakeBindingStorage:
    def __init__(self, binding):
        self.binding = binding
        self.upserts: list[dict] = []

    def get_execution_binding(self, session_id: str):
        return self.binding if session_id == self.binding.session_id else None

    def get_cli_session_id(self, session_id: str):
        return None

    def upsert_execution_binding(self, **kwargs):
        self.upserts.append(kwargs)


def test_stream_binding_preserves_existing_source_type_for_history_binding():
    storage = _FakeBindingStorage(
        ExecutionBinding(
            session_id="runtime-1",
            cli_session_id="hist-001",
            session_kind="chat",
            provider="claude",
            alias="claude-internal",
            exec_user="alice",
            work_dir="/projects/demo",
            source_type="history",
            source_session_id="hist-001",
        )
    )

    cli_session_id, work_dir, compat_hits = StreamHandler.__new__(StreamHandler)._sync_execution_binding(
        storage=storage,
        session_id="runtime-1",
        provider="claude",
        alias="claude-internal",
        exec_user="alice",
        work_dir="/projects/demo",
        cli_session_id=None,
        session_kind="chat",
        source_type="chat",
    )

    assert cli_session_id == "hist-001"
    assert work_dir == "/projects/demo"
    assert "binding_cli_session" in compat_hits
    assert storage.upserts[-1]["source_type"] == "history"
    assert storage.upserts[-1]["source_session_id"] == "hist-001"


def test_stream_binding_preserves_existing_work_dir_when_followup_omits_cwd():
    storage = _FakeBindingStorage(
        ExecutionBinding(
            session_id="runtime-1",
            session_kind="chat",
            provider="codebuddy",
            alias="codebuddy",
            exec_user="alice",
            work_dir="/tmp/kanban-e2e",
            source_type="chat",
        )
    )

    cli_session_id, work_dir, compat_hits = StreamHandler.__new__(StreamHandler)._sync_execution_binding(
        storage=storage,
        session_id="runtime-1",
        provider="codebuddy",
        alias="codebuddy",
        exec_user="alice",
        work_dir=None,
        cli_session_id=None,
        session_kind="chat",
        source_type="chat",
    )

    assert cli_session_id is None
    assert work_dir == "/tmp/kanban-e2e"
    assert "binding_work_dir" in compat_hits
    assert storage.upserts[-1]["work_dir"] == "/tmp/kanban-e2e"

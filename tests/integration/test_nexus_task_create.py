"""Nexus Tasks Create API integration tests."""

from unittest.mock import patch

import pytest

from src.server.models import Task, TaskPriority, TaskStatus


class MockTaskQueue:
    def __init__(self):
        self._tasks = {}

    def add_task(
        self,
        description: str,
        priority: TaskPriority = TaskPriority.THOUGHT,
        context=None,
        project_id=None,
        project_name=None,
        workspace=None,
        provider=None,
        alias=None,
        model=None,
        task_id=None,
        source_session_id=None,
        session_id=None,
        exec_user=None,
        depends_on=None,
        **kwargs,
    ) -> Task:
        t = Task(
            description=description,
            priority=priority,
            status=TaskStatus.TODO,
            project_id=project_id,
            project_name=project_name,
            workspace=workspace,
            provider=provider or "claude",
            alias=alias,
            model=model,
            exec_user=exec_user,
            session_id=session_id or (source_session_id + "_" if source_session_id else "task_") + (task_id or "new"),
        )
        self._tasks[t.id] = t
        return t


class TestNexusCreateTask:
    @pytest.mark.asyncio
    async def test_create_task_success(self, client, tmp_path):
        q = MockTaskQueue()
        workspace = tmp_path / "ws"
        workspace.mkdir()
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=q):
            resp = await client.post(
                "/api/nexus/tasks",
                params={"exec_user": "ubuntu"},
                json={
                    "description": "Build feature",
                    "provider": "gemini",
                    "workspace": str(workspace),
                    "agent": "ubuntu",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "Build feature"
        assert data["provider"] == "gemini"
        assert data["status"] == "pending"
        assert data["workspace"] == str(workspace.resolve())

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider", ["claude", "gemini", "codex", "codebuddy"])
    async def test_create_task_valid_providers_success(self, client, provider, tmp_path):
        q = MockTaskQueue()
        workspace = tmp_path / f"ws-{provider}"
        workspace.mkdir()
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=q):
            resp = await client.post(
                "/api/nexus/tasks",
                params={"exec_user": "ubuntu"},
                json={
                    "description": "Build feature",
                    "provider": provider,
                    "workspace": str(workspace),
                    "agent": "ubuntu",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == provider

    @pytest.mark.asyncio
    async def test_create_task_alias_uses_base_provider_success(self, client, tmp_path):
        q = MockTaskQueue()
        workspace = tmp_path / "ws-alias"
        workspace.mkdir()
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=q):
            resp = await client.post(
                "/api/nexus/tasks",
                params={"exec_user": "ubuntu"},
                json={
                    "description": "Build feature",
                    "provider": "claude",
                    "alias": "claude-internal",
                    "workspace": str(workspace),
                    "agent": "ubuntu",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "claude"
        assert data["alias"] == "claude-internal"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("alias", ["claude-internal", "gemini-internal", "codex-internal"])
    async def test_create_task_internal_aliases_rejected_as_provider(self, client, alias):
        """Aliases like -internal are not valid provider names and should be rejected."""
        q = MockTaskQueue()
        workspace = "/tmp"
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=q):
            resp = await client.post(
                "/api/nexus/tasks",
                params={"exec_user": "ubuntu"},
                json={
                    "description": "Build feature",
                    "provider": alias,
                    "workspace": workspace,
                    "agent": "ubuntu",
                },
            )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_task_rejects_missing_workspace(self, client):
        q = MockTaskQueue()
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=q):
            resp = await client.post(
                "/api/nexus/tasks",
                params={"exec_user": "ubuntu"},
                json={
                    "description": "Build feature",
                    "provider": "claude",
                    "workspace": "definitely-missing-workspace-dir",
                },
            )

        assert resp.status_code == 400
        assert "workspace 不存在或不是目录" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_task_resolves_relative_workspace(self, client, tmp_path, monkeypatch):
        q = MockTaskQueue()
        base = tmp_path / "current"
        base.mkdir()
        workspace = base / "nested"
        workspace.mkdir()

        monkeypatch.chdir(base)
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=q):
            resp = await client.post(
                "/api/nexus/tasks",
                params={"exec_user": "ubuntu"},
                json={
                    "description": "Build feature",
                    "provider": "claude",
                    "workspace": "nested",
                },
            )

        assert resp.status_code == 200
        assert resp.json()["workspace"] == str(workspace.resolve())

    @pytest.mark.asyncio
    async def test_create_task_invalid_provider(self, client):
        q = MockTaskQueue()
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=q):
            resp = await client.post(
                "/api/nexus/tasks",
                params={"exec_user": "ubuntu"},
                json={
                    "description": "Build feature",
                    "provider": "unknown",
                },
            )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_task_missing_description(self, client):
        q = MockTaskQueue()
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=q):
            resp = await client.post(
                "/api/nexus/tasks",
                params={"exec_user": "ubuntu"},
                json={
                    "description": " ",
                    "provider": "claude",
                },
            )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_task_can_attach_to_existing_session(self, client):
        q = MockTaskQueue()
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=q):
            resp = await client.post(
                "/api/nexus/tasks",
                params={"exec_user": "ubuntu"},
                json={
                    "description": "Build feature",
                    "provider": "claude",
                    "session_id": "existing-session-123",
                    "agent": "ubuntu",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "existing-session-123"

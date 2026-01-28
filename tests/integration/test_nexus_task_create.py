"""Nexus Tasks Create API integration tests."""

from unittest.mock import patch

import pytest

from src.providers.claude_code_api.models import Task, TaskPriority, TaskStatus


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
        task_id=None,
        source_session_id=None,
        agent_name=None,
    ) -> Task:
        t = Task(
            description=description,
            priority=priority,
            status=TaskStatus.TODO,
            project_id=project_id,
            project_name=project_name,
            workspace=workspace,
            provider=provider or "claude",
            agent_name=agent_name,
            session_id=(source_session_id + "_" if source_session_id else "task_") + (task_id or "new"),
        )
        self._tasks[t.id] = t
        return t


class TestNexusCreateTask:
    @pytest.mark.asyncio
    async def test_create_task_success(self, client):
        q = MockTaskQueue()
        with patch("src.server.routers.nexus._get_task_queue", return_value=q):
            resp = await client.post(
                "/api/nexus/tasks",
                params={"agent_name": "ubuntu"},
                json={
                    "description": "Build feature",
                    "provider": "gemini",
                    "workspace": "/tmp/ws",
                    "agent": "ubuntu",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "Build feature"
        assert data["provider"] == "gemini"
        assert data["status"] == "todo"
        assert data["workspace"] == "/tmp/ws"

    @pytest.mark.asyncio
    async def test_create_task_invalid_provider(self, client):
        q = MockTaskQueue()
        with patch("src.server.routers.nexus._get_task_queue", return_value=q):
            resp = await client.post(
                "/api/nexus/tasks",
                params={"agent_name": "ubuntu"},
                json={
                    "description": "Build feature",
                    "provider": "unknown",
                },
            )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_task_missing_description(self, client):
        q = MockTaskQueue()
        with patch("src.server.routers.nexus._get_task_queue", return_value=q):
            resp = await client.post(
                "/api/nexus/tasks",
                params={"agent_name": "ubuntu"},
                json={
                    "description": " ",
                    "provider": "claude",
                },
            )

        assert resp.status_code == 400

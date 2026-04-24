# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.runtime.models.task_models import Task
from src.server.services.task_execution_service import execute_task


class _DummyStorage:
    def __init__(self) -> None:
        self.binding_upserts = []
        self.task_ids = []

    def get_execution_binding(self, session_id: str):
        return None

    def get_cli_session_id(self, session_id: str):
        return None

    def upsert_execution_binding(self, **kwargs):
        self.binding_upserts.append(kwargs)

    def set_task_id(self, session_id: str, task_id: str):
        self.task_ids.append((session_id, task_id))


class _DummyArchiver:
    async def on_run_started(self, initial_messages):
        return None

    async def archive_event(self, event):
        return None

    async def on_run_error(self, error):
        return None

    async def on_run_finished(self):
        return None


class _DummyAdapter:
    def init_state(self, **kwargs):
        return None

    def create_start_event(self):
        return None

    def create_end_event(self):
        return None

    def create_error_event(self, message):
        return None

    def convert(self, data):
        return None


class _DummyExecutor:
    async def execute(self, request, exec_user, output_format="raw"):
        if False:
            yield None
        return


@pytest.mark.asyncio
async def test_execute_task_passes_resolved_binding_to_archiver(monkeypatch):
    storage = _DummyStorage()
    captured = {}

    def fake_create_archiver(**kwargs):
        captured.update(kwargs)
        return _DummyArchiver()

    monkeypatch.setattr("src.server.services.get_session_storage", lambda: storage)
    monkeypatch.setattr("src.server.services.stream_archiver.create_archiver", fake_create_archiver)
    monkeypatch.setattr("src.server.services.task_execution_service.create_executor", lambda provider: _DummyExecutor())
    monkeypatch.setattr("src.server.services.task_execution_service.create_adapter", lambda provider: _DummyAdapter())
    monkeypatch.setattr("src.server.services.task_execution_service._provision_task_workspace", lambda task: task.workspace)
    monkeypatch.setattr("src.server.services.task_execution_service._handle_ralph_loop", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.server.services.task_execution_service.record_sampled_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.server.services.task_execution_service.telemetry", SimpleNamespace(
        increment=lambda *args, **kwargs: None,
        set_gauge=lambda *args, **kwargs: None,
    ))

    task = Task(
        id="task-binding-1",
        description="verify binding handoff",
        session_id="task_binding_session",
        exec_user="ubuntu",
        provider="claude",
        alias="claude",
        workspace="/tmp",
    )

    result = await execute_task(task)

    assert result is None
    assert captured["thread_id"] == "task_binding_session"
    assert captured["execution_binding"] is not None
    assert captured["execution_binding"].session_id == "task_binding_session"
    assert captured["execution_binding"].task_id == "task-binding-1"
    assert storage.task_ids == [("task_binding_session", "task-binding-1")]
    assert storage.binding_upserts

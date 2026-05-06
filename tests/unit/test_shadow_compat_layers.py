# -*- coding: utf-8 -*-

from __future__ import annotations

from src.core.tasks.task import TaskManager as CoreCompatTaskManager
from src.runtime.execution.task import Task as RuntimeCompatTask
from src.runtime.models.task_models import TaskStatus
from src.core.tasks.session import Session as CoreCompatSession
from src.runtime.execution.session import Session as RuntimeCompatSession


def test_core_task_compat_uses_runtime_task_model():
    task = CoreCompatTaskManager().create("Compat task")
    assert isinstance(task, RuntimeCompatTask)
    assert task.status == TaskStatus.PENDING
    assert task.task_id == task.id


def test_session_compat_layers_share_runtime_meta_shape():
    session = CoreCompatSession(
        id="sess-1",
        session_id="sess-1",
        thread_id="sess-1",
        username="tester",
        provider="claude",
        exec_user="tester",
        workspace="/tmp/ws",
    )
    payload = session.to_dict()
    assert payload["session_id"] == "sess-1"
    assert payload["workspace"] == "/tmp/ws"

    runtime_session = RuntimeCompatSession(
        session_id="sess-2",
        provider="codex",
    )
    assert runtime_session.session_id == "sess-2"

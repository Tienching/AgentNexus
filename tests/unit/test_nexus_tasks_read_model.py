# -*- coding: utf-8 -*-
"""Regression tests for task read-model assembly."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.core.quality.gates import ReviewStatus
from src.runtime.models.execution_binding import ExecutionBinding
from src.runtime.models.task_models import Task, TaskPriority, TaskStatus
from src.server.routers.nexus_tasks import _assemble_task_read_models


class _FakeQualityGate:
    def __init__(self, latest_reviews):
        self.latest_reviews = latest_reviews
        self.calls: list[tuple[list[str], int]] = []

    def get_latest_by_tasks(self, task_ids, workspace_id: int = 1):
        task_id_list = list(task_ids)
        self.calls.append((task_id_list, workspace_id))
        return self.latest_reviews


class _FakeSessionStorage:
    def __init__(self, bindings):
        self.bindings = bindings
        self.calls: list[str] = []

    def get_execution_binding(self, session_id: str):
        self.calls.append(session_id)
        return self.bindings.get(session_id)


def _make_task(*, task_id: str, session_id: str, inline_binding: bool = False) -> Task:
    binding = None
    if inline_binding:
        binding = ExecutionBinding(
            session_id=session_id,
            cli_session_id=f"cli-{task_id}",
            session_kind="chat",
            provider="claude",
            alias="claude",
            exec_user="alice",
            work_dir="/projects/demo",
            source_type="history",
            source_session_id=f"hist-{task_id}",
            task_id=task_id,
        )

    return Task(
        id=task_id,
        description=f"Task {task_id}",
        priority=TaskPriority.THOUGHT,
        status=TaskStatus.DONE,
        provider="claude",
        alias="claude",
        exec_user="alice",
        session_id=session_id,
        execution_binding=binding,
    )


def test_assemble_task_read_models_batches_quality_gate_lookup_and_uses_binding_fallback():
    inline_task = _make_task(task_id="task-inline", session_id="session-inline", inline_binding=True)
    storage_task = _make_task(task_id="task-storage", session_id="session-storage", inline_binding=False)

    latest_reviews = {
        "task-inline": SimpleNamespace(
            status=ReviewStatus.APPROVED,
            reviewer="reviewer-a",
            notes="Looks good",
            created_at=1700000000.0,
        ),
        "task-storage": SimpleNamespace(
            status=ReviewStatus.REJECTED,
            reviewer="reviewer-b",
            notes="Needs work",
            created_at=1700000100.0,
        ),
    }
    fake_gate = _FakeQualityGate(latest_reviews)
    fake_storage = _FakeSessionStorage(
        {
            "session-storage": ExecutionBinding(
                session_id="session-storage",
                cli_session_id="cli-storage",
                session_kind="chat",
                provider="claude",
                alias="claude",
                exec_user="alice",
                work_dir="/projects/demo",
                source_type="task",
                source_session_id="hist-task-storage",
                task_id="task-storage",
            )
        }
    )

    with patch("src.server.routers.nexus_tasks.get_quality_gate", return_value=fake_gate), patch(
        "src.server.services.session_storage.get_session_storage",
        return_value=fake_storage,
    ):
        items = _assemble_task_read_models([inline_task, storage_task], workspace_id=7)

    assert fake_gate.calls == [(["task-inline", "task-storage"], 7)]
    assert fake_storage.calls == ["session-inline", "session-storage"]

    inline_item, storage_item = items
    assert inline_item.id == "task-inline"
    assert inline_item.cli_session_id == "cli-task-inline"
    assert inline_item.session_kind == "chat"
    assert inline_item.aegis_approved is True
    assert inline_item.aegis_status == "approved"
    assert inline_item.aegis_reason == "Quality review approved"

    assert storage_item.id == "task-storage"
    assert storage_item.cli_session_id == "cli-storage"
    assert storage_item.session_kind == "chat"
    assert storage_item.aegis_approved is False
    assert storage_item.aegis_status == "rejected"
    assert storage_item.aegis_reason == "Latest quality review status: rejected"

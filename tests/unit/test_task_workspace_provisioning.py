from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.runtime.commands.slash.worktree import CachedRepoProvisionResult, WorktreeResult
from src.server.services.task_execution_service import _provision_task_workspace


def test_provision_task_workspace_prefers_existing_explicit_worktree(tmp_path: Path):
    worktree = tmp_path / "existing-worktree"
    worktree.mkdir()
    task = SimpleNamespace(
        id="task-1",
        repo_url="https://example.com/acme/demo.git",
        repo_root=None,
        worktree_path=str(worktree),
        workspace=None,
    )

    resolved = _provision_task_workspace(task)

    assert resolved == str(worktree)
    assert task.workspace == str(worktree)


def test_provision_task_workspace_uses_cached_provisioner(monkeypatch, tmp_path: Path):
    worktree = tmp_path / "demo_feature_task-2"
    result = CachedRepoProvisionResult(
        cache_dir=tmp_path / "cache.git",
        repo_key="repo-key-1",
        reused_cache=False,
        worktree=WorktreeResult(
            repo_root=tmp_path / "cache.git",
            repo_name="demo",
            task_id="task-2",
            branch="feature_task-2",
            worktree_dir=worktree,
            reused=False,
        ),
    )

    captured: dict[str, object] = {}

    def fake_provision_cached_worktree(**kwargs):
        captured.update(kwargs)
        return result

    monkeypatch.setattr(
        "src.runtime.commands.slash.worktree.provision_cached_worktree",
        fake_provision_cached_worktree,
    )

    original_workspace = str(tmp_path / "placeholder" / "workspace")
    task = SimpleNamespace(
        id="task-2",
        repo_url="https://example.com/acme/demo.git",
        repo_root=None,
        worktree_path=str(worktree),
        workspace=original_workspace,
    )

    resolved = _provision_task_workspace(task)

    assert resolved == str(worktree)
    assert task.workspace == str(worktree)
    assert task.worktree_path == str(worktree)
    assert captured["task_id"] == "task-2"
    assert captured["repo_url"] == "https://example.com/acme/demo.git"
    assert captured["tmp_base"] == worktree.parent


async def _never_called_execute(*args, **kwargs):
    raise AssertionError("executor should not be called when workspace provisioning fails")

@pytest.mark.asyncio
async def test_execute_task_returns_error_when_explicit_worktree_contract_fails(monkeypatch, tmp_path: Path):
    from src.server.services import task_execution_service

    missing_worktree = tmp_path / "missing-worktree"
    task = SimpleNamespace(
        id="task-3",
        description="do work",
        project_id=None,
        priority="thought",
        context={},
        repo_url=None,
        repo_root=None,
        worktree_path=str(missing_worktree),
        workspace=str(tmp_path / "wrong-dir"),
    )

    monkeypatch.setattr(task_execution_service, "create_executor", _never_called_execute)

    result = await task_execution_service.execute_task(task)

    assert result is not None
    assert "Task workspace provisioning failed" in result

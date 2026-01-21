# -*- coding: utf-8 -*-

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.claude_code_api.services.worktree import (
    WorktreeError,
    ensure_task_worktree,
    is_git_worktree,
)


def _cp(stdout: str = "", stderr: str = "", returncode: int = 0):
    class CP:
        def __init__(self):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    return CP()


def test_is_git_worktree_true():
    with patch("src.claude_code_api.services.worktree.subprocess.run") as m:
        m.return_value = _cp(stdout="true\n", returncode=0)
        assert is_git_worktree(Path("/repo")) is True


def test_is_git_worktree_false():
    with patch("src.claude_code_api.services.worktree.subprocess.run") as m:
        m.return_value = _cp(stdout="false\n", returncode=0)
        assert is_git_worktree(Path("/repo")) is False


def test_ensure_task_worktree_not_git_repo_raises():
    with patch("src.claude_code_api.services.worktree.subprocess.run") as m:
        # rev-parse --show-toplevel fails
        m.return_value = _cp(stdout="", stderr="fatal: not a git repository", returncode=128)
        with pytest.raises(WorktreeError):
            ensure_task_worktree(Path("/notgit"), task_id="abcd1234", tmp_base=Path("/tmp"))


def test_ensure_task_worktree_reuse_when_registered(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # Create target dir
    target = tmp_path / "repo_feature_abcd1234"
    target.mkdir()

    def fake_run(cmd, capture_output, text):
        # cmd is [git, -C, <dir>, ...]
        if cmd[3:] == ["rev-parse", "--show-toplevel"]:
            return _cp(stdout=str(repo_root) + "\n", returncode=0)
        if cmd[3:] == ["worktree", "list", "--porcelain"]:
            return _cp(stdout=f"worktree {target}\nHEAD deadbeef\n", returncode=0)
        raise AssertionError(f"unexpected git call: {cmd}")

    with patch("src.claude_code_api.services.worktree.subprocess.run", side_effect=fake_run):
        res = ensure_task_worktree(repo_root, task_id="abcd1234", tmp_base=tmp_path)
        assert res.reused is True
        assert res.worktree_dir == target
        assert res.branch == "feature_abcd1234"


def test_ensure_task_worktree_existing_but_not_registered_raises(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = tmp_path / "repo_feature_abcd1234"
    target.mkdir()

    def fake_run(cmd, capture_output, text):
        if cmd[3:] == ["rev-parse", "--show-toplevel"]:
            return _cp(stdout=str(repo_root) + "\n", returncode=0)
        if cmd[3:] == ["worktree", "list", "--porcelain"]:
            return _cp(stdout=f"worktree {repo_root}\n", returncode=0)
        raise AssertionError(f"unexpected git call: {cmd}")

    with patch("src.claude_code_api.services.worktree.subprocess.run", side_effect=fake_run):
        with pytest.raises(WorktreeError):
            ensure_task_worktree(repo_root, task_id="abcd1234", tmp_base=tmp_path)


def test_ensure_task_worktree_create_new_success(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = tmp_path / "repo_feature_abcd1234"

    def fake_run(cmd, capture_output, text):
        if cmd[3:] == ["rev-parse", "--show-toplevel"]:
            return _cp(stdout=str(repo_root) + "\n", returncode=0)
        if cmd[3:] == ["worktree", "add", "-b", "feature_abcd1234", str(target)]:
            return _cp(stdout="", returncode=0)
        raise AssertionError(f"unexpected git call: {cmd}")

    with patch("src.claude_code_api.services.worktree.subprocess.run", side_effect=fake_run):
        res = ensure_task_worktree(repo_root, task_id="abcd1234", tmp_base=tmp_path)
        assert res.reused is False
        assert res.worktree_dir == target


def test_ensure_task_worktree_branch_exists_fallback_add(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = tmp_path / "repo_feature_abcd1234"

    calls = []

    def fake_run(cmd, capture_output, text):
        calls.append(cmd)
        if cmd[3:] == ["rev-parse", "--show-toplevel"]:
            return _cp(stdout=str(repo_root) + "\n", returncode=0)
        if cmd[3:] == ["worktree", "add", "-b", "feature_abcd1234", str(target)]:
            return _cp(stderr="fatal: a branch named 'feature_abcd1234' already exists", returncode=128)
        if cmd[3:] == ["worktree", "add", str(target), "feature_abcd1234"]:
            return _cp(stdout="", returncode=0)
        raise AssertionError(f"unexpected git call: {cmd}")

    with patch("src.claude_code_api.services.worktree.subprocess.run", side_effect=fake_run):
        res = ensure_task_worktree(repo_root, task_id="abcd1234", tmp_base=tmp_path)
        assert res.reused is False
        assert res.worktree_dir == target
        assert any("-b" in c for c in (" ".join(x) for x in calls))

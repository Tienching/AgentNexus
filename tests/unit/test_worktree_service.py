# -*- coding: utf-8 -*-

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.server.services import (
    RepoWorktreeRegistry,
    WorktreeError,
    ensure_task_worktree,
)
from src.runtime.stores.db import Database
from src.runtime.commands.slash.worktree import (
    compute_repo_cache_key,
    ensure_bare_repo_cache,
    is_git_worktree,
    provision_cached_worktree,
)


def _cp(stdout: str = "", stderr: str = "", returncode: int = 0):
    class CP:
        def __init__(self):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    return CP()


def test_is_git_worktree_true():
    with patch("src.runtime.commands.slash.worktree.subprocess.run") as m:
        m.return_value = _cp(stdout="true\n", returncode=0)
        assert is_git_worktree(Path("/repo")) is True


def test_is_git_worktree_false():
    with patch("src.runtime.commands.slash.worktree.subprocess.run") as m:
        m.return_value = _cp(stdout="false\n", returncode=0)
        assert is_git_worktree(Path("/repo")) is False


def test_ensure_task_worktree_not_git_repo_raises():
    with patch("src.runtime.commands.slash.worktree.subprocess.run") as m:
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

    with patch("src.runtime.commands.slash.worktree.subprocess.run", side_effect=fake_run):
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

    with patch("src.runtime.commands.slash.worktree.subprocess.run", side_effect=fake_run):
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

    with patch("src.runtime.commands.slash.worktree.subprocess.run", side_effect=fake_run):
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

    with patch("src.runtime.commands.slash.worktree.subprocess.run", side_effect=fake_run):
        res = ensure_task_worktree(repo_root, task_id="abcd1234", tmp_base=tmp_path)
        assert res.reused is False
        assert res.worktree_dir == target
        assert any("-b" in c for c in (" ".join(x) for x in calls))


def test_ensure_bare_repo_cache_clones_and_registers(tmp_path: Path, monkeypatch):
    cache_root = tmp_path / "cache"
    cache_dir = cache_root / f"demo-{compute_repo_cache_key(repo_url='https://example.com/acme/demo.git')}.git"

    calls = []

    def fake_run(cmd, capture_output, text):
        calls.append(cmd)
        if cmd[:4] == ["git", "clone", "--bare", "https://example.com/acme/demo.git"]:
            cache_dir.mkdir(parents=True, exist_ok=True)
            return _cp(stdout="", returncode=0)
        raise AssertionError(f"unexpected git call: {cmd}")

    with patch("src.runtime.commands.slash.worktree.subprocess.run", side_effect=fake_run):
        path, reused = ensure_bare_repo_cache(
            repo_url="https://example.com/acme/demo.git",
            cache_base=cache_root,
            fetch=False,
        )

    assert reused is False
    assert path == cache_dir
    assert calls[0][:4] == ["git", "clone", "--bare", "https://example.com/acme/demo.git"]


def test_ensure_bare_repo_cache_fetches_existing(tmp_path: Path):
    cache_root = tmp_path / "cache"
    repo_url = "https://example.com/acme/demo.git"
    cache_dir = cache_root / f"demo-{compute_repo_cache_key(repo_url=repo_url)}.git"
    cache_dir.mkdir(parents=True)

    calls = []

    def fake_run(cmd, capture_output, text):
        calls.append(cmd)
        if cmd[:2] == ["git", f"--git-dir={cache_dir}"] and cmd[2:] == ["fetch", "--all", "--prune"]:
            return _cp(stdout="", returncode=0)
        raise AssertionError(f"unexpected git call: {cmd}")

    with patch("src.runtime.commands.slash.worktree.subprocess.run", side_effect=fake_run):
        path, reused = ensure_bare_repo_cache(
            repo_url=repo_url,
            cache_base=cache_root,
        )

    assert reused is True
    assert path == cache_dir
    assert calls == [["git", f"--git-dir={cache_dir}", "fetch", "--all", "--prune"]]


def test_provision_cached_worktree_uses_repo_level_lock_and_registers_existing_target(tmp_path: Path):
    cache_root = tmp_path / "cache"
    target_root = tmp_path / "worktrees"
    repo_url = "https://example.com/acme/demo.git"
    repo_key = compute_repo_cache_key(repo_url=repo_url)
    cache_dir = cache_root / f"demo-{repo_key}.git"
    target = target_root / "demo_feature_abcd1234"
    cache_dir.mkdir(parents=True)
    target.mkdir(parents=True)

    def fake_run(cmd, capture_output, text):
        if cmd[:2] == ["git", f"--git-dir={cache_dir}"] and cmd[2:] == ["fetch", "--all", "--prune"]:
            return _cp(stdout="", returncode=0)
        if cmd[:2] == ["git", f"--git-dir={cache_dir}"] and cmd[2:] == ["worktree", "list", "--porcelain"]:
            return _cp(stdout=f"worktree {target}\nHEAD deadbeef\n", returncode=0)
        raise AssertionError(f"unexpected git call: {cmd}")

    with patch("src.runtime.commands.slash.worktree.subprocess.run", side_effect=fake_run):
        result = provision_cached_worktree(
            task_id="abcd1234",
            repo_url=repo_url,
            tmp_base=target_root,
            cache_base=cache_root,
        )

    assert result.repo_key == repo_key
    assert result.cache_dir == cache_dir
    assert result.worktree.worktree_dir == target
    assert result.worktree.reused is True


def test_register_task_handoff_keeps_same_repo_url_worktrees_separate(tmp_path: Path):
    db = Database(str(tmp_path / "registry.db"))
    registry = RepoWorktreeRegistry(db)
    repo_url = "https://example.com/acme/demo.git"
    repo_root = str(tmp_path / "repo")
    worktree_one = str(tmp_path / "demo_feature_t1")
    worktree_two = str(tmp_path / "demo_feature_t2")

    first = registry.register_task_handoff(
        task_id="t1",
        repo_url=repo_url,
        repo_root=repo_root,
        worktree_path=worktree_one,
    )
    second = registry.register_task_handoff(
        task_id="t2",
        repo_url=repo_url,
        repo_root=repo_root,
        worktree_path=worktree_two,
    )

    records = registry.list_records(repo_root=repo_root)
    assert first.repo_key != second.repo_key
    assert {record.task_id for record in records} == {"t1", "t2"}
    assert {record.worktree_path for record in records} == {worktree_one, worktree_two}


def test_register_task_handoff_without_worktree_uses_task_specific_key(tmp_path: Path):
    db = Database(str(tmp_path / "registry.db"))
    registry = RepoWorktreeRegistry(db)
    repo_url = "https://example.com/acme/demo.git"
    repo_root = str(tmp_path / "repo")

    first = registry.register_task_handoff(task_id="t1", repo_url=repo_url, repo_root=repo_root)
    second = registry.register_task_handoff(task_id="t2", repo_url=repo_url, repo_root=repo_root)

    records = registry.list_records(repo_root=repo_root)
    assert first.repo_key != second.repo_key
    assert {record.task_id for record in records} == {"t1", "t2"}


def test_regular_registry_repo_key_matches_cached_provision_key(tmp_path: Path):
    db = Database(str(tmp_path / "registry.db"))
    registry = RepoWorktreeRegistry(db)
    repo_url = "https://example.com/acme/demo.git"
    expected_repo_key = compute_repo_cache_key(repo_url=repo_url)

    record = registry.register(
        repo_url=repo_url,
        repo_root=str(tmp_path / "repo"),
        worktree_path=str(tmp_path / "demo_feature_t1"),
    )
    cache = registry.register_cache(
        repo_url=repo_url,
        cache_path=str(tmp_path / "cache" / "demo.git"),
    )

    assert record.repo_key == expected_repo_key
    assert cache.repo_key == expected_repo_key


def test_repo_worktree_registry_tracks_bare_cache_and_cache_level_lock(tmp_path: Path):
    db = Database(str(tmp_path / "registry.db"))
    registry = RepoWorktreeRegistry(db)
    cache = registry.register_cache(
        repo_url="https://example.com/acme/demo.git",
        cache_path=str(tmp_path / "cache" / "demo.git"),
        metadata={"provider": "github"},
    )

    assert registry.acquire_cache_lock(cache.repo_key, owner="worker-a", ttl_seconds=30) is True
    assert registry.acquire_cache_lock(cache.repo_key, owner="worker-b", ttl_seconds=30) is False
    assert registry.release_cache_lock(cache.repo_key, owner="worker-a") is True
    assert registry.acquire_cache_lock(cache.repo_key, owner="worker-b", ttl_seconds=30) is True


def test_provision_cached_worktree_registers_task_handoff_key(tmp_path: Path):
    cache_root = tmp_path / "cache"
    target_root = tmp_path / "worktrees"
    repo_url = "https://example.com/acme/demo.git"
    repo_key = compute_repo_cache_key(repo_url=repo_url)
    cache_dir = cache_root / f"demo-{repo_key}.git"
    target = target_root / "demo_feature_abcd1234"
    cache_dir.mkdir(parents=True)
    calls = []

    class FakeRegistry:
        def register_task_handoff(self, **kwargs):
            calls.append(kwargs)

        def register_cache(self, **kwargs):
            pass

    def fake_run(cmd, capture_output, text):
        if cmd[:2] == ["git", f"--git-dir={cache_dir}"] and cmd[2:] == ["fetch", "--all", "--prune"]:
            return _cp(stdout="", returncode=0)
        if cmd[:2] == ["git", f"--git-dir={cache_dir}"] and cmd[2:] == ["worktree", "add", "-b", "feature_abcd1234", str(target), "HEAD"]:
            return _cp(stdout="", returncode=0)
        raise AssertionError(f"unexpected git call: {cmd}")

    with patch("src.runtime.commands.slash.worktree.subprocess.run", side_effect=fake_run), \
         patch("src.server.services.worktree_registry.get_repo_worktree_registry", return_value=FakeRegistry()):
        provision_cached_worktree(
            task_id="abcd1234",
            repo_url=repo_url,
            tmp_base=target_root,
            cache_base=cache_root,
        )

    assert calls == [{
        "task_id": "abcd1234",
        "repo_url": repo_url,
        "repo_root": None,
        "worktree_path": str(target),
        "branch_name": "feature_abcd1234",
        "metadata": {"cache_dir": str(cache_dir), "provisioning": "cached"},
    }]

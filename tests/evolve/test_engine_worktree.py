"""Tests for the worktree parallel execution engine."""

import asyncio
import pytest
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

from src.nanobot.evolve.models import EvolutionConfig, EvolutionSession, EvolutionTask
from src.nanobot.evolve.engine import EvolutionEngine, WorktreeTaskResult
from src.nanobot.evolve.codebuddy_executor import ExecutionResult


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo for worktree tests."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True)
    # Create an initial commit so worktree can branch from HEAD
    (tmp_path / "README.md").write_text("test repo")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    return tmp_path


@pytest.fixture
def config(git_repo):
    return EvolutionConfig(
        enabled=True,
        working_dir=str(git_repo),
        memory_path=str(git_repo / "memory"),
        codebuddy_path="codebuddy",
        codebuddy_timeout=30,
        max_tasks_per_session=3,
        use_worktree=True,
        worktree_base_dir=".evolve",
        parallel_tasks=True,
    )


@pytest.fixture
def engine(config):
    return EvolutionEngine(config)


def _make_task(task_id: str, title: str, files: list[str] | None = None) -> EvolutionTask:
    return EvolutionTask(
        id=task_id,
        title=title,
        files=files or ["src/test.py"],
        description=f"Fix {title}",
    )


def _make_session(engine) -> EvolutionSession:
    return EvolutionSession(id="abc123", day=2, date="2026-01-02")


class TestWorktreeHelpers:
    def test_worktree_base_path(self, engine, git_repo):
        base = engine._worktree_base()
        assert base == git_repo / ".evolve"

    def test_create_and_remove_worktree(self, engine, git_repo):
        """Should create a worktree and then remove it cleanly."""
        wt_path = git_repo / ".evolve" / "test-wt"
        branch = "evolve/test-branch"

        success = engine._create_worktree(branch, wt_path)
        assert success is True
        assert wt_path.exists()
        assert (wt_path / "README.md").exists()  # shares main repo files

        engine._remove_worktree(branch, wt_path)
        assert not wt_path.exists()

    def test_create_worktree_bad_path(self, engine, git_repo):
        """Creating worktree on existing branch should fail gracefully."""
        wt_path = git_repo / ".evolve" / "test-fail"
        # Create it once
        engine._create_worktree("evolve/once", wt_path)
        # Creating same branch again should fail
        wt_path2 = git_repo / ".evolve" / "test-fail2"
        ok = engine._create_worktree("evolve/once", wt_path2)
        assert ok is False
        # Cleanup
        engine._remove_worktree("evolve/once", wt_path)

    def test_cleanup_stale_worktrees(self, engine, git_repo):
        """Stale worktrees should be cleaned up on session start."""
        wt_path = git_repo / ".evolve" / "session-stale-t-001"
        engine._create_worktree("evolve/stale-branch", wt_path)
        assert wt_path.exists()

        engine._cleanup_stale_worktrees()
        assert not wt_path.exists()

    def test_cleanup_stale_no_evolve_dir(self, engine):
        """Cleanup should not crash when .evolve dir doesn't exist."""
        engine._cleanup_stale_worktrees()  # Should not raise


class TestWorktreeTaskResult:
    def test_default_values(self):
        task = _make_task("t-001", "Test task")
        result = WorktreeTaskResult(task=task)
        assert result.success is False
        assert result.merge_status == "pending"
        assert result.files_changed == []
        assert result.error is None


class TestParallelImplementation:
    @pytest.mark.asyncio
    async def test_parallel_spawns_multiple_worktrees(self, engine, git_repo):
        """Parallel mode should spawn one worktree per task."""
        session = _make_session(engine)
        tasks = [
            _make_task("t-001", "Fix bug A", ["src/a.py"]),
            _make_task("t-002", "Fix bug B", ["src/b.py"]),
        ]
        session.tasks = tasks

        worktrees_created = []

        original_run = engine._run_task_in_worktree

        async def track_worktree(task, sess, ctx, day, sha, branch, wt_path):
            worktrees_created.append(branch)
            return WorktreeTaskResult(
                task=task,
                success=True,
                branch_name=branch,
                worktree_path=str(wt_path),
                files_changed=task.files,
            )

        with patch.object(engine, "_run_task_in_worktree", side_effect=track_worktree), \
             patch.object(engine, "_merge_worktree_results", new_callable=AsyncMock):
            await engine._run_implementation_parallel(session)

        assert len(worktrees_created) == 2
        assert all("abc123" in b for b in worktrees_created)

    @pytest.mark.asyncio
    async def test_merge_successful_results(self, engine, git_repo):
        """Successful worktrees should be merged into main branch."""
        session = _make_session(engine)
        task = _make_task("t-001", "Fix A")

        # Create a real worktree, make a commit, then merge
        wt_path = git_repo / ".evolve" / "session-merge-test"
        branch = "evolve/merge-test"
        engine._create_worktree(branch, wt_path)

        # Make a commit in the worktree
        (wt_path / "fix_a.txt").write_text("fixed")
        subprocess.run(["git", "add", "."], cwd=str(wt_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "fix a"], cwd=str(wt_path), capture_output=True)

        results = [WorktreeTaskResult(
            task=task,
            success=True,
            branch_name=branch,
            worktree_path=str(wt_path),
            files_changed=["fix_a.txt"],
        )]

        await engine._merge_worktree_results(results, session, day=2)

        assert results[0].merge_status == "merged"
        # Worktree should be cleaned up
        assert not wt_path.exists()

    @pytest.mark.asyncio
    async def test_failed_task_not_merged(self, engine, git_repo):
        """Failed tasks should not be merged."""
        session = _make_session(engine)
        task = _make_task("t-001", "Failed task")

        results = [WorktreeTaskResult(
            task=task,
            success=False,
            branch_name="evolve/no-branch",
            worktree_path=str(git_repo / ".evolve" / "nonexistent"),
            error="CodeBuddy failed",
        )]

        await engine._merge_worktree_results(results, session, day=2)
        assert results[0].merge_status == "failed"

    @pytest.mark.asyncio
    async def test_metrics_updated_after_parallel(self, engine, git_repo):
        """Metrics should reflect parallel task outcomes."""
        session = _make_session(engine)
        tasks = [
            _make_task("t-001", "Success task", ["src/a.py"]),
            _make_task("t-002", "Fail task", ["src/b.py"]),
        ]
        session.tasks = tasks

        async def fake_run_task(task, sess, ctx, day, sha, branch, wt_path):
            if task.id == "t-001":
                return WorktreeTaskResult(
                    task=task, success=True, branch_name=branch,
                    worktree_path=str(wt_path), files_changed=["src/a.py"]
                )
            return WorktreeTaskResult(
                task=task, success=False, branch_name=branch,
                worktree_path=str(wt_path), error="failed"
            )

        async def fake_merge(results, sess, day):
            for r in results:
                if r.success:
                    r.merge_status = "merged"
                else:
                    r.merge_status = "failed"

        with patch.object(engine, "_run_task_in_worktree", side_effect=fake_run_task), \
             patch.object(engine, "_merge_worktree_results", side_effect=fake_merge):
            await engine._run_implementation_parallel(session)

        assert session.metrics.tasks_completed == 1
        assert session.metrics.tasks_failed == 1

    @pytest.mark.asyncio
    async def test_run_implementation_routes_to_parallel(self, engine):
        """run_implementation should use parallel mode when configured."""
        session = _make_session(engine)
        session.tasks = [_make_task("t-001", "Task A")]

        with patch.object(engine, "_run_implementation_parallel", new_callable=AsyncMock) as mock_par, \
             patch.object(engine, "_run_implementation_serial", new_callable=AsyncMock) as mock_ser:
            await engine.run_implementation(session)

        mock_par.assert_called_once()
        mock_ser.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_implementation_routes_to_serial(self, config):
        """run_implementation should use serial mode when worktree disabled."""
        config.use_worktree = False
        engine = EvolutionEngine(config)
        session = _make_session(engine)
        session.tasks = [_make_task("t-001", "Task A")]

        with patch.object(engine, "_run_implementation_parallel", new_callable=AsyncMock) as mock_par, \
             patch.object(engine, "_run_implementation_serial", new_callable=AsyncMock) as mock_ser:
            await engine.run_implementation(session)

        mock_ser.assert_called_once()
        mock_par.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_worktrees_cleaned_on_start(self, engine, git_repo):
        """Full cycle should clean up stale worktrees at start."""
        # Create a stale worktree
        stale_path = git_repo / ".evolve" / "session-stale-t-000"
        engine._create_worktree("evolve/stale-session", stale_path)
        assert stale_path.exists()

        success_result = MagicMock()
        success_result.status = "completed"

        with patch.object(engine, "run_assessment", new_callable=AsyncMock), \
             patch.object(engine, "run_planning", new_callable=AsyncMock), \
             patch.object(engine, "run_implementation", new_callable=AsyncMock), \
             patch.object(engine, "run_reflection", new_callable=AsyncMock):
            await engine.run_full_cycle()

        # Stale worktree should have been cleaned
        assert not stale_path.exists()

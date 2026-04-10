"""Execution infrastructure for the self-evolution system.

Enhanced with WorktreeManager integration for agent-level isolation,
session resume, and garbage collection.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from src.nanobot.evolve.prompts import (
    build_conflict_resolution_prompt,
    build_implementation_prompt,
)
from src.runtime.commands.slash.worktree import (
    IsolationLevel,
    WorktreeEntry,
    WorktreeGarbageCollector,
    WorktreeManager,
)

if TYPE_CHECKING:
    from src.nanobot.evolve.models import EvolutionSession, EvolutionTask
    from src.nanobot.evolve.runtime import EvolutionEngine


@dataclass
class WorktreeTaskResult:
    """Result from running a task in a git worktree."""

    task: "EvolutionTask"
    success: bool = False
    branch_name: str = ""
    worktree_path: str = ""
    files_changed: list[str] = field(default_factory=list)
    error: str | None = None
    merge_status: str = "pending"  # pending | merged | conflict | failed


def run_shell(engine: "EvolutionEngine", cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a shell command, return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(engine._working_dir),
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out after {timeout}s"
    except Exception as exc:
        return 1, "", str(exc)


def get_git_diff_files(engine: "EvolutionEngine", base_sha: str) -> list[str]:
    """Get list of files changed since base_sha."""
    code, stdout, _ = engine._run_shell(f"git diff --name-only {base_sha}..HEAD")
    if code != 0:
        return []
    return [line.strip() for line in stdout.splitlines() if line.strip()]


def get_current_sha(engine: "EvolutionEngine") -> str:
    """Get current HEAD SHA."""
    _, stdout, _ = engine._run_shell("git rev-parse HEAD")
    return stdout.strip()


def worktree_base(engine: "EvolutionEngine") -> Path:
    return engine._working_dir / engine.config.worktree_base_dir


def cleanup_stale_worktrees(engine: "EvolutionEngine") -> None:
    """Remove any leftover worktrees from crashed previous sessions."""
    base = engine._worktree_base()
    if not base.exists():
        return
    for wt_dir in base.iterdir():
        if wt_dir.is_dir() and wt_dir.name.startswith("session-"):
            logger.warning("Evolution: removing stale worktree {}", wt_dir)
            engine._run_shell(f"git worktree remove {wt_dir} --force")
            branch = f"evolve/{wt_dir.name}"
            engine._run_shell(f"git branch -D {branch}")


def create_worktree(engine: "EvolutionEngine", branch_name: str, worktree_path: Path) -> bool:
    """Create a git worktree on a new branch. Returns True on success."""
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    code, _, err = engine._run_shell(f"git worktree add {worktree_path} -b {branch_name}")
    if code != 0:
        logger.error("Evolution: failed to create worktree {}: {}", worktree_path, err)
        return False
    return True


def remove_worktree(engine: "EvolutionEngine", branch_name: str, worktree_path: Path) -> None:
    """Remove a worktree and its branch (best-effort)."""
    engine._run_shell(f"git worktree remove {worktree_path} --force")
    engine._run_shell(f"git branch -D {branch_name}")


def get_worktree_commits(engine: "EvolutionEngine", branch_name: str, base_sha: str) -> list[str]:
    """Get commits on branch since base_sha."""
    _, stdout, _ = engine._run_shell(f"git log --oneline {base_sha}..{branch_name}")
    return [line.strip() for line in stdout.splitlines() if line.strip()]


async def run_implementation(engine: "EvolutionEngine", session: "EvolutionSession") -> None:
    """Phase B: Execute tasks, either in parallel worktrees or serially."""
    if engine.config.use_worktree and engine.config.parallel_tasks:
        await engine._run_implementation_parallel(session)
    else:
        await engine._run_implementation_serial(session)


async def run_implementation_parallel(engine: "EvolutionEngine", session: "EvolutionSession") -> None:
    """Run tasks in parallel, each in its own git worktree."""
    await engine._log("Phase B: Parallel worktree implementation starting...", session)
    session.phase = "implementation"

    tasks = session.tasks
    if not tasks:
        await engine._log("No tasks to implement", session)
        return

    engine._cleanup_stale_worktrees()

    context = engine._build_context()
    session_number = session.day
    base_sha = engine._get_current_sha()
    max_tasks = min(len(tasks), engine.config.max_tasks_per_session)
    active_tasks = tasks[:max_tasks]

    await engine._log(f"  Spawning {len(active_tasks)} worktrees in parallel...", session)

    worktree_infos: list[tuple[object, str, Path]] = []
    for task in active_tasks:
        branch_name = f"evolve/{session.id}-{task.id}"
        worktree_path = engine._worktree_base() / f"session-{session.id}-{task.id}"
        worktree_infos.append((task, branch_name, worktree_path))

    results: list[WorktreeTaskResult] = await asyncio.gather(
        *[
            engine._run_task_in_worktree(task, session, context, session_number, base_sha, branch_name, worktree_path)
            for task, branch_name, worktree_path in worktree_infos
        ]
    )

    await engine._merge_worktree_results(results, session, session_number)

    for result in results:
        if result.merge_status == "merged":
            session.metrics.tasks_completed += 1
            session.metrics.files_changed += len(result.files_changed)
            result.task.status = "completed"
        elif result.merge_status in ("conflict", "failed"):
            session.metrics.tasks_failed += 1
            result.task.status = "failed"
            result.task.error = result.error or f"Merge status: {result.merge_status}"
        else:
            session.metrics.tasks_failed += 1
            result.task.status = "failed"
            result.task.error = result.error or "Unknown error"


async def run_task_in_worktree(
    engine: "EvolutionEngine",
    task: "EvolutionTask",
    session: "EvolutionSession",
    context: str,
    session_number: int,
    base_sha: str,
    branch_name: str,
    worktree_path: Path,
) -> WorktreeTaskResult:
    """Execute a single task in an isolated git worktree."""
    result = WorktreeTaskResult(task=task, branch_name=branch_name, worktree_path=str(worktree_path))

    if not engine._create_worktree(branch_name, worktree_path):
        result.error = f"Failed to create worktree {worktree_path}"
        return result

    task.status = "running"
    await engine._log(f"  [WT] {task.id}: {task.title}", session)

    venv_python = engine._working_dir / ".venv" / "bin" / "python"
    pytest_cmd = (
        f"{venv_python} -m pytest tests/ -x -q --tb=short 2>&1 | head -30"
        if venv_python.exists()
        else "python -m pytest tests/ -x -q --tb=short 2>&1 | head -30"
    )

    prompt = build_implementation_prompt(
        engine.config,
        session_number=session_number,
        context=context,
        task=task,
        branch_name=branch_name,
        pytest_cmd=pytest_cmd,
        working_dir=str(engine._working_dir),
    )

    exec_result = await engine._executor.execute(
        prompt=prompt,
        tools="Read,Write,Edit,MultiEdit,Bash,Grep,Glob",
        timeout=engine.config.codebuddy_timeout,
        working_dir=str(worktree_path),
    )

    if not exec_result.success:
        result.error = exec_result.error or "CodeBuddy execution failed"
        await engine._log(f"  [WT] {task.id} FAILED: {result.error}", session)
        return result

    commits = engine._get_worktree_commits(branch_name, base_sha)
    if not commits:
        result.error = "No commits produced"
        await engine._log(f"  [WT] {task.id}: no commits — skipping", session)
        return result

    _, stdout, _ = engine._run_shell(
        f"git diff --name-only {base_sha}..{branch_name} -- " + " ".join(engine.config.protected_files)
    )
    if stdout.strip():
        result.error = f"Modified protected files: {stdout.strip()}"
        await engine._log(f"  [WT] {task.id} BLOCKED: {result.error}", session)
        return result

    _, diff_out, _ = engine._run_shell(f"git diff --name-only {base_sha}..{branch_name}")
    result.files_changed = [line.strip() for line in diff_out.splitlines() if line.strip()]
    result.success = True
    await engine._log(
        f"  [WT] {task.id} ✓ ready ({len(commits)} commit(s), {len(result.files_changed)} file(s))",
        session,
    )
    return result


async def merge_worktree_results(
    engine: "EvolutionEngine",
    results: list[WorktreeTaskResult],
    session: "EvolutionSession",
    session_number: int,
) -> None:
    """Sequentially merge successful worktree results into main branch."""
    await engine._log("  Merging worktrees into main branch...", session)

    for result in results:
        try:
            if not result.success:
                result.merge_status = "failed"
                continue

            merged = await engine._try_merge(result, session, session_number)
            if not merged:
                result.merge_status = "conflict"
                await engine._log(
                    f"  ✗ Could not merge: {result.task.title} — will retry next session",
                    session,
                )
        finally:
            engine._remove_worktree(result.branch_name, Path(result.worktree_path))


async def try_merge(
    engine: "EvolutionEngine",
    result: WorktreeTaskResult,
    session: "EvolutionSession",
    session_number: int,
) -> bool:
    """Attempt to merge a worktree branch with escalating conflict resolution."""
    commit_msg = f"Session {session_number}: {result.task.title} [worktree]"

    code, _, err = engine._run_shell(f'git merge --no-ff {result.branch_name} -m "{commit_msg}"', timeout=30)
    if code == 0:
        result.merge_status = "merged"
        await engine._log(f"  ✓ Merged: {result.task.title}", session)
        return True

    engine._run_shell("git merge --abort")

    await engine._log(
        f"  ⚠ Conflict on '{result.task.title}' — trying auto-resolve (-X theirs)...",
        session,
    )
    code2, _, _ = engine._run_shell(
        f'git merge --no-ff -X theirs {result.branch_name} -m "{commit_msg} [auto-resolved]"',
        timeout=30,
    )
    if code2 == 0:
        result.merge_status = "merged"
        await engine._log(f"  ✓ Merged with auto-resolve: {result.task.title}", session)
        return True

    engine._run_shell("git merge --abort")

    await engine._log("  ⚠ Auto-resolve failed — asking codebuddy to resolve conflicts...", session)
    resolved = await engine._codebuddy_resolve_conflict(result, session, session_number)
    if resolved:
        result.merge_status = "merged"
        await engine._log(f"  ✓ Merged with codebuddy resolution: {result.task.title}", session)
        return True

    result.error = f"All merge strategies failed: {err[:200]}"
    return False


async def codebuddy_resolve_conflict(
    engine: "EvolutionEngine",
    result: WorktreeTaskResult,
    session: "EvolutionSession",
    session_number: int,
) -> bool:
    """Use codebuddy to resolve merge conflicts interactively."""
    commit_msg = f"Session {session_number}: {result.task.title} [worktree, conflict-resolved]"

    engine._run_shell(f"git merge --no-ff --no-commit {result.branch_name}", timeout=30)

    _, conflict_out, _ = engine._run_shell("git diff --name-only --diff-filter=U")
    conflicted = [line.strip() for line in conflict_out.splitlines() if line.strip()]

    if not conflicted:
        code, _, _ = engine._run_shell(f'git commit -m "{commit_msg}"')
        if code == 0:
            return True
        engine._run_shell("git merge --abort")
        return False

    await engine._log(f"    Conflicts in: {', '.join(conflicted)} — asking codebuddy...", session)

    prompt = build_conflict_resolution_prompt(
        engine.config,
        branch_name=result.branch_name,
        task=result.task,
        files_changed=result.files_changed,
        conflicted_files=conflicted,
        commit_msg=commit_msg,
    )
    await engine._executor.execute(
        prompt=prompt,
        tools="Read,Write,Edit,Bash,Grep",
        timeout=engine.config.codebuddy_timeout,
        working_dir=str(engine._working_dir),
    )

    _, log_out, _ = engine._run_shell("git log --oneline -1 --format='%s'")
    if commit_msg[:30] in log_out or "conflict-resolved" in log_out:
        return True

    _, status_out, _ = engine._run_shell("git status --short")
    if "UU " in status_out or "AA " in status_out:
        engine._run_shell("git merge --abort")
        return False

    _, grep_out, _ = engine._run_shell('grep -r "<<<<<<" ' + " ".join(conflicted) + ' 2>/dev/null || true')
    if not grep_out.strip():
        code, _, _ = engine._run_shell(f'git commit -m "{commit_msg}"')
        return code == 0

    engine._run_shell("git merge --abort")
    return False


async def run_implementation_serial(engine: "EvolutionEngine", session: "EvolutionSession") -> None:
    """Fallback: run tasks serially in the main working directory."""
    await engine._log("Phase B: Serial implementation starting...", session)
    session.phase = "implementation"

    tasks = session.tasks
    if not tasks:
        await engine._log("No tasks to implement", session)
        return

    context = engine._build_context()
    session_number = session.day
    max_tasks = min(len(tasks), engine.config.max_tasks_per_session)

    for index, task in enumerate(tasks[:max_tasks]):
        await engine._log(f"  → Task {index + 1}/{max_tasks}: {task.title}", session)
        task.status = "running"

        pre_sha = engine._get_current_sha()
        prompt = build_implementation_prompt(
            engine.config,
            session_number=session_number,
            context=context,
            task=task,
            branch_name="main-working-tree",
            pytest_cmd="python -m pytest tests/ -x -q --tb=short 2>&1 | head -30",
            working_dir=str(engine._working_dir),
        )

        exec_result = await engine._executor.execute(
            prompt=prompt,
            tools="Read,Write,Edit,MultiEdit,Bash,Grep,Glob",
            timeout=engine.config.codebuddy_timeout,
            working_dir=str(engine._working_dir),
        )

        changed_files = engine._get_git_diff_files(pre_sha)
        is_valid, violations = engine._identity.validate_changes(changed_files)
        if not is_valid:
            await engine._log(f"    BLOCKED: modified protected files {violations}", session)
            engine._run_shell(f"git reset --hard {pre_sha}")
            task.status = "failed"
            task.error = f"Modified protected files: {violations}"
            session.metrics.tasks_failed += 1
            continue

        code, _, _ = engine._run_shell("python -m pytest tests/ -x -q --tb=short 2>&1 | head -50", timeout=120)
        if code != 0 and not exec_result.success:
            await engine._log(f"    FAILED: {exec_result.error or 'tests failed'}", session)
            engine._run_shell(f"git reset --hard {pre_sha}")
            task.status = "failed"
            task.error = exec_result.error or "Tests failed after implementation"
            session.metrics.tasks_failed += 1
            continue

        task.status = "completed"
        task.output = exec_result.output[:2000] if exec_result.output else ""
        session.metrics.tasks_completed += 1
        session.metrics.files_changed += len(changed_files)
        await engine._log(f"    ✓ Completed: {task.title}", session)


# ---------------------------------------------------------------------------
# Enhanced: WorktreeManager integration for agent-level isolation
# ---------------------------------------------------------------------------

def get_worktree_manager(engine: "EvolutionEngine") -> WorktreeManager:
    """Get or create a WorktreeManager for the evolution engine's workspace."""
    if not hasattr(engine, "_wt_manager") or engine._wt_manager is None:
        engine._wt_manager = WorktreeManager(engine._working_dir)
    return engine._wt_manager


async def run_implementation_isolated(engine: "EvolutionEngine", session: "EvolutionSession") -> None:
    """Phase B: Execute tasks in AGENT-isolated worktrees via WorktreeManager.

    Each task gets its own worktree tracked by the WorktreeManager with
    AGENT-level isolation. This provides full lifecycle management including
    session resume and garbage collection.
    """
    await engine._log("Phase B: Isolated worktree implementation starting...", session)
    session.phase = "implementation"

    tasks = session.tasks
    if not tasks:
        await engine._log("No tasks to implement", session)
        return

    manager = get_worktree_manager(engine)
    gc = WorktreeGarbageCollector(manager)

    # Clean up stale worktrees from previous sessions
    gc_result = gc.collect(max_age_hours=24, dry_run=False)
    if gc_result.removed or gc_result.stashed:
        await engine._log(
            f"  GC: removed={len(gc_result.removed)}, stashed={len(gc_result.stashed)}",
            session,
        )

    context = engine._build_context()
    session_number = session.day
    base_sha = engine._get_current_sha()
    max_tasks = min(len(tasks), engine.config.max_tasks_per_session)
    active_tasks = tasks[:max_tasks]

    await engine._log(f"  Spawning {len(active_tasks)} isolated worktrees...", session)

    # Create isolated worktree entries for each task
    entries: list[tuple[EvolutionTask, WorktreeEntry]] = []
    for task in active_tasks:
        try:
            entry = manager.create_isolated(
                isolation_level=IsolationLevel.AGENT,
                agent_name=f"evolve-{session.id}-{task.id}",
                task_id=task.id,
            )
            entries.append((task, entry))
            await engine._log(f"  [WT] {task.id}: worktree created at {entry.path}", session)
        except Exception as exc:
            task.status = "failed"
            task.error = f"Failed to create worktree: {exc}"
            session.metrics.tasks_failed += 1
            await engine._log(f"  [WT] {task.id} FAILED: {exc}", session)

    # Run tasks in parallel
    results: list[WorktreeTaskResult] = await asyncio.gather(
        *[
            _run_task_in_isolated_worktree(
                engine, task, session, context, session_number,
                base_sha, entry.branch, Path(entry.path),
            )
            for task, entry in entries
        ]
    )

    # Merge results
    await engine._merge_worktree_results(results, session, session_number)

    for result in results:
        if result.merge_status == "merged":
            session.metrics.tasks_completed += 1
            session.metrics.files_changed += len(result.files_changed)
            result.task.status = "completed"
        elif result.merge_status in ("conflict", "failed"):
            session.metrics.tasks_failed += 1
            result.task.status = "failed"
            result.task.error = result.error or f"Merge status: {result.merge_status}"
        else:
            session.metrics.tasks_failed += 1
            result.task.status = "failed"
            result.task.error = result.error or "Unknown error"


async def _run_task_in_isolated_worktree(
    engine: "EvolutionEngine",
    task: "EvolutionTask",
    session: "EvolutionSession",
    context: str,
    session_number: int,
    base_sha: str,
    branch_name: str,
    worktree_path: Path,
) -> WorktreeTaskResult:
    """Execute a single task in a WorktreeManager-tracked worktree."""
    result = WorktreeTaskResult(task=task, branch_name=branch_name, worktree_path=str(worktree_path))

    manager = get_worktree_manager(engine)

    # Verify the worktree exists; if not, create it
    from src.runtime.commands.slash.worktree import is_git_worktree as _is_git_wt, _run_git as _run_git_raw

    if not worktree_path.exists() or not _is_git_wt(worktree_path):
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        repo_root = engine._working_dir
        res = _run_git_raw(repo_root, ["worktree", "add", "-b", branch_name, str(worktree_path)])
        if res.returncode != 0:
            stderr = (res.stderr or "").strip()
            if "already exists" in stderr.lower() and "branch" in stderr.lower():
                res2 = _run_git_raw(repo_root, ["worktree", "add", str(worktree_path), branch_name])
                if res2.returncode != 0:
                    result.error = f"Failed to create worktree: {(res2.stderr or '').strip()}"
                    return result
            else:
                result.error = f"Failed to create worktree: {stderr}"
                return result

    task.status = "running"
    await engine._log(f"  [WT] {task.id}: {task.title}", session)

    # Touch the worktree to update access time
    manager.touch(branch_name)

    venv_python = engine._working_dir / ".venv" / "bin" / "python"
    pytest_cmd = (
        f"{venv_python} -m pytest tests/ -x -q --tb=short 2>&1 | head -30"
        if venv_python.exists()
        else "python -m pytest tests/ -x -q --tb=short 2>&1 | head -30"
    )

    prompt = build_implementation_prompt(
        engine.config,
        session_number=session_number,
        context=context,
        task=task,
        branch_name=branch_name,
        pytest_cmd=pytest_cmd,
        working_dir=str(engine._working_dir),
    )

    exec_result = await engine._executor.execute(
        prompt=prompt,
        tools="Read,Write,Edit,MultiEdit,Bash,Grep,Glob",
        timeout=engine.config.codebuddy_timeout,
        working_dir=str(worktree_path),
    )

    if not exec_result.success:
        result.error = exec_result.error or "CodeBuddy execution failed"
        await engine._log(f"  [WT] {task.id} FAILED: {result.error}", session)
        return result

    commits = engine._get_worktree_commits(branch_name, base_sha)
    if not commits:
        result.error = "No commits produced"
        await engine._log(f"  [WT] {task.id}: no commits — skipping", session)
        return result

    _, stdout, _ = engine._run_shell(
        f"git diff --name-only {base_sha}..{branch_name} -- " + " ".join(engine.config.protected_files)
    )
    if stdout.strip():
        result.error = f"Modified protected files: {stdout.strip()}"
        await engine._log(f"  [WT] {task.id} BLOCKED: {result.error}", session)
        return result

    _, diff_out, _ = engine._run_shell(f"git diff --name-only {base_sha}..{branch_name}")
    result.files_changed = [line.strip() for line in diff_out.splitlines() if line.strip()]
    result.success = True
    await engine._log(
        f"  [WT] {task.id} ✓ ready ({len(commits)} commit(s), {len(result.files_changed)} file(s))",
        session,
    )
    return result

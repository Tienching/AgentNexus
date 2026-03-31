"""Core evolution engine for agent-nexus self-improvement.

Implements the three-phase evolution cycle inspired by yoyo's approach:
  Phase A1 - Assessment: Read codebase, test self, research gaps
  Phase A2 - Planning:   Create task plan from assessment
  Phase B  - Implementation: Execute tasks with CodeBuddy
  Phase C  - Reflection: Update memory and write journal
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Coroutine, Any

from loguru import logger

from src.nanobot.evolve.codebuddy_executor import CodeBuddyExecutor, ExecutionResult
from src.nanobot.evolve.identity import IdentityManager
from src.nanobot.evolve.memory import MemoryManager
from src.nanobot.evolve.models import (
    AssessmentReport,
    EvolutionConfig,
    EvolutionSession,
    EvolutionTask,
    Lesson,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _load_prompt_template(name: str, base_dir: str) -> str:
    """Load a prompt template from prompts/evolve/."""
    path = Path(base_dir) / "prompts" / "evolve" / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


@dataclass
class WorktreeTaskResult:
    """Result from running a task in a git worktree."""
    task: EvolutionTask
    success: bool = False
    branch_name: str = ""
    worktree_path: str = ""
    files_changed: list[str] = field(default_factory=list)
    error: str | None = None
    merge_status: str = "pending"  # pending | merged | conflict | failed


class EvolutionEngine:
    """Orchestrates the full evolution cycle for agent-nexus.

    Usage:
        config = EvolutionConfig(enabled=True, working_dir=".")
        engine = EvolutionEngine(config)
        session = await engine.run_full_cycle()
    """

    def __init__(
        self,
        config: EvolutionConfig,
        on_progress: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    ):
        self.config = config
        self.on_progress = on_progress
        self._working_dir = Path(config.working_dir).resolve()
        self._executor = CodeBuddyExecutor(config)
        self._identity = IdentityManager(config)
        self._memory = MemoryManager(config)

    async def _log(self, msg: str, session: EvolutionSession | None = None) -> None:
        logger.info("Evolution: {}", msg)
        if session:
            session.add_log(msg)
        if self.on_progress:
            try:
                await self.on_progress(msg)
            except Exception:
                pass

    def _build_context(self) -> str:
        """Build the shared identity context for all agents."""
        active_learnings = self._memory.load_active_learnings()
        social_learnings = self._memory.load_active_social_learnings()
        return self._identity.build_context(active_learnings, social_learnings)

    def _get_session_day(self) -> int:
        """Count completed evolution sessions from JOURNAL.md."""
        journal_path = self._working_dir / self.config.journal_path
        if not journal_path.exists():
            return 1
        content = journal_path.read_text(encoding="utf-8")
        return content.count("## Session ") + 1

    def _run_shell(self, cmd: str, timeout: int = 30) -> tuple[int, str, str]:
        """Run a shell command, return (exit_code, stdout, stderr)."""
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=str(self._working_dir)
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return 1, "", f"Command timed out after {timeout}s"
        except Exception as e:
            return 1, "", str(e)

    def _get_git_diff_files(self, base_sha: str) -> list[str]:
        """Get list of files changed since base_sha."""
        code, stdout, _ = self._run_shell(f"git diff --name-only {base_sha}..HEAD")
        if code != 0:
            return []
        return [f.strip() for f in stdout.splitlines() if f.strip()]

    def _get_current_sha(self) -> str:
        """Get current HEAD SHA."""
        _, stdout, _ = self._run_shell("git rev-parse HEAD")
        return stdout.strip()

    # ─────────────── Worktree helpers ───────────────────────────

    def _worktree_base(self) -> Path:
        return self._working_dir / self.config.worktree_base_dir

    def _cleanup_stale_worktrees(self) -> None:
        """Remove any leftover worktrees from crashed previous sessions."""
        base = self._worktree_base()
        if not base.exists():
            return
        for wt_dir in base.iterdir():
            if wt_dir.is_dir() and wt_dir.name.startswith("session-"):
                logger.warning("Evolution: removing stale worktree {}", wt_dir)
                self._run_shell(f"git worktree remove {wt_dir} --force")
                # Best-effort branch delete
                branch = f"evolve/{wt_dir.name}"
                self._run_shell(f"git branch -D {branch}")

    def _create_worktree(self, branch_name: str, worktree_path: Path) -> bool:
        """Create a git worktree on a new branch. Returns True on success."""
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        code, _, err = self._run_shell(
            f"git worktree add {worktree_path} -b {branch_name}"
        )
        if code != 0:
            logger.error("Evolution: failed to create worktree {}: {}", worktree_path, err)
            return False
        return True

    def _remove_worktree(self, branch_name: str, worktree_path: Path) -> None:
        """Remove a worktree and its branch (best-effort)."""
        self._run_shell(f"git worktree remove {worktree_path} --force")
        self._run_shell(f"git branch -D {branch_name}")

    def _get_worktree_commits(self, branch_name: str, base_sha: str) -> list[str]:
        """Get commits on branch since base_sha."""
        _, stdout, _ = self._run_shell(
            f"git log --oneline {base_sha}..{branch_name}"
        )
        return [l.strip() for l in stdout.splitlines() if l.strip()]

    # ─────────────────── Phase A1: Assessment ───────────────────

    async def run_assessment(self, session: EvolutionSession) -> AssessmentReport:
        """Phase A1: Assess current codebase state."""
        await self._log("Phase A1: Assessment starting...", session)
        session.phase = "assessment"

        context = self._build_context()
        day = session.day
        date_str = session.date

        prompt = f"""You are agent-nexus, a self-evolving AI orchestration system. Today is Day {day} ({date_str}).

{context}

=== YOUR TASK: ASSESSMENT ===

You are the ASSESSMENT agent. Your job: understand the current state of the codebase.
You do NOT write task files. You produce a single structured assessment document.

Steps:

1. **Read the source code** — scan src/ directory structure. Note module counts, key entry points.
   Key modules: src/nanobot/mission/, src/nanobot/cron/, src/nanobot/agent/, src/runtime/

2. **Read recent history** — run `git log --oneline -10` to see recent commits.
   Read JOURNAL.md (last 20 lines) if it exists.
   Read memory/active_learnings.md for context from past sessions.

3. **Run the test suite** — run `cd {self._working_dir} && python -m pytest tests/ -x -q --tb=short 2>&1 | head -50`
   Note which tests pass/fail, total count.

4. **Count codebase size** — run `find src/ -name "*.py" | xargs wc -l 2>/dev/null | tail -1`

5. **Identify capability gaps** — what features are partially implemented or missing?
   Check: error handling completeness, test coverage, API stability, documentation quality.

6. **Check for known issues** — look for TODO/FIXME/HACK comments in src/:
   `grep -r "TODO\\|FIXME\\|HACK" src/ --include="*.py" -l | head -10`

Write your assessment to session_plan/assessment.md with this format:

# Assessment — Day {day}

## Build/Test Status
[pass/fail, test count, any errors]

## Recent Changes (last 3 commits)
[from git log]

## Codebase Size
[total lines, module count]

## Self-Test Results
[what tests pass/fail, any errors discovered]

## Capability Gaps
[what's missing or needs improvement]

## Known Issues
[TODO/FIXME items found, any obvious bugs]

## Recommended Focus
[1-3 specific improvements most worth doing today]

Keep assessment to ~2 pages. Be specific and factual.

After writing, run:
mkdir -p session_plan && run your assessment then save to session_plan/assessment.md

Then STOP. Do not write task files yet.
"""

        result = await self._executor.execute(
            prompt=prompt,
            tools="Read,Bash,Grep,Glob,Write",
            timeout=self.config.codebuddy_timeout,
            working_dir=str(self._working_dir),
        )

        report = AssessmentReport(generated_at_ms=_now_ms())

        if result.success:
            report.raw_text = result.output
            # Try to read the actual assessment file
            assessment_file = self._working_dir / "session_plan" / "assessment.md"
            if assessment_file.exists():
                report.raw_text = assessment_file.read_text(encoding="utf-8")
                await self._log(f"Assessment written ({len(report.raw_text)} chars)", session)
            else:
                # Use the output directly
                report.raw_text = result.output
                await self._log("Assessment completed (from output)", session)
        else:
            report.raw_text = f"Assessment failed: {result.error}"
            await self._log(f"Assessment failed: {result.error}", session)

        session.assessment = report
        return report

    # ─────────────────── Phase A2: Planning ───────────────────

    async def run_planning(self, session: EvolutionSession) -> list[EvolutionTask]:
        """Phase A2: Create a task plan from the assessment."""
        await self._log("Phase A2: Planning starting...", session)
        session.phase = "planning"

        context = self._build_context()
        day = session.day
        assessment_text = session.assessment.raw_text if session.assessment else "No assessment available."

        prompt = f"""You are agent-nexus, a self-evolving AI orchestration system. Today is Day {day}.

{context}

=== ASSESSMENT (from Phase A1) ===

{assessment_text}

=== WRITE SESSION PLAN ===

Based on the assessment above, create task files in session_plan/.

Priority:
0. Fix failing tests (if any — highest priority)
1. Fix bugs or crashes discovered in assessment
2. Improve test coverage for undertested modules
3. Add missing features or capabilities identified in gaps
4. Refactor for better code quality
5. Improve documentation or error messages

TASK SIZING RULES:
- Each task MUST touch at most 3 source files
- Each task must be completable in 20 minutes
- If a task was tried before and failed, make it SMALLER
- Prefer tasks verifiable with: python -m pytest tests/ -x -q

PARALLEL EXECUTION RULES (CRITICAL):
- Tasks run in PARALLEL in isolated git worktrees — each task is independent
- NO two tasks may modify the same file. If multiple tasks need the same file, merge them into one task or pick the most important
- Each task's "Files:" list must be UNIQUE across all tasks in this session
- Before finalizing, review all task Files: fields and resolve any overlaps

For EACH task, create a file: session_plan/task_01.md, session_plan/task_02.md, etc.
Maximum {self.config.max_tasks_per_session} tasks.

Each task file format:
```
Title: [short task title]
Files: [comma-separated list of files to modify — must not overlap with other tasks]
Issue: none

[Detailed description of what to change and why.
Include specific functions/classes to modify.
Include how to verify the change with a test.]
```

Run: mkdir -p session_plan && rm -f session_plan/task_*.md

After writing all task files, commit:
git add session_plan/ && git commit -m "Day {day}: session plan"

Then STOP. Do not implement anything. Your job is planning only.
"""

        result = await self._executor.execute(
            prompt=prompt,
            tools="Read,Write,Bash,Grep,Glob",
            timeout=self.config.codebuddy_timeout,
            working_dir=str(self._working_dir),
        )

        tasks = []
        session_plan_dir = self._working_dir / "session_plan"

        if session_plan_dir.exists():
            for task_file in sorted(session_plan_dir.glob("task_*.md")):
                task = self._parse_task_file(task_file)
                tasks.append(task)
                await self._log(f"Task {task.id}: {task.title}", session)

        if not tasks:
            # Fallback task
            await self._log("No tasks produced — using fallback", session)
            fallback = EvolutionTask(
                id="t-001",
                title="Self-improvement",
                files=["src/"],
                description="Read your source code, identify the most impactful improvement, implement it with tests, and commit.",
            )
            tasks.append(fallback)

        session.tasks = tasks
        session.metrics.tasks_planned = len(tasks)
        await self._log(f"Planning complete: {len(tasks)} task(s)", session)
        return tasks

    def _parse_task_file(self, path: Path) -> EvolutionTask:
        """Parse a task_NN.md file into an EvolutionTask."""
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()

        title = ""
        files: list[str] = []
        issue = "none"
        desc_lines: list[str] = []
        in_desc = False

        for line in lines:
            if line.startswith("Title:"):
                title = line[6:].strip()
            elif line.startswith("Files:"):
                files = [f.strip() for f in line[6:].split(",") if f.strip()]
            elif line.startswith("Issue:"):
                issue = line[6:].strip()
            elif title and not in_desc and line.strip() == "":
                in_desc = True
            elif in_desc:
                desc_lines.append(line)

        # Derive ID from filename (task_01.md → t-001)
        m = re.search(r"task_(\d+)", path.stem)
        num = int(m.group(1)) if m else 1
        task_id = f"t-{num:03d}"

        return EvolutionTask(
            id=task_id,
            title=title or path.stem,
            files=files,
            issue=issue,
            description="\n".join(desc_lines).strip(),
        )

    # ─────────────────── Phase B: Implementation ───────────────────

    async def run_implementation(self, session: EvolutionSession) -> None:
        """Phase B: Execute tasks, either in parallel worktrees or serially."""
        if self.config.use_worktree and self.config.parallel_tasks:
            await self._run_implementation_parallel(session)
        else:
            await self._run_implementation_serial(session)

    async def _run_implementation_parallel(self, session: EvolutionSession) -> None:
        """Run tasks in parallel, each in its own git worktree."""
        await self._log("Phase B: Parallel worktree implementation starting...", session)
        session.phase = "implementation"

        tasks = session.tasks
        if not tasks:
            await self._log("No tasks to implement", session)
            return

        # Cleanup any stale worktrees from previous crashed sessions
        self._cleanup_stale_worktrees()

        context = self._build_context()
        day = session.day
        base_sha = self._get_current_sha()
        max_tasks = min(len(tasks), self.config.max_tasks_per_session)
        active_tasks = tasks[:max_tasks]

        await self._log(f"  Spawning {len(active_tasks)} worktrees in parallel...", session)

        # Build worktree info for each task
        worktree_infos = []
        for i, task in enumerate(active_tasks):
            branch_name = f"evolve/{session.id}-{task.id}"
            worktree_path = self._worktree_base() / f"session-{session.id}-{task.id}"
            worktree_infos.append((task, branch_name, worktree_path))

        # Run all tasks in parallel
        results: list[WorktreeTaskResult] = await asyncio.gather(
            *[
                self._run_task_in_worktree(task, session, context, day, base_sha, branch, wt_path)
                for task, branch, wt_path in worktree_infos
            ]
        )

        # Serial merge phase
        await self._merge_worktree_results(results, session, day)

        # Update metrics
        for r in results:
            if r.merge_status == "merged":
                session.metrics.tasks_completed += 1
                session.metrics.files_changed += len(r.files_changed)
                r.task.status = "completed"
            elif r.merge_status in ("conflict", "failed"):
                session.metrics.tasks_failed += 1
                r.task.status = "failed"
                r.task.error = r.error or f"Merge status: {r.merge_status}"
            else:
                session.metrics.tasks_failed += 1
                r.task.status = "failed"
                r.task.error = r.error or "Unknown error"

    async def _run_task_in_worktree(
        self,
        task: EvolutionTask,
        session: EvolutionSession,
        context: str,
        day: int,
        base_sha: str,
        branch_name: str,
        worktree_path: Path,
    ) -> WorktreeTaskResult:
        """Execute a single task in an isolated git worktree."""
        result = WorktreeTaskResult(
            task=task,
            branch_name=branch_name,
            worktree_path=str(worktree_path),
        )

        # Create the worktree
        if not self._create_worktree(branch_name, worktree_path):
            result.error = f"Failed to create worktree {worktree_path}"
            return result

        task.status = "running"
        await self._log(f"  [WT] {task.id}: {task.title}", session)

        # The venv lives in the main working dir — use absolute path for pytest
        venv_python = self._working_dir / ".venv" / "bin" / "python"
        pytest_cmd = (
            f"{venv_python} -m pytest tests/ -x -q --tb=short 2>&1 | head -30"
            if venv_python.exists()
            else "python -m pytest tests/ -x -q --tb=short 2>&1 | head -30"
        )

        prompt = f"""You are agent-nexus, a self-evolving AI orchestration system. Day {day}.

{context}

Your ONLY job: implement this single task and commit.

Title: {task.title}
Files: {', '.join(task.files) if task.files else 'src/'}

{task.description}

IMPORTANT — you are working in an ISOLATED GIT WORKTREE:
- This is a separate directory from the main repo, on branch: {branch_name}
- The .venv is shared with the main repo at: {self._working_dir}/.venv
- Run tests with: {pytest_cmd}
- The main src/ code is in this directory — edit it normally

Follow these rules:
- Write or update a test first if possible
- Make focused, surgical changes
- After each change run: {pytest_cmd}
- If tests fail, read the error and fix it. Try up to 3 times.
- Only if stuck after 3 attempts: revert with git checkout -- .
- After all tests pass, commit:
  git add -A && git commit -m "Day {day}: {task.title}"
- Do NOT modify: {', '.join(self.config.protected_files)}
- Do NOT work on anything else.
"""

        exec_result = await self._executor.execute(
            prompt=prompt,
            tools="Read,Write,Edit,MultiEdit,Bash,Grep,Glob",
            timeout=self.config.codebuddy_timeout,
            working_dir=str(worktree_path),
        )

        if not exec_result.success:
            result.error = exec_result.error or "CodeBuddy execution failed"
            await self._log(f"  [WT] {task.id} FAILED: {result.error}", session)
            return result

        # Check if any commits were made
        commits = self._get_worktree_commits(branch_name, base_sha)
        if not commits:
            result.error = "No commits produced"
            await self._log(f"  [WT] {task.id}: no commits — skipping", session)
            return result

        # Check protected files
        _, stdout, _ = self._run_shell(
            f"git diff --name-only {base_sha}..{branch_name} -- "
            + " ".join(self.config.protected_files)
        )
        if stdout.strip():
            result.error = f"Modified protected files: {stdout.strip()}"
            await self._log(f"  [WT] {task.id} BLOCKED: {result.error}", session)
            return result

        # Get list of changed files
        _, diff_out, _ = self._run_shell(
            f"git diff --name-only {base_sha}..{branch_name}"
        )
        result.files_changed = [f.strip() for f in diff_out.splitlines() if f.strip()]
        result.success = True
        await self._log(
            f"  [WT] {task.id} ✓ ready ({len(commits)} commit(s), {len(result.files_changed)} file(s))",
            session
        )
        return result

    async def _merge_worktree_results(
        self,
        results: list[WorktreeTaskResult],
        session: EvolutionSession,
        day: int,
    ) -> None:
        """Sequentially merge successful worktree results into main branch.

        Conflict resolution strategy (three attempts):
          1. Standard merge — succeeds when no conflicts
          2. Auto-resolve with -X theirs — takes the worktree's version for
             any conflicted hunks; safe when tasks touch different logical areas
          3. codebuddy-assisted resolution — for true semantic conflicts,
             spawn a codebuddy instance to read the conflict markers and fix them
          4. Give up — abort and log for next session
        """
        await self._log("  Merging worktrees into main branch...", session)

        for r in results:
            try:
                if not r.success:
                    r.merge_status = "failed"
                    continue

                merged = await self._try_merge(r, session, day)
                if not merged:
                    r.merge_status = "conflict"
                    await self._log(
                        f"  ✗ Could not merge: {r.task.title} — will retry next session",
                        session,
                    )
            finally:
                # Always clean up worktree regardless of merge outcome
                self._remove_worktree(r.branch_name, Path(r.worktree_path))

    async def _try_merge(
        self,
        r: WorktreeTaskResult,
        session: EvolutionSession,
        day: int,
    ) -> bool:
        """Attempt to merge a worktree branch with escalating conflict resolution.

        Returns True if the merge succeeded (via any strategy).
        """
        commit_msg = f"Day {day}: {r.task.title} [worktree]"

        # ── Attempt 1: Clean merge ────────────────────────────────
        code, _, err = self._run_shell(
            f'git merge --no-ff {r.branch_name} -m "{commit_msg}"',
            timeout=30,
        )
        if code == 0:
            r.merge_status = "merged"
            await self._log(f"  ✓ Merged: {r.task.title}", session)
            return True

        # Merge failed — check if it left conflict state
        self._run_shell("git merge --abort")

        # ── Attempt 2: Auto-resolve with -X theirs ────────────────
        # This is safe when tasks modify different parts of the same file.
        # "-X theirs" picks the incoming branch's version for conflicted hunks.
        await self._log(
            f"  ⚠ Conflict on '{r.task.title}' — trying auto-resolve (-X theirs)...",
            session,
        )
        code2, _, err2 = self._run_shell(
            f'git merge --no-ff -X theirs {r.branch_name} -m "{commit_msg} [auto-resolved]"',
            timeout=30,
        )
        if code2 == 0:
            r.merge_status = "merged"
            await self._log(
                f"  ✓ Merged with auto-resolve: {r.task.title}",
                session,
            )
            return True

        self._run_shell("git merge --abort")

        # ── Attempt 3: codebuddy-assisted conflict resolution ──────
        await self._log(
            f"  ⚠ Auto-resolve failed — asking codebuddy to resolve conflicts...",
            session,
        )
        resolved = await self._codebuddy_resolve_conflict(r, session, day)
        if resolved:
            r.merge_status = "merged"
            await self._log(
                f"  ✓ Merged with codebuddy resolution: {r.task.title}",
                session,
            )
            return True

        r.error = f"All merge strategies failed: {err[:200]}"
        return False

    async def _codebuddy_resolve_conflict(
        self,
        r: WorktreeTaskResult,
        session: EvolutionSession,
        day: int,
    ) -> bool:
        """Use codebuddy to resolve merge conflicts interactively.

        Starts the merge (leaving conflict markers), then asks codebuddy
        to read the conflicted files and produce clean resolutions.
        Returns True if resolution succeeded and commit was made.
        """
        commit_msg = f"Day {day}: {r.task.title} [worktree, conflict-resolved]"

        # Start merge without committing — will leave conflict markers in files
        code, _, _ = self._run_shell(
            f"git merge --no-ff --no-commit {r.branch_name}",
            timeout=30,
        )

        # Find conflicted files
        _, conflict_out, _ = self._run_shell("git diff --name-only --diff-filter=U")
        conflicted = [f.strip() for f in conflict_out.splitlines() if f.strip()]

        if not conflicted:
            # No actual conflicts — just commit what we have
            code2, _, _ = self._run_shell(f'git commit -m "{commit_msg}"')
            if code2 == 0:
                return True
            self._run_shell("git merge --abort")
            return False

        await self._log(
            f"    Conflicts in: {', '.join(conflicted)} — asking codebuddy...",
            session,
        )

        prompt = f"""You are agent-nexus, resolving a git merge conflict.

A worktree branch '{r.branch_name}' was implementing:
  Task: {r.task.title}
  Files changed: {', '.join(r.files_changed)}

The merge has conflict markers (<<<<<<, =======, >>>>>>>) in:
  {chr(10).join(f'  - {f}' for f in conflicted)}

Your job:
1. Read each conflicted file
2. Understand both versions (HEAD = current main, incoming = worktree improvement)
3. Produce a clean merged version that incorporates the worktree's improvement
   while preserving any changes in HEAD
4. After resolving ALL conflict markers:
   git add {' '.join(conflicted)}
   git commit -m "{commit_msg}"

Rules:
- Remove ALL conflict markers (<<<<<<, =======, >>>>>>>) — none should remain
- Prefer the incoming (worktree) changes for the task's intended improvement
- Preserve unrelated HEAD changes
- Run: python -m pytest tests/ -x -q --tb=short 2>&1 | head -20 to verify
- Only commit if tests pass
- If you cannot resolve cleanly, run: git merge --abort
"""

        result = await self._executor.execute(
            prompt=prompt,
            tools="Read,Write,Edit,Bash,Grep",
            timeout=self.config.codebuddy_timeout,
            working_dir=str(self._working_dir),
        )

        # Check if merge was completed (a new commit was made)
        _, log_out, _ = self._run_shell(
            f"git log --oneline -1 --format='%s'"
        )
        if commit_msg[:30] in log_out or "conflict-resolved" in log_out:
            return True

        # Check merge state — if still in conflict, abort
        _, status_out, _ = self._run_shell("git status --short")
        if "UU " in status_out or "AA " in status_out:
            self._run_shell("git merge --abort")
            return False

        # If no conflict markers remain, try to commit
        _, grep_out, _ = self._run_shell(
            'grep -r "<<<<<<" ' + " ".join(conflicted) + ' 2>/dev/null || true'
        )
        if not grep_out.strip():
            code3, _, _ = self._run_shell(f'git commit -m "{commit_msg}"')
            return code3 == 0

        self._run_shell("git merge --abort")
        return False

    async def _run_implementation_serial(self, session: EvolutionSession) -> None:
        """Fallback: run tasks serially in the main working directory."""
        await self._log("Phase B: Serial implementation starting...", session)
        session.phase = "implementation"

        tasks = session.tasks
        if not tasks:
            await self._log("No tasks to implement", session)
            return

        context = self._build_context()
        day = session.day
        max_tasks = min(len(tasks), self.config.max_tasks_per_session)

        for i, task in enumerate(tasks[:max_tasks]):
            await self._log(f"  → Task {i+1}/{max_tasks}: {task.title}", session)
            task.status = "running"

            pre_sha = self._get_current_sha()

            prompt = f"""You are agent-nexus, a self-evolving AI orchestration system. Day {day}.

{context}

Your ONLY job: implement this single task and commit.

Title: {task.title}
Files: {', '.join(task.files) if task.files else 'src/'}

{task.description}

Follow these rules:
- Write or update a test first if possible
- Make focused, surgical changes (edit_file preferred over rewriting entire files)
- After each change run: python -m pytest tests/ -x -q --tb=short 2>&1 | head -30
- If tests fail, read the error and fix it. Try up to 3 times.
- Only if stuck after 3 attempts: revert with git checkout -- . (keeps previous commits)
- After all tests pass, commit:
  git add -A && git commit -m "Day {day}: {task.title}"
- Do NOT modify: {', '.join(self.config.protected_files)}
- Do NOT work on anything else. This is your only task.
"""

            result = await self._executor.execute(
                prompt=prompt,
                tools="Read,Write,Edit,MultiEdit,Bash,Grep,Glob",
                timeout=self.config.codebuddy_timeout,
                working_dir=str(self._working_dir),
            )

            # Verify: protected files not changed
            changed_files = self._get_git_diff_files(pre_sha)
            is_valid, violations = self._identity.validate_changes(changed_files)

            if not is_valid:
                await self._log(f"    BLOCKED: modified protected files {violations}", session)
                self._run_shell(f"git reset --hard {pre_sha}")
                task.status = "failed"
                task.error = f"Modified protected files: {violations}"
                session.metrics.tasks_failed += 1
                continue

            # Verify: tests pass
            code, stdout, stderr = self._run_shell(
                "python -m pytest tests/ -x -q --tb=short 2>&1 | head -50",
                timeout=120,
            )

            if code != 0 and not result.success:
                await self._log(f"    FAILED: {result.error or 'tests failed'}", session)
                self._run_shell(f"git reset --hard {pre_sha}")
                task.status = "failed"
                task.error = result.error or "Tests failed after implementation"
                session.metrics.tasks_failed += 1
            else:
                task.status = "completed"
                task.output = result.output[:2000] if result.output else ""
                session.metrics.tasks_completed += 1
                session.metrics.files_changed += len(changed_files)
                await self._log(f"    ✓ Completed: {task.title}", session)

    # ─────────────────── Phase C: Reflection ───────────────────

    async def run_reflection(self, session: EvolutionSession) -> None:
        """Phase C: Update memory and write journal entry."""
        await self._log("Phase C: Reflection starting...", session)
        session.phase = "reflection"

        day = session.day
        date_str = session.date
        completed = [t for t in session.tasks if t.status == "completed"]
        failed = [t for t in session.tasks if t.status == "failed"]

        # Write journal entry
        journal_path = self._working_dir / self.config.journal_path
        entry_lines = [
            f"\n## Session {day} — {date_str}\n",
            f"**Duration:** {session.duration_seconds:.0f}s\n",
            f"**Tasks:** {len(completed)} completed, {len(failed)} failed\n",
        ]

        if completed:
            entry_lines.append("\n### Completed\n")
            for t in completed:
                entry_lines.append(f"- {t.title}")

        if failed:
            entry_lines.append("\n### Failed\n")
            for t in failed:
                entry_lines.append(f"- {t.title}: {t.error or 'unknown reason'}")

        if session.assessment and session.assessment.raw_text:
            gaps_match = re.search(
                r"## Capability Gaps\n(.*?)(?=\n##|\Z)",
                session.assessment.raw_text, re.DOTALL
            )
            if gaps_match:
                entry_lines.append(f"\n### Gaps Identified\n{gaps_match.group(1).strip()}")

        entry_lines.append("\n---\n")
        entry_text = "\n".join(entry_lines)

        try:
            journal_path.parent.mkdir(parents=True, exist_ok=True)
            with open(journal_path, "a", encoding="utf-8") as f:
                f.write(entry_text)
            await self._log("Journal updated", session)
        except Exception as e:
            await self._log(f"Failed to update journal: {e}", session)

        # Extract and save lessons
        if completed:
            lesson = Lesson(
                day=day,
                source="evolution",
                title=f"Day {day}: {len(completed)} improvements completed",
                context=f"Completed: {', '.join(t.title for t in completed[:3])}",
                takeaway=f"Session {day} was {'productive' if len(completed) > len(failed) else 'mixed'}. "
                         f"{len(completed)}/{len(completed) + len(failed)} tasks succeeded.",
            )
            self._memory.append_learning(lesson)

        # Commit journal + memory
        self._run_shell(
            f'git add JOURNAL.md memory/ && git commit -m "Day {day}: session wrap-up"'
        )
        await self._log("Reflection complete", session)

    # ─────────────────── Full Cycle ───────────────────

    async def run_full_cycle(self) -> EvolutionSession:
        """Run a complete evolution cycle: Assessment → Planning → Implementation → Reflection."""
        day = self._get_session_day()
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        session_id = str(uuid.uuid4())[:8]

        session = EvolutionSession(
            id=session_id,
            day=day,
            date=date_str,
            status="running",
            started_at_ms=_now_ms(),
        )

        await self._log(f"=== Evolution Session {day} starting ({session_id}) ===", session)

        try:
            # Ensure session_plan directory exists
            (self._working_dir / "session_plan").mkdir(parents=True, exist_ok=True)

            # Clean up any stale worktrees from previous crashed sessions
            if self.config.use_worktree:
                self._cleanup_stale_worktrees()

            # Phase A1: Assessment
            await self.run_assessment(session)

            # Phase A2: Planning
            await self.run_planning(session)

            # Phase B: Implementation
            await self.run_implementation(session)

            # Phase C: Reflection
            session.completed_at_ms = _now_ms()
            await self.run_reflection(session)

            session.status = "completed"
            await self._log(
                f"=== Session {day} complete: {session.metrics.tasks_completed}/{session.metrics.tasks_planned} tasks ===",
                session
            )

        except Exception as e:
            session.status = "failed"
            session.error = str(e)
            session.completed_at_ms = _now_ms()
            await self._log(f"Session failed: {e}", session)
            logger.exception("Evolution session {} failed", session_id)

        return session

    async def run_memory_synthesis(self) -> None:
        """Synthesize archive memories into active context. Run daily."""
        logger.info("Evolution: running memory synthesis")
        self._memory.synthesize()
        logger.info("Evolution: memory synthesis complete")

"""Core runtime orchestration for the self-evolution system."""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger

from src.nanobot.evolve.codebuddy_executor import CodeBuddyExecutor
from src.nanobot.evolve.identity import IdentityManager
from src.nanobot.evolve.implementation import (
    WorktreeTaskResult,
    cleanup_stale_worktrees as implementation_cleanup_stale_worktrees,
    codebuddy_resolve_conflict as implementation_codebuddy_resolve_conflict,
    create_worktree as implementation_create_worktree,
    get_current_sha as implementation_get_current_sha,
    get_git_diff_files as implementation_get_git_diff_files,
    get_worktree_commits as implementation_get_worktree_commits,
    get_worktree_manager as implementation_get_worktree_manager,
    merge_worktree_results as implementation_merge_worktree_results,
    remove_worktree as implementation_remove_worktree,
    run_implementation as implementation_run_implementation,
    run_implementation_isolated as implementation_run_implementation_isolated,
    run_implementation_parallel as implementation_run_implementation_parallel,
    run_implementation_serial as implementation_run_implementation_serial,
    run_shell as implementation_run_shell,
    run_task_in_worktree as implementation_run_task_in_worktree,
    try_merge as implementation_try_merge,
    worktree_base as implementation_worktree_base,
)
from src.nanobot.evolve.memory import MemoryManager
from src.nanobot.evolve.models import (
    AssessmentReport,
    EvolutionConfig,
    EvolutionSession,
    EvolutionTask,
    Lesson,
)
from src.nanobot.evolve.prompts import build_assessment_prompt, build_planning_prompt


def _now_ms() -> int:
    return int(time.time() * 1000)


class EvolutionEngine:
    """Orchestrates the full evolution cycle for agent-nexus."""

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
        self._wt_manager = None  # Lazy-initialized WorktreeManager

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
        active_learnings = self._memory.load_active_learnings()
        social_learnings = self._memory.load_active_social_learnings()
        return self._identity.build_context(active_learnings, social_learnings)

    def _get_session_number(self) -> int:
        journal_path = self._working_dir / self.config.journal_path
        if not journal_path.exists():
            return 1
        content = journal_path.read_text(encoding="utf-8")
        return content.count("## Session ") + 1

    def _run_shell(self, cmd: str, timeout: int = 30) -> tuple[int, str, str]:
        return implementation_run_shell(self, cmd, timeout)

    def _get_git_diff_files(self, base_sha: str) -> list[str]:
        return implementation_get_git_diff_files(self, base_sha)

    def _get_current_sha(self) -> str:
        return implementation_get_current_sha(self)

    def _worktree_base(self) -> Path:
        return implementation_worktree_base(self)

    def _cleanup_stale_worktrees(self) -> None:
        implementation_cleanup_stale_worktrees(self)

    def _create_worktree(self, branch_name: str, worktree_path: Path) -> bool:
        return implementation_create_worktree(self, branch_name, worktree_path)

    def _remove_worktree(self, branch_name: str, worktree_path: Path) -> None:
        implementation_remove_worktree(self, branch_name, worktree_path)

    def _get_worktree_commits(self, branch_name: str, base_sha: str) -> list[str]:
        return implementation_get_worktree_commits(self, branch_name, base_sha)

    async def run_assessment(self, session: EvolutionSession) -> AssessmentReport:
        await self._log("Phase A1: Assessment starting...", session)
        session.phase = "assessment"

        prompt = build_assessment_prompt(
            self.config,
            session_number=session.day,
            date_str=session.date,
            context=self._build_context(),
            working_dir=str(self._working_dir),
        )
        result = await self._executor.execute(
            prompt=prompt,
            tools="Read,Bash,Grep,Glob,Write",
            timeout=self.config.codebuddy_timeout,
            working_dir=str(self._working_dir),
        )

        report = AssessmentReport(generated_at_ms=_now_ms())
        if result.success:
            assessment_file = self._working_dir / "session_plan" / "assessment.md"
            if assessment_file.exists():
                report.raw_text = assessment_file.read_text(encoding="utf-8")
                await self._log(f"Assessment written ({len(report.raw_text)} chars)", session)
            else:
                report.raw_text = result.output
                await self._log("Assessment completed (from output)", session)
        else:
            report.raw_text = f"Assessment failed: {result.error}"
            await self._log(f"Assessment failed: {result.error}", session)

        session.assessment = report
        return report

    async def run_planning(self, session: EvolutionSession) -> list[EvolutionTask]:
        await self._log("Phase A2: Planning starting...", session)
        session.phase = "planning"

        prompt = build_planning_prompt(
            self.config,
            session_number=session.day,
            context=self._build_context(),
            assessment_text=session.assessment.raw_text if session.assessment else "No assessment available.",
        )
        await self._executor.execute(
            prompt=prompt,
            tools="Read,Write,Bash,Grep,Glob",
            timeout=self.config.codebuddy_timeout,
            working_dir=str(self._working_dir),
        )

        tasks: list[EvolutionTask] = []
        session_plan_dir = self._working_dir / "session_plan"
        if session_plan_dir.exists():
            for task_file in sorted(session_plan_dir.glob("task_*.md")):
                task = self._parse_task_file(task_file)
                tasks.append(task)
                await self._log(f"Task {task.id}: {task.title}", session)

        if not tasks:
            await self._log("No tasks produced — using fallback", session)
            tasks.append(
                EvolutionTask(
                    id="t-001",
                    title="Self-improvement",
                    files=["src/"],
                    description=(
                        "Read your source code, identify the most impactful improvement, "
                        "implement it with tests, and commit."
                    ),
                )
            )

        session.tasks = tasks
        session.metrics.tasks_planned = len(tasks)
        await self._log(f"Planning complete: {len(tasks)} task(s)", session)
        return tasks

    def _parse_task_file(self, path: Path) -> EvolutionTask:
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
                files = [part.strip() for part in line[6:].split(",") if part.strip()]
            elif line.startswith("Issue:"):
                issue = line[6:].strip()
            elif title and not in_desc and line.strip() == "":
                in_desc = True
            elif in_desc:
                desc_lines.append(line)

        match = re.search(r"task_(\d+)", path.stem)
        num = int(match.group(1)) if match else 1
        return EvolutionTask(
            id=f"t-{num:03d}",
            title=title or path.stem,
            files=files,
            issue=issue,
            description="\n".join(desc_lines).strip(),
        )

    async def run_implementation(self, session: EvolutionSession) -> None:
        await implementation_run_implementation(self, session)

    async def _run_implementation_parallel(self, session: EvolutionSession) -> None:
        await implementation_run_implementation_parallel(self, session)

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
        return await implementation_run_task_in_worktree(
            self,
            task,
            session,
            context,
            day,
            base_sha,
            branch_name,
            worktree_path,
        )

    async def _merge_worktree_results(
        self,
        results: list[WorktreeTaskResult],
        session: EvolutionSession,
        day: int,
    ) -> None:
        await implementation_merge_worktree_results(self, results, session, day)

    async def _try_merge(
        self,
        result: WorktreeTaskResult,
        session: EvolutionSession,
        day: int,
    ) -> bool:
        return await implementation_try_merge(self, result, session, day)

    async def _codebuddy_resolve_conflict(
        self,
        result: WorktreeTaskResult,
        session: EvolutionSession,
        day: int,
    ) -> bool:
        return await implementation_codebuddy_resolve_conflict(self, result, session, day)

    async def _run_implementation_serial(self, session: EvolutionSession) -> None:
        await implementation_run_implementation_serial(self, session)

    async def run_reflection(self, session: EvolutionSession) -> None:
        await self._log("Phase C: Reflection starting...", session)
        session.phase = "reflection"

        completed = [task for task in session.tasks if task.status == "completed"]
        failed = [task for task in session.tasks if task.status == "failed"]
        journal_path = self._working_dir / self.config.journal_path

        entry_lines = [
            f"\n## Session {session.day} — {session.date}\n",
            f"**Duration:** {session.duration_seconds:.0f}s\n",
            f"**Tasks:** {len(completed)} completed, {len(failed)} failed\n",
        ]

        if completed:
            entry_lines.append("\n### Completed\n")
            entry_lines.extend(f"- {task.title}" for task in completed)

        if failed:
            entry_lines.append("\n### Failed\n")
            entry_lines.extend(f"- {task.title}: {task.error or 'unknown reason'}" for task in failed)

        if session.assessment and session.assessment.raw_text:
            gaps_match = re.search(r"## Capability Gaps\n(.*?)(?=\n##|\Z)", session.assessment.raw_text, re.DOTALL)
            if gaps_match:
                entry_lines.append(f"\n### Gaps Identified\n{gaps_match.group(1).strip()}")

        entry_lines.append("\n---\n")
        entry_text = "\n".join(entry_lines)

        try:
            journal_path.parent.mkdir(parents=True, exist_ok=True)
            with open(journal_path, "a", encoding="utf-8") as handle:
                handle.write(entry_text)
            await self._log("Journal updated", session)
        except Exception as exc:
            await self._log(f"Failed to update journal: {exc}", session)

        if completed:
            self._memory.append_learning(
                Lesson(
                    day=session.day,
                    source="evolution",
                    title=f"Session {session.day}: {len(completed)} improvements completed",
                    context=f"Completed: {', '.join(task.title for task in completed[:3])}",
                    takeaway=(
                        f"Session {session.day} was {'productive' if len(completed) > len(failed) else 'mixed'}. "
                        f"{len(completed)}/{len(completed) + len(failed)} tasks succeeded."
                    ),
                )
            )

        journal_target = self.config.journal_path
        memory_target = self.config.memory_path
        self._run_shell(
            f'git add "{journal_target}" "{memory_target}" && git commit -m "Session {session.day}: wrap-up"'
        )
        await self._log("Reflection complete", session)

    async def run_full_cycle(self) -> EvolutionSession:
        session_number = self._get_session_number()
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        session = EvolutionSession(
            id=str(uuid.uuid4())[:8],
            day=session_number,
            date=date_str,
            status="running",
            started_at_ms=_now_ms(),
        )

        await self._log(f"=== Evolution Session {session_number} starting ({session.id}) ===", session)

        try:
            (self._working_dir / "session_plan").mkdir(parents=True, exist_ok=True)
            if self.config.use_worktree:
                self._cleanup_stale_worktrees()

            await self.run_assessment(session)
            await self.run_planning(session)
            await self.run_implementation(session)

            session.completed_at_ms = _now_ms()
            await self.run_reflection(session)

            session.status = "completed"
            await self._log(
                f"=== Session {session_number} complete: {session.metrics.tasks_completed}/{session.metrics.tasks_planned} tasks ===",
                session,
            )
        except Exception as exc:
            session.status = "failed"
            session.error = str(exc)
            session.completed_at_ms = _now_ms()
            await self._log(f"Session failed: {exc}", session)
            logger.exception("Evolution session {} failed", session.id)

        return session

    async def run_memory_synthesis(self) -> None:
        logger.info("Evolution: running memory synthesis")
        self._memory.synthesize()
        logger.info("Evolution: memory synthesis complete")

    # ------------------------------------------------------------------
    # Session Resume & Isolated Worktree support
    # ------------------------------------------------------------------

    def get_worktree_manager(self):
        """Get or lazily initialize the WorktreeManager for this engine."""
        return implementation_get_worktree_manager(self)

    async def resume_session(self, session_key: str) -> EvolutionSession | None:
        """Resume a previously running session by looking up its worktree.

        If the session has an active worktree bound via WorktreeManager,
        switch the working directory to it and return a reconstructed
        EvolutionSession. Returns None if the session key is not found.
        """
        from src.runtime.commands.slash.worktree import (
            WorktreeNotFoundError,
            IsolationLevel,
        )

        manager = self.get_worktree_manager()
        try:
            entry = manager.resume_session(session_key)
        except WorktreeNotFoundError:
            logger.warning("Evolution: no worktree for session_key={}", session_key)
            return None

        # Switch working dir to the resumed worktree
        if entry.path.exists():
            self._working_dir = entry.path
            logger.info("Evolution: resumed session to worktree at {}", entry.path)

        session_number = self._get_session_number()
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        session = EvolutionSession(
            id=session_key,
            day=session_number,
            date=date_str,
            status="running",
            started_at_ms=_now_ms(),
        )
        return session

    async def run_isolated_cycle(self) -> EvolutionSession:
        """Run a full evolution cycle with AGENT-level isolated worktrees.

        Uses WorktreeManager for lifecycle management instead of raw git
        commands, providing session resume and garbage collection.
        """
        session_number = self._get_session_number()
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        session = EvolutionSession(
            id=str(uuid.uuid4())[:8],
            day=session_number,
            date=date_str,
            status="running",
            started_at_ms=_now_ms(),
        )

        await self._log(f"=== Isolated Evolution Session {session_number} starting ({session.id}) ===", session)

        try:
            (self._working_dir / "session_plan").mkdir(parents=True, exist_ok=True)

            await self.run_assessment(session)
            await self.run_planning(session)
            await implementation_run_implementation_isolated(self, session)

            session.completed_at_ms = _now_ms()
            await self.run_reflection(session)

            session.status = "completed"
            await self._log(
                f"=== Isolated Session {session_number} complete: {session.metrics.tasks_completed}/{session.metrics.tasks_planned} tasks ===",
                session,
            )
        except Exception as exc:
            session.status = "failed"
            session.error = str(exc)
            session.completed_at_ms = _now_ms()
            await self._log(f"Isolated session failed: {exc}", session)
            logger.exception("Isolated evolution session {} failed", session.id)

        return session

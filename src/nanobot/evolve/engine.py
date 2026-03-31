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
    # Fallback: inline defaults are used in the engine methods
    return ""


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

For EACH task, create a file: session_plan/task_01.md, session_plan/task_02.md, etc.
Maximum {self.config.max_tasks_per_session} tasks.

Each task file format:
```
Title: [short task title]
Files: [comma-separated list of files to modify]
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
        """Phase B: Execute each task with CodeBuddy."""
        await self._log("Phase B: Implementation starting...", session)
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
                # Revert
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
            test_output = stdout + stderr

            if code != 0 and not result.success:
                await self._log(f"    FAILED: {result.error or 'tests failed'}", session)
                # Revert to pre-task state
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

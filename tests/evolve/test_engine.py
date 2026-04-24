"""Tests for the evolution engine."""

import asyncio
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.nanobot.evolve.models import EvolutionConfig, EvolutionSession, EvolutionTask
from src.nanobot.evolve.engine import EvolutionEngine
from src.nanobot.evolve.codebuddy_executor import ExecutionResult


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def config(tmp_dir):
    return EvolutionConfig(
        enabled=True,
        working_dir=str(tmp_dir),
        memory_path=str(tmp_dir / "memory"),
        journal_path="JOURNAL.md",
        identity_file="IDENTITY.md",
        personality_file="PERSONALITY.md",
        codebuddy_path="codebuddy",
        codebuddy_timeout=30,
        max_tasks_per_session=2,
    )


@pytest.fixture
def engine(config):
    return EvolutionEngine(config)


@pytest.fixture
def mock_success_result():
    return ExecutionResult(success=True, output="Done", exit_code=0)


@pytest.fixture
def mock_fail_result():
    return ExecutionResult(success=False, error="Command failed", exit_code=1)


def _make_session(config) -> EvolutionSession:
    return EvolutionSession(id="test-001", day=1, date="2026-01-01")


class TestEvolutionEngine:
    def test_get_session_number_no_journal(self, engine, tmp_dir):
        """Should return session 1 when no journal exists."""
        session_number = engine._get_session_number()
        assert session_number == 1

    def test_get_session_number_with_journal(self, engine, tmp_dir):
        """Should count sessions from journal entries."""
        journal = tmp_dir / "JOURNAL.md"
        journal.write_text("## Session 1\n\n## Session 2\n\n## Session 3\n", encoding="utf-8")
        session_number = engine._get_session_number()
        assert session_number == 4

    def test_parse_task_file(self, engine, tmp_dir):
        """Should parse task file into EvolutionTask."""
        task_file = tmp_dir / "task_01.md"
        task_file.write_text(
            "Title: Fix null pointer in executor\n"
            "Files: src/nexus/mission/executor.py, tests/test_executor.py\n"
            "Issue: #42\n\n"
            "Description of what to do.\n"
            "More details here.",
            encoding="utf-8",
        )
        task = engine._parse_task_file(task_file)
        assert task.id == "t-001"
        assert task.title == "Fix null pointer in executor"
        assert "src/nexus/mission/executor.py" in task.files
        assert task.issue == "#42"
        assert "Description" in task.description

    def test_parse_task_file_minimal(self, engine, tmp_dir):
        """Should handle minimal task file."""
        task_file = tmp_dir / "task_03.md"
        task_file.write_text("Title: Simple fix\nFiles: src/\nIssue: none\n", encoding="utf-8")
        task = engine._parse_task_file(task_file)
        assert task.id == "t-003"
        assert task.title == "Simple fix"

    @pytest.mark.asyncio
    async def test_run_assessment_success(self, engine, tmp_dir):
        """Assessment phase should produce a report."""
        session_plan = tmp_dir / "session_plan"
        session_plan.mkdir()
        (session_plan / "assessment.md").write_text(
            "# Assessment — Session 1\n\n## Build/Test Status\npass, 50 tests\n",
            encoding="utf-8",
        )

        session = _make_session(engine.config)
        with patch.object(engine._executor, "execute", return_value=ExecutionResult(success=True, output="")):
            report = await engine.run_assessment(session)

        assert report is not None
        assert "Assessment" in report.raw_text

    @pytest.mark.asyncio
    async def test_run_planning_creates_tasks(self, engine, tmp_dir):
        """Planning phase should parse task files into EvolutionTask list."""
        session_plan = tmp_dir / "session_plan"
        session_plan.mkdir()
        (session_plan / "task_01.md").write_text(
            "Title: Add test for mission planner\nFiles: tests/test_planner.py\nIssue: none\n\nDescription.",
            encoding="utf-8",
        )
        (session_plan / "task_02.md").write_text(
            "Title: Fix timeout bug\nFiles: src/nexus/mission/executor.py\nIssue: none\n\nFix it.",
            encoding="utf-8",
        )

        session = _make_session(engine.config)
        session.assessment = MagicMock(raw_text="# Assessment\n## Gaps\nSome gaps.")

        with patch.object(engine._executor, "execute", return_value=ExecutionResult(success=True)):
            tasks = await engine.run_planning(session)

        assert len(tasks) == 2
        assert tasks[0].title == "Add test for mission planner"
        assert tasks[1].title == "Fix timeout bug"

    @pytest.mark.asyncio
    async def test_run_planning_fallback_no_tasks(self, engine):
        """Should create fallback task if planning produces nothing."""
        session = _make_session(engine.config)
        session.assessment = MagicMock(raw_text="No assessment.")

        with patch.object(engine._executor, "execute", return_value=ExecutionResult(success=True)):
            tasks = await engine.run_planning(session)

        assert len(tasks) == 1
        assert tasks[0].title == "Self-improvement"

    @pytest.mark.asyncio
    async def test_run_reflection_creates_journal(self, engine, tmp_dir):
        """Reflection should append a journal entry."""
        session = _make_session(engine.config)
        session.tasks = [
            EvolutionTask(id="t-001", title="Fix timeout", status="completed"),
        ]
        session.completed_at_ms = 1_000_000
        session.started_at_ms = 900_000

        with patch.object(engine, "_run_shell", return_value=(0, "", "")):
            await engine.run_reflection(session)

        journal = tmp_dir / "JOURNAL.md"
        assert journal.exists()
        content = journal.read_text(encoding="utf-8")
        assert "Session 1" in content
        assert "Fix timeout" in content

    @pytest.mark.asyncio
    async def test_full_cycle_completes(self, engine, tmp_dir):
        """Full cycle should complete without errors when everything succeeds."""
        session_plan = tmp_dir / "session_plan"
        session_plan.mkdir()
        (session_plan / "assessment.md").write_text("# Assessment\n## Gaps\nNone.", encoding="utf-8")
        (session_plan / "task_01.md").write_text(
            "Title: Minor improvement\nFiles: src/\nIssue: none\n\nDo something minor.",
            encoding="utf-8",
        )

        success_result = ExecutionResult(success=True, output="done", exit_code=0)

        with patch.object(engine._executor, "execute", return_value=success_result), \
             patch.object(engine, "_run_shell", return_value=(0, "", "")), \
             patch.object(engine, "_get_current_sha", return_value="abc123"), \
             patch.object(engine, "_get_git_diff_files", return_value=["src/nexus/mission/types.py"]):

            session = await engine.run_full_cycle()

        assert session.status == "completed"
        assert session.day >= 1

"""Tests for the CodeBuddy executor."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.nanobot.evolve.models import EvolutionConfig
from src.nanobot.evolve.codebuddy_executor import CodeBuddyExecutor, ExecutionResult


@pytest.fixture
def config():
    return EvolutionConfig(
        codebuddy_path="codebuddy",
        codebuddy_timeout=30,
        working_dir=".",
    )


@pytest.fixture
def executor(config):
    return CodeBuddyExecutor(config)


class TestExecutionResult:
    def test_defaults(self):
        r = ExecutionResult()
        assert r.success is False
        assert r.output == ""
        assert r.error is None
        assert r.exit_code == -1
        assert r.timed_out is False
        assert r.duration_seconds == 0.0


class TestCodeBuddyExecutor:
    @pytest.mark.asyncio
    async def test_execute_success(self, executor):
        """Should return success result when codebuddy exits 0."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"output text", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await executor.execute("do something")

        assert result.success is True
        assert result.output == "output text"
        assert result.exit_code == 0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_execute_failure(self, executor):
        """Should return failure when codebuddy exits non-zero."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"some error"))
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await executor.execute("do something")

        assert result.success is False
        assert result.exit_code == 1
        assert "some error" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execute_timeout(self, executor):
        """Should return timed_out=True when process exceeds timeout."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await executor.execute("do something", timeout=1)

        assert result.timed_out is True
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_codebuddy_not_found(self, config):
        """Should return error when codebuddy binary not found."""
        config_bad = EvolutionConfig(codebuddy_path="/nonexistent/codebuddy")
        executor = CodeBuddyExecutor(config_bad)

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            result = await executor.execute("do something")

        assert result.success is False
        assert "not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_system_prompt_written_to_file(self, executor):
        """System prompt should be written to a temp file."""
        created_files = []

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"done", b""))
        mock_proc.returncode = 0

        original_mkstemp = __import__("tempfile").NamedTemporaryFile

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await executor.execute("task", system_prompt="My system prompt")

        assert result.success is True
        # Verify --system-prompt-file was passed
        call_args = mock_exec.call_args[0]  # positional args (cmd list)
        assert "--system-prompt-file" in call_args

    @pytest.mark.asyncio
    async def test_tools_passed_to_command(self, executor):
        """Tools list should appear in the command."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"done", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await executor.execute("task", tools="Read,Write")

        call_args = mock_exec.call_args[0]
        assert "--tools" in call_args
        tools_idx = list(call_args).index("--tools")
        assert call_args[tools_idx + 1] == "Read,Write"

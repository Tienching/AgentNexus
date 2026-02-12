# -*- coding: utf-8 -*-
"""Chat continue (session resume) command building tests.

Verifies that each provider's _build_command correctly appends
session-resume flags when run_kind == "chat_continue".
"""

from unittest.mock import Mock

import pytest

from src.runtime.executors.base import RequestContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(content: str = "Hello", run_kind: str = "", **kw) -> RequestContext:
    return RequestContext(content=content, run_kind=run_kind, **kw)


# ===========================================================================
# 1. providers/gemini – GeminiExecutor
# ===========================================================================

class TestGeminiProviderContinue:
    """providers/gemini/executor.py"""

    @pytest.fixture
    def executor(self):
        from src.providers.gemini.executor import GeminiExecutor
        cfg = Mock()
        cfg.gemini_command = "gemini"
        cfg.timeout = 120
        cfg.user_home_base = "/home"
        return GeminiExecutor(config=cfg)

    def test_normal_no_resume(self, executor):
        ctx = _make_context("Hello")
        cmd = executor._build_command(ctx)
        assert "--resume" not in cmd
        assert "-p" in cmd
        assert "Hello" in cmd

    def test_chat_continue_adds_resume_latest(self, executor):
        ctx = _make_context("Follow up", run_kind="chat_continue")
        cmd = executor._build_command(ctx)
        # --resume latest should appear before -p
        idx_resume = cmd.index("--resume")
        idx_p = cmd.index("-p")
        assert cmd[idx_resume + 1] == "latest"
        assert idx_resume < idx_p


# ===========================================================================
# 2. providers/codebuddy – CodebuddyCLIExecutor
# ===========================================================================

class TestCodebuddyProviderContinue:
    """providers/codebuddy/cli_executor.py"""

    @pytest.fixture
    def executor(self):
        from src.providers.codebuddy.cli_executor import CodebuddyCLIExecutor
        cfg = Mock()
        cfg.codebuddy_command = "codebuddy"
        cfg.timeout = 120
        cfg.user_home_base = "/home"
        return CodebuddyCLIExecutor(config=cfg)

    def test_normal_no_continue_flag(self, executor):
        ctx = _make_context("Hello")
        cmd = executor._build_command(ctx)
        assert "-c" not in cmd
        assert "-p" in cmd

    def test_chat_continue_adds_c_flag(self, executor):
        ctx = _make_context("Follow up", run_kind="chat_continue")
        cmd = executor._build_command(ctx)
        idx_c = cmd.index("-c")
        idx_p = cmd.index("-p")
        assert idx_c < idx_p


# ===========================================================================
# 3. providers/codex – CodexCLIExecutor
# ===========================================================================

class TestCodexProviderContinue:
    """providers/codex/cli_executor.py"""

    @pytest.fixture
    def executor(self):
        from src.providers.codex.cli_executor import CodexCLIExecutor
        cfg = Mock()
        cfg.codex_command = "codex-internal"
        cfg.skip_git_repo_check = False
        cfg.sandbox_mode = None
        cfg.full_auto = True
        cfg.timeout = 120
        cfg.user_home_base = "/home"
        return CodexCLIExecutor(config=cfg)

    def test_normal_no_resume(self, executor):
        ctx = _make_context("Hello")
        cmd = executor._build_command(ctx)
        assert "resume" not in cmd
        assert "--last" not in cmd
        assert "Hello" in cmd

    def test_chat_continue_appends_resume_last(self, executor):
        ctx = _make_context("Follow up", run_kind="chat_continue")
        cmd = executor._build_command(ctx)
        # "resume" and "--last" should appear after the prompt
        idx_prompt = cmd.index("Follow up")
        idx_resume = cmd.index("resume")
        idx_last = cmd.index("--last")
        assert idx_resume > idx_prompt
        assert idx_last > idx_resume


# ===========================================================================
# 4. runtime/executors/gemini_executor – GeminiExecutor (runtime layer)
# ===========================================================================

class TestGeminiRuntimeContinue:
    """runtime/executors/gemini_executor.py"""

    @pytest.fixture
    def executor(self):
        from src.runtime.executors.gemini_executor import GeminiExecutor
        cfg = Mock()
        cfg.gemini_command = "gemini"
        cfg.timeout = 120
        cfg.user_home_base = "/home"
        return GeminiExecutor(config=cfg)

    def test_normal_no_resume(self, executor):
        ctx = _make_context("Hello")
        cmd = executor._build_command(ctx)
        assert "--resume" not in cmd

    def test_chat_continue_adds_resume_latest(self, executor):
        ctx = _make_context("Follow up", run_kind="chat_continue")
        cmd = executor._build_command(ctx)
        idx_resume = cmd.index("--resume")
        assert cmd[idx_resume + 1] == "latest"


# ===========================================================================
# 5. runtime/executors/cli_executor – CLIExecutor (runtime layer)
# ===========================================================================

class TestCLIRuntimeProviderAware:
    """runtime/executors/cli_executor.py"""

    @pytest.fixture
    def executor(self):
        from src.runtime.executors.cli_executor import CLIExecutor, CLIExecutorConfig
        cfg = CLIExecutorConfig(
            cli_command="ccr",
            agent_cli_command_map={},
        )
        return CLIExecutor(config=cfg)

    @staticmethod
    def _make_executor_with_map(default_cmd: str = "ccr", cmd_map: dict = None):
        from src.runtime.executors.cli_executor import CLIExecutor, CLIExecutorConfig
        cfg = CLIExecutorConfig(
            cli_command=default_cmd,
            agent_cli_command_map=cmd_map or {},
        )
        return CLIExecutor(config=cfg)

    def test_default_cli_uses_c(self, executor):
        ctx = _make_context("Hello")
        cmd = executor._build_command(ctx, use_continue=True)
        assert "-c" in cmd

    def test_codex_command_skips_c(self):
        ex = self._make_executor_with_map(
            cmd_map={"codex_user": "codex-internal"},
        )
        ctx = _make_context("Hello", exec_user="codex_user")
        cmd = ex._build_command(ctx, use_continue=True)
        assert "-c" not in cmd
        # Codex uses positional args + resume --last, not -p (which is --profile)
        assert "resume" in cmd
        assert "--last" in cmd

    def test_gemini_command_uses_resume(self):
        ex = self._make_executor_with_map(
            cmd_map={"gemini_user": "gemini"},
        )
        ctx = _make_context("Hello", exec_user="gemini_user")
        cmd = ex._build_command(ctx, use_continue=True)
        assert "--resume" in cmd
        assert "latest" in cmd
        assert "-c" not in cmd
        # Gemini must NOT have Claude-specific flags
        assert "--include-partial-messages" not in cmd
        assert "--verbose" not in cmd
        assert "--dangerously-skip-permissions" not in cmd

    def test_no_continue_skips_all(self, executor):
        ctx = _make_context("Hello")
        cmd = executor._build_command(ctx, use_continue=False)
        assert "-c" not in cmd
        assert "--resume" not in cmd


# ===========================================================================
# 6. server/services/cli_executor – CLIExecutor (server layer)
# ===========================================================================

class TestCLIServerProviderAware:
    """server/services/cli_executor.py"""

    @pytest.fixture
    def executor(self):
        cfg = Mock()
        cfg.agent_cli_command_map = {}
        cfg.cli_command = "ccr"
        from src.server.services.cli_executor import CLIExecutor
        return CLIExecutor(config=cfg)

    def test_claude_uses_c(self, executor):
        cmd = executor._build_command(
            exec_user="ubuntu", content="Hello",
            use_continue=True, agent_type="claude",
        )
        assert "-c" in cmd

    def test_codex_skips_c(self, executor):
        cmd = executor._build_command(
            exec_user="ubuntu", content="Hello",
            use_continue=True, agent_type="codex-internal",
        )
        assert "-c" not in cmd
        # Codex uses positional args + resume --last, not -p (which is --profile)
        assert "resume" in cmd
        assert "--last" in cmd

    def test_gemini_uses_resume(self, executor):
        cmd = executor._build_command(
            exec_user="ubuntu", content="Hello",
            use_continue=True, agent_type="gemini-internal",
        )
        assert "--resume" in cmd
        assert "latest" in cmd
        assert "-c" not in cmd
        # Gemini must NOT have Claude-specific flags
        assert "--include-partial-messages" not in cmd
        assert "--verbose" not in cmd
        assert "--dangerously-skip-permissions" not in cmd

    def test_codebuddy_uses_c(self, executor):
        cmd = executor._build_command(
            exec_user="ubuntu", content="Hello",
            use_continue=True, agent_type="codebuddy",
        )
        assert "-c" in cmd

    def test_no_continue_skips_all(self, executor):
        cmd = executor._build_command(
            exec_user="ubuntu", content="Hello",
            use_continue=False, agent_type="codex-internal",
        )
        assert "-c" not in cmd
        assert "--resume" not in cmd

    def test_codex_continue_appends_resume_last(self, executor):
        """codex in continue mode should append 'resume --last' after prompt."""
        cmd = executor._build_command(
            exec_user="ubuntu", content="Follow up",
            use_continue=True, agent_type="codex-internal",
        )
        idx_prompt = cmd.index("Follow up")
        idx_resume = cmd.index("resume")
        idx_last = cmd.index("--last")
        assert idx_resume > idx_prompt
        assert idx_last > idx_resume

    def test_codex_no_continue_no_resume_last(self, executor):
        """codex without continue should NOT append 'resume --last'."""
        cmd = executor._build_command(
            exec_user="ubuntu", content="Hello",
            use_continue=False, agent_type="codex-internal",
        )
        assert "resume" not in cmd
        assert "--last" not in cmd

    def test_gemini_command_maps_to_gemini(self, executor):
        """gemini agent_type should produce 'gemini' as CLI command."""
        cmd = executor._build_command(
            exec_user="ubuntu", content="Hello",
            use_continue=True, agent_type="gemini",
        )
        assert cmd[0] == "gemini"

    def test_gemini_internal_command_maps_correctly(self, executor):
        """gemini-internal agent_type should produce 'gemini-internal' CLI command."""
        cmd = executor._build_command(
            exec_user="ubuntu", content="Hello",
            use_continue=True, agent_type="gemini-internal",
        )
        assert cmd[0] == "gemini-internal"
        # Gemini must NOT have Claude-specific flags
        assert "--include-partial-messages" not in cmd
        assert "--verbose" not in cmd
        assert "--dangerously-skip-permissions" not in cmd

    def test_codebuddy_command_maps_correctly(self, executor):
        """codebuddy agent_type should produce 'codebuddy' CLI command."""
        cmd = executor._build_command(
            exec_user="ubuntu", content="Hello",
            use_continue=True, agent_type="codebuddy",
        )
        assert cmd[0] == "codebuddy"

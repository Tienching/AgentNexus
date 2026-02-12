"""CLI 执行器单元测试

历史上曾存在 `CCRCodeService`，目前代码以 `CLIExecutor` 作为统一执行器。
本用例覆盖：
- 命令构建（是否带 -c）
- 输入清理（trim 行为）
"""

import json
from unittest.mock import Mock

import pytest

from src.server.services.cli_executor import CLIExecutor


@pytest.fixture
def executor():
    cfg = Mock()
    cfg.agent_cli_command_map = {}
    cfg.cli_command = "ccr"
    return CLIExecutor(config=cfg)


class TestCLIExecutor:
    def test_build_command_default_continue(self, executor):
        cmd = executor._build_command(exec_user="ubuntu", content="Test content", use_continue=True)

        assert isinstance(cmd, list)
        assert cmd[0] == "ccr"
        assert "code" in cmd
        assert "-c" in cmd
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert "--include-partial-messages" in cmd
        assert "--verbose" in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert "Test content" in cmd

    def test_build_command_without_continue(self, executor):
        cmd = executor._build_command(exec_user="ubuntu", content="Test content", use_continue=False)

        assert "-p" in cmd
        assert "-c" not in cmd

    def test_build_command_clear_uses_hello_message(self, executor):
        cmd = executor._build_command(exec_user="ubuntu", content="/clear", use_continue=True)

        # /clear 特殊处理：message 固定为 "你好"，并且不带 -c
        assert "-p" in cmd
        assert "-c" not in cmd
        assert "你好" in cmd

    def test_clean_content_trims_whitespace(self, executor):
        assert executor._clean_content("  hi  ") == "hi"
        assert executor._clean_content("\n\nhello\n") == "hello"


class TestCLIExecutorAlias:
    """Test alias overrides CLI command name in _build_command."""

    @pytest.fixture
    def executor(self):
        cfg = Mock()
        cfg.agent_cli_command_map = {}
        cfg.cli_command = "claude"
        return CLIExecutor(config=cfg)

    def test_alias_overrides_command_name(self, executor):
        """When alias is provided, it should be used as cmd[0] instead of provider."""
        cmd = executor._build_command(
            exec_user="ubuntu",
            content="Hello",
            use_continue=True,
            agent_type="claude",
            alias="claude-internal",
        )
        assert cmd[0] == "claude-internal"
        assert "-c" in cmd  # parameter format still follows claude (provider)

    def test_alias_overrides_gemini_provider(self, executor):
        cmd = executor._build_command(
            exec_user="ubuntu",
            content="Hello",
            use_continue=True,
            agent_type="gemini",
            alias="gemini-internal",
        )
        assert cmd[0] == "gemini-internal"
        assert "--resume" in cmd  # parameter format follows gemini
        # Gemini must NOT have Claude-specific flags
        assert "--include-partial-messages" not in cmd
        assert "--verbose" not in cmd
        assert "--dangerously-skip-permissions" not in cmd

    def test_no_alias_uses_provider(self, executor):
        cmd = executor._build_command(
            exec_user="ubuntu",
            content="Hello",
            use_continue=True,
            agent_type="claude",
            alias=None,
        )
        assert cmd[0] == "claude"

    def test_empty_alias_uses_provider(self, executor):
        cmd = executor._build_command(
            exec_user="ubuntu",
            content="Hello",
            use_continue=True,
            agent_type="codebuddy",
            alias="",
        )
        assert cmd[0] == "codebuddy"

    def test_alias_with_codex_provider(self, executor):
        cmd = executor._build_command(
            exec_user="ubuntu",
            content="Hello",
            use_continue=True,
            agent_type="codex",
            alias="codex-internal",
        )
        assert cmd[0] == "codex-internal"
        # codex doesn't use -c (it uses resume --last)
        assert "-c" not in cmd

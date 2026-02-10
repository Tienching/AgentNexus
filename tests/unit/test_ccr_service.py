"""CCR 执行器单元测试

历史上曾存在 `CCRCodeService`，目前代码以 `CCRExecutor` 作为统一执行器。
本用例覆盖：
- 命令构建（是否带 -c）
- 输入清理（trim 行为）
"""

import json
from unittest.mock import Mock

import pytest

from src.server.services.ccr_executor import CCRExecutor


@pytest.fixture
def executor():
    cfg = Mock()
    cfg.agent_ccr_command_map = {}
    cfg.ccr_command = "ccr"
    return CCRExecutor(config=cfg)


class TestCCRExecutor:
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

import shlex
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.server.routers import nexus_sessions
from src.server.routers.nexus_terminal import _build_tmux_command
from src.server.services.terminal_manager import _build_terminal_argv


class _Storage:
    def __init__(self, session, cli_session_id):
        self.session = session
        self.cli_session_id = cli_session_id

    def get_session_meta(self, _session_id):
        return self.session

    def get_exec_dir_override(self, _session_id):
        return None

    def get_cli_session_id(self, _session_id):
        return self.cli_session_id


def test_terminal_command_builder_keeps_untrusted_values_as_arguments():
    alias = "agent'; touch /tmp/alias-injected; #"
    cli_session_id = "resume'; touch /tmp/session-injected; #"
    exec_dir = "/tmp/work dir'; touch /tmp/dir-injected; #"
    session = SimpleNamespace(
        id="session-123",
        exec_user="ubuntu",
        exec_dir=exec_dir,
        provider="codebuddy",
        alias=alias,
    )

    result = _build_tmux_command(session, _Storage(session, cli_session_id))

    assert shlex.split(result["cli_cmd"]) == [alias, "-r", cli_session_id]


def test_terminal_manager_builds_argv_without_shell_interpolation():
    exec_dir = "/tmp/work dir'; touch /tmp/dir-injected; #"
    cli_cmd = "'agent; touch /tmp/cli-injected' -c"
    tmux_name = "nexus'; touch /tmp/name-injected; #"
    expected_tmux = [
        "tmux",
        "new-session",
        "-A",
        "-s",
        tmux_name,
        "-c",
        exec_dir,
        cli_cmd,
    ]

    assert _build_terminal_argv(
        exec_user="ubuntu",
        exec_dir=exec_dir,
        cli_cmd=cli_cmd,
        tmux_session_name=tmux_name,
        current_user="ubuntu",
    ) == expected_tmux

    switched = _build_terminal_argv(
        exec_user="worker",
        exec_dir=exec_dir,
        cli_cmd=cli_cmd,
        tmux_session_name=tmux_name,
        current_user="ubuntu",
    )
    assert switched[:4] == ["su", "-", "worker", "-c"]
    assert shlex.split(switched[4]) == expected_tmux


@pytest.mark.asyncio
async def test_tmux_api_returns_a_shell_safe_command(monkeypatch):
    alias = "agent'; touch /tmp/alias-injected; #"
    cli_session_id = "resume'; touch /tmp/session-injected; #"
    exec_dir = "/tmp/work dir'; touch /tmp/dir-injected; #"
    session_id = "session';touch"
    session = SimpleNamespace(
        exec_user="ubuntu",
        exec_dir=exec_dir,
        provider="codebuddy",
        alias=alias,
    )
    storage = _Storage(session, cli_session_id)
    monkeypatch.setattr(nexus_sessions, "get_session_storage", lambda: storage)
    monkeypatch.setattr(nexus_sessions, "validate_exec_user", AsyncMock(return_value="ubuntu"))

    result = await nexus_sessions.get_tmux_command(session_id)

    assert shlex.split(result["cli_command"]) == [alias, "-r", cli_session_id]
    assert shlex.split(result["tmux_command"]) == [
        "tmux",
        "new-session",
        "-A",
        "-s",
        f"nexus-{session_id[:12]}",
        "-c",
        exec_dir,
        result["cli_command"],
    ]

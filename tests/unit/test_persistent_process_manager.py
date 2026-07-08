# -*- coding: utf-8 -*-
"""Unit tests for PersistentProcessManager and PersistentProcess.

Tests cover:
    - Command building for persistent CLI processes
    - Process lifecycle (create, reuse, destroy, cleanup)
    - Provider support checks
    - Per-user session limits
    - Stream output and completion detection (mocked subprocess)
"""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.providers.persistent.completion_detector import CompletionDetector, CompletionStatus
from src.providers.persistent.process_manager import (
    PersistentProcess,
    PersistentProcessManager,
    _STREAM_INPUT_PROVIDERS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_config(**overrides):
    """Create a mock config with persistent defaults."""
    cfg = Mock()
    cfg.persistent_idle_timeout = overrides.get("persistent_idle_timeout", 1800.0)
    cfg.persistent_quiescence_timeout = overrides.get("persistent_quiescence_timeout", 3.0)
    cfg.persistent_max_sessions_per_user = overrides.get("persistent_max_sessions_per_user", 5)
    cfg.persistent_init_timeout = overrides.get("persistent_init_timeout", 60.0)
    cfg.cli_timeout = overrides.get("cli_timeout", 600)
    return cfg


def _make_mock_process(alive: bool = True, returncode=None):
    """Create a mock asyncio subprocess.

    Note: asyncio.subprocess.Process.kill() is a regular (sync) method,
    while .wait() is a coroutine.  We use MagicMock for kill and
    AsyncMock for wait to match the real API.
    """
    proc = AsyncMock(spec=asyncio.subprocess.Process)
    proc.returncode = returncode if not alive else None
    proc.stdin = AsyncMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdout = AsyncMock()
    proc.stderr = AsyncMock()
    proc.kill = MagicMock()  # sync method
    proc.wait = AsyncMock()  # async coroutine
    return proc


def _make_persistent_process(
    session_id: str = "test-session",
    exec_user: str = "ubuntu",
    provider: str = "claude",
    alive: bool = True,
    last_activity: float = None,
) -> PersistentProcess:
    """Create a PersistentProcess with a mock subprocess."""
    mock_proc = _make_mock_process(alive=alive)
    detector = CompletionDetector(quiescence_timeout=3.0)
    pp = PersistentProcess(
        session_id=session_id,
        exec_user=exec_user,
        provider=provider,
        process=mock_proc,
        detector=detector,
    )
    if last_activity is not None:
        pp.last_activity = last_activity
    return pp


# ===========================================================================
# PersistentProcess — unit tests
# ===========================================================================

class TestPersistentProcess:
    """Tests for the PersistentProcess dataclass."""

    def test_alive_property_when_running(self):
        pp = _make_persistent_process(alive=True)
        assert pp.alive is True

    def test_alive_property_when_exited(self):
        pp = _make_persistent_process(alive=False)
        pp.process.returncode = 0
        assert pp.alive is False

    def test_cli_session_id_initially_none(self):
        pp = _make_persistent_process()
        assert pp.cli_session_id is None

    def test_cli_session_id_from_detector(self):
        pp = _make_persistent_process()
        pp.detector._session_id = "detected-id"
        assert pp.cli_session_id == "detected-id"

    def test_cli_session_id_explicit_overrides_detector(self):
        pp = _make_persistent_process()
        pp._cli_session_id = "explicit-id"
        pp.detector._session_id = "detected-id"
        assert pp.cli_session_id == "explicit-id"

    @pytest.mark.asyncio
    async def test_send_message_writes_to_stdin(self):
        pp = _make_persistent_process()
        await pp.send_message("Hello, world!")

        pp.process.stdin.write.assert_called_once()
        written = pp.process.stdin.write.call_args[0][0]
        data = json.loads(written.decode("utf-8").strip())

        assert data["type"] == "user"
        assert data["message"]["role"] == "user"
        assert data["message"]["content"][0]["type"] == "text"
        assert data["message"]["content"][0]["text"] == "Hello, world!"

    @pytest.mark.asyncio
    async def test_send_message_drains_stdin(self):
        pp = _make_persistent_process()
        await pp.send_message("test")
        pp.process.stdin.drain.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_message_updates_last_activity(self):
        pp = _make_persistent_process()
        old_activity = pp.last_activity
        await asyncio.sleep(0.01)
        await pp.send_message("test")
        assert pp.last_activity > old_activity

    @pytest.mark.asyncio
    async def test_send_message_raises_when_dead(self):
        pp = _make_persistent_process(alive=False)
        pp.process.returncode = 1
        with pytest.raises(RuntimeError, match="not alive"):
            await pp.send_message("hello")

    @pytest.mark.asyncio
    async def test_kill_terminates_process(self):
        pp = _make_persistent_process(alive=True)
        await pp.kill()
        pp.process.kill.assert_called_once()
        pp.process.wait.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_kill_safe_when_already_dead(self):
        pp = _make_persistent_process(alive=False)
        pp.process.returncode = 0
        await pp.kill()
        # Should not raise, but kill is NOT called since not alive
        pp.process.kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_wait_for_init_success(self):
        pp = _make_persistent_process()
        init_event = {
            "type": "system",
            "subtype": "init",
            "session_id": "init-uuid-123",
        }
        pp.process.stdout.readline = AsyncMock(
            return_value=json.dumps(init_event).encode("utf-8") + b"\n"
        )

        result = await pp.wait_for_init(timeout=5.0)
        assert result is not None
        assert result["type"] == "system"
        assert result["subtype"] == "init"
        assert pp._init_received is True
        assert pp._cli_session_id == "init-uuid-123"

    @pytest.mark.asyncio
    async def test_wait_for_init_already_received(self):
        pp = _make_persistent_process()
        pp._init_received = True
        result = await pp.wait_for_init()
        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_init_timeout(self):
        pp = _make_persistent_process()
        pp.process.stdout.readline = AsyncMock(side_effect=asyncio.TimeoutError)
        result = await pp.wait_for_init(timeout=0.1)
        assert result is None
        assert pp._init_received is False

    @pytest.mark.asyncio
    async def test_wait_for_init_eof(self):
        pp = _make_persistent_process()
        pp.process.stdout.readline = AsyncMock(return_value=b"")
        result = await pp.wait_for_init(timeout=5.0)
        assert result is None


# ===========================================================================
# PersistentProcessManager — command building
# ===========================================================================

class TestPersistentProcessManagerCommands:
    """Tests for _build_persistent_cmd()."""

    @pytest.fixture
    def manager(self):
        return PersistentProcessManager(config=_make_mock_config())

    def test_basic_claude_command(self, manager):
        cmd = manager._build_persistent_cmd("claude", Path("/home/user"))
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--input-format" in cmd
        assert "stream-json" in cmd
        assert "--output-format" in cmd
        assert "--verbose" in cmd
        assert "--dangerously-skip-permissions" in cmd

    def test_codebuddy_command(self, manager):
        cmd = manager._build_persistent_cmd("codebuddy", Path("/home/user"))
        assert cmd[0] == "codebuddy"
        assert "--dangerously-skip-permissions" in cmd

    def test_codex_command(self, manager):
        cmd = manager._build_persistent_cmd("codex", Path("/home/user"))
        assert cmd[0] == "codex"
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd
        assert "--dangerously-skip-permissions" not in cmd

    def test_model_override(self, manager):
        cmd = manager._build_persistent_cmd("claude", Path("/home/user"), model="claude-3-opus")
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-3-opus"

    def test_no_model_when_none(self, manager):
        cmd = manager._build_persistent_cmd("claude", Path("/home/user"), model=None)
        assert "--model" not in cmd

    def test_alias_overrides_provider(self, manager):
        cmd = manager._build_persistent_cmd("claude", Path("/home/user"), alias="claude-internal")
        assert cmd[0] == "claude-internal"

    def test_stream_json_flags(self, manager):
        cmd = manager._build_persistent_cmd("claude", Path("/home/user"))
        # Find indices for format flags
        input_idx = cmd.index("--input-format")
        output_idx = cmd.index("--output-format")
        assert cmd[input_idx + 1] == "stream-json"
        assert cmd[output_idx + 1] == "stream-json"


# ===========================================================================
# PersistentProcessManager — provider support
# ===========================================================================

class TestProviderSupport:
    """Tests for supports_persistent() static method."""

    def test_claude_supported(self):
        assert PersistentProcessManager.supports_persistent("claude") is True

    def test_codebuddy_supported(self):
        assert PersistentProcessManager.supports_persistent("codebuddy") is True

    def test_codex_not_supported(self):
        assert PersistentProcessManager.supports_persistent("codex") is False

    def test_empty_string_not_supported(self):
        assert PersistentProcessManager.supports_persistent("") is False

    def test_none_not_supported(self):
        assert PersistentProcessManager.supports_persistent(None) is False

    def test_case_insensitive(self):
        assert PersistentProcessManager.supports_persistent("CLAUDE") is True
        assert PersistentProcessManager.supports_persistent("Claude") is True
        assert PersistentProcessManager.supports_persistent("CODEBUDDY") is True

    def test_whitespace_stripped(self):
        assert PersistentProcessManager.supports_persistent("  claude  ") is True

    def test_stream_input_providers_is_frozen(self):
        """Ensure the provider set is immutable."""
        assert isinstance(_STREAM_INPUT_PROVIDERS, frozenset)
        assert "claude" in _STREAM_INPUT_PROVIDERS
        assert "codebuddy" in _STREAM_INPUT_PROVIDERS


# ===========================================================================
# PersistentProcessManager — lifecycle management
# ===========================================================================

class TestPersistentProcessManagerLifecycle:
    """Tests for process creation, reuse, destruction, and cleanup."""

    @pytest.fixture
    def manager(self):
        return PersistentProcessManager(config=_make_mock_config())

    @pytest.mark.asyncio
    async def test_destroy_nonexistent_session(self, manager):
        """Destroying a non-existent session should not raise."""
        await manager.destroy("nonexistent-session")

    @pytest.mark.asyncio
    async def test_destroy_existing_session(self, manager):
        pp = _make_persistent_process(session_id="s1")
        manager._processes["s1"] = pp
        assert manager.active_count == 1

        await manager.destroy("s1")
        assert "s1" not in manager._processes
        pp.process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_destroy_for_user(self, manager):
        pp1 = _make_persistent_process(session_id="s1", exec_user="alice")
        pp2 = _make_persistent_process(session_id="s2", exec_user="bob")
        pp3 = _make_persistent_process(session_id="s3", exec_user="alice")
        manager._processes = {"s1": pp1, "s2": pp2, "s3": pp3}

        killed = await manager.destroy_for_user("alice")
        assert killed == 2
        assert "s1" not in manager._processes
        assert "s3" not in manager._processes
        assert "s2" in manager._processes

    @pytest.mark.asyncio
    async def test_cleanup_idle_sessions(self, manager):
        manager._idle_timeout = 60.0  # 60 seconds

        # Active session (recent activity)
        pp_active = _make_persistent_process(
            session_id="active", last_activity=time.time()
        )
        # Idle session (old activity)
        pp_idle = _make_persistent_process(
            session_id="idle", last_activity=time.time() - 120
        )
        # Dead session
        pp_dead = _make_persistent_process(session_id="dead", alive=False)
        pp_dead.process.returncode = 1

        manager._processes = {
            "active": pp_active,
            "idle": pp_idle,
            "dead": pp_dead,
        }

        cleaned = await manager.cleanup_idle()
        assert cleaned == 2
        assert "active" in manager._processes
        assert "idle" not in manager._processes
        assert "dead" not in manager._processes

    @pytest.mark.asyncio
    async def test_shutdown_kills_all(self, manager):
        pp1 = _make_persistent_process(session_id="s1")
        pp2 = _make_persistent_process(session_id="s2")
        manager._processes = {"s1": pp1, "s2": pp2}

        await manager.shutdown()
        assert len(manager._processes) == 0
        pp1.process.kill.assert_called_once()
        pp2.process.kill.assert_called_once()

    def test_active_count(self, manager):
        pp_alive = _make_persistent_process(session_id="alive", alive=True)
        pp_dead = _make_persistent_process(session_id="dead", alive=False)
        pp_dead.process.returncode = 1
        manager._processes = {"alive": pp_alive, "dead": pp_dead}
        assert manager.active_count == 1

    def test_get_session_info_existing(self, manager):
        pp = _make_persistent_process(session_id="info-test")
        pp._cli_session_id = "cli-uuid"
        manager._processes["info-test"] = pp

        info = manager.get_session_info("info-test")
        assert info is not None
        assert info["session_id"] == "info-test"
        assert info["provider"] == "claude"
        assert info["exec_user"] == "ubuntu"
        assert info["alive"] is True
        assert info["cli_session_id"] == "cli-uuid"
        assert "idle_seconds" in info

    def test_get_session_info_nonexistent(self, manager):
        assert manager.get_session_info("no-such") is None


# ===========================================================================
# PersistentProcessManager — per-user limits
# ===========================================================================

class TestPerUserLimits:
    """Tests for max sessions per user enforcement."""

    @pytest.mark.asyncio
    async def test_evicts_oldest_when_limit_reached(self):
        manager = PersistentProcessManager(
            config=_make_mock_config(persistent_max_sessions_per_user=2)
        )

        # Pre-populate with 2 sessions for "alice"
        pp_old = _make_persistent_process(
            session_id="old", exec_user="alice",
            last_activity=time.time() - 100,
        )
        pp_new = _make_persistent_process(
            session_id="new", exec_user="alice",
            last_activity=time.time(),
        )
        manager._processes = {"old": pp_old, "new": pp_new}

        # Patch _create_process to avoid actually spawning
        pp_newest = _make_persistent_process(
            session_id="newest", exec_user="alice"
        )
        manager._create_process = AsyncMock(return_value=pp_newest)

        result = await manager.get_or_create(
            session_id="newest",
            exec_user="alice",
            provider="claude",
            exec_dir=Path("/home/alice"),
        )

        # "old" should have been evicted
        assert "old" not in manager._processes
        pp_old.process.kill.assert_called_once()

        # "new" and "newest" should remain
        assert "new" in manager._processes
        assert "newest" in manager._processes
        assert result.session_id == "newest"


# ===========================================================================
# PersistentProcessManager — reuse existing
# ===========================================================================

class TestProcessReuse:
    """Tests for get_or_create reusing existing processes."""

    @pytest.mark.asyncio
    async def test_reuses_alive_process(self):
        manager = PersistentProcessManager(config=_make_mock_config())
        pp = _make_persistent_process(session_id="reuse-me")
        manager._processes["reuse-me"] = pp

        result = await manager.get_or_create(
            session_id="reuse-me",
            exec_user="ubuntu",
            provider="claude",
            exec_dir=Path("/home/ubuntu"),
        )
        assert result is pp

    @pytest.mark.asyncio
    async def test_recreates_dead_process(self):
        manager = PersistentProcessManager(config=_make_mock_config())
        pp_dead = _make_persistent_process(session_id="dead-one", alive=False)
        pp_dead.process.returncode = 1
        manager._processes["dead-one"] = pp_dead

        pp_new = _make_persistent_process(session_id="dead-one")
        manager._create_process = AsyncMock(return_value=pp_new)

        result = await manager.get_or_create(
            session_id="dead-one",
            exec_user="ubuntu",
            provider="claude",
            exec_dir=Path("/home/ubuntu"),
        )
        assert result is pp_new
        assert result is not pp_dead

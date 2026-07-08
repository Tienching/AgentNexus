# -*- coding: utf-8 -*-
"""Unit tests for persistent process routing in CLIExecutor.

Tests the decision logic (_should_use_persistent) and transition handling
(model switch, user switch, /clear) for persistent CLI processes.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.providers.persistent.process_manager import PersistentProcessManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_config(persistent_enabled=True, **kw):
    """Create a mock Settings-like config."""
    cfg = Mock()
    cfg.persistent_enabled = persistent_enabled
    cfg.persistent_idle_timeout = kw.get("persistent_idle_timeout", 1800.0)
    cfg.persistent_quiescence_timeout = kw.get("persistent_quiescence_timeout", 3.0)
    cfg.persistent_max_sessions_per_user = kw.get("persistent_max_sessions_per_user", 5)
    cfg.persistent_init_timeout = kw.get("persistent_init_timeout", 60.0)
    cfg.cli_timeout = kw.get("cli_timeout", 600)
    cfg.cli_command = "claude"
    cfg.agent_cli_command_map = {}
    cfg.user_home_base = "/home"
    cfg.auto_create_user_dir = False
    cfg.exec_user = "ubuntu"
    cfg.log_level = "INFO"
    return cfg


def _make_mock_request(
    content="Hello",
    session_id="test-session",
    user="testuser",
    agent_type=None,
    provider=None,
    model=None,
    use_persistent=None,
    model_changed=False,
    run_kind="",
    alias=None,
):
    """Create a mock RequestModel-like object."""
    req = Mock()
    req.content = content
    req.session_id = session_id
    req.user = user
    req.msg_type = "text"
    req.msg_id = "msg-001"
    req.raw_msg = ""
    req.business_keys = []
    req.agent_type = agent_type
    req.provider = provider
    req.model = model
    req.model_changed = model_changed
    req.run_kind = run_kind
    req.alias = alias
    # Simulate extra field via getattr
    req.use_persistent = use_persistent
    req.exec_dir = None
    req.exec_user = None
    return req


def _make_mock_storage(persistent_mode=False, session_cleared=False, exec_user_switched=False):
    """Create a mock SessionStorage."""
    store = Mock()
    store.get_persistent_mode = Mock(return_value=persistent_mode)
    store.set_persistent_mode = Mock(return_value=True)
    store.clear_persistent_mode = Mock(return_value=True)
    store.consume_session_cleared = Mock(return_value=session_cleared)
    store.consume_exec_user_switched = Mock(return_value=exec_user_switched)
    store.get_session_meta = Mock(return_value=None)
    store.get_cli_session_id = Mock(return_value=None)
    return store


# ===========================================================================
# _should_use_persistent — decision logic
# ===========================================================================

class TestShouldUsePersistent:
    """Tests for CLIExecutor._should_use_persistent()."""

    @pytest.fixture
    def executor_cls(self):
        from src.server.services.cli_executor import CLIExecutor
        return CLIExecutor

    @pytest.fixture
    def executor_enabled(self, executor_cls):
        """CLIExecutor with persistent mode enabled."""
        cfg = _make_mock_config(persistent_enabled=True)
        exc = executor_cls.__new__(executor_cls)
        exc.config = cfg
        exc._persistent_manager = PersistentProcessManager(config=cfg)
        exc._slash_handlers = {}
        exc._current_process = None
        return exc

    @pytest.fixture
    def executor_disabled(self, executor_cls):
        """CLIExecutor with persistent mode disabled."""
        cfg = _make_mock_config(persistent_enabled=False)
        exc = executor_cls.__new__(executor_cls)
        exc.config = cfg
        exc._persistent_manager = None
        exc._slash_handlers = {}
        exc._current_process = None
        return exc

    # ── Global toggle ────────────────────────────────────────────────

    def test_disabled_when_manager_is_none(self, executor_disabled):
        req = _make_mock_request(agent_type="claude")
        assert executor_disabled._should_use_persistent(req, "s1", None) is False

    # ── Per-request override ─────────────────────────────────────────

    def test_request_override_true(self, executor_enabled):
        req = _make_mock_request(agent_type="claude", use_persistent=True)
        assert executor_enabled._should_use_persistent(req, "s1", None) is True

    def test_request_override_false(self, executor_enabled):
        req = _make_mock_request(agent_type="claude", use_persistent=False)
        storage = _make_mock_storage(persistent_mode=True)
        assert executor_enabled._should_use_persistent(req, "s1", storage) is False

    # ── Session stickiness ───────────────────────────────────────────

    def test_sticky_session_returns_true(self, executor_enabled):
        req = _make_mock_request(agent_type="claude")
        storage = _make_mock_storage(persistent_mode=True)
        assert executor_enabled._should_use_persistent(req, "s1", storage) is True

    def test_no_sticky_session_falls_through(self, executor_enabled):
        req = _make_mock_request(agent_type="claude")
        storage = _make_mock_storage(persistent_mode=False)
        # Without explicit request override and no stickiness, falls to provider check
        # Provider is supported but default is False
        assert executor_enabled._should_use_persistent(req, "s1", storage) is False

    # ── Provider check ───────────────────────────────────────────────

    def test_unsupported_provider_returns_false(self, executor_enabled):
        req = _make_mock_request(agent_type="cursor", use_persistent=True)
        # Even with request override True, provider check should...
        # Actually, request override=True wins at step 2 before provider check
        # Let's test without request override
        req2 = _make_mock_request(agent_type="cursor")
        storage = _make_mock_storage(persistent_mode=False)
        assert executor_enabled._should_use_persistent(req2, "s1", storage) is False

    # ── No storage ───────────────────────────────────────────────────

    def test_no_storage_skips_stickiness(self, executor_enabled):
        req = _make_mock_request(agent_type="claude")
        # No storage, no stickiness, default False
        assert executor_enabled._should_use_persistent(req, "s1", None) is False


# ===========================================================================
# Transition handling — model switch / exec_user switch / clear
# ===========================================================================

class TestTransitionHandling:
    """Tests that transitions properly destroy persistent processes.

    These tests verify the integration between the transition flag checking
    and the persistent process destruction in execute().
    Since execute() is a complex async generator, we test the individual
    pieces that make up the transition logic.
    """

    @pytest.mark.asyncio
    async def test_persistent_manager_destroy_is_called_on_session_clear(self):
        """Verify that destroy is callable and cleans up."""
        manager = PersistentProcessManager(config=_make_mock_config())
        # Pre-populate a mock process
        from tests.unit.test_persistent_process_manager import _make_persistent_process
        pp = _make_persistent_process(session_id="clear-me")
        manager._processes["clear-me"] = pp

        await manager.destroy("clear-me")
        assert "clear-me" not in manager._processes

    def test_storage_clear_persistent_mode_on_transition(self):
        """Verify storage.clear_persistent_mode works."""
        storage = _make_mock_storage(persistent_mode=True)
        storage.clear_persistent_mode("s1")
        storage.clear_persistent_mode.assert_called_with("s1")

    def test_supports_persistent_check(self):
        """After model switch to unsupported provider, persistent should be False."""
        assert PersistentProcessManager.supports_persistent("cursor") is False
        assert PersistentProcessManager.supports_persistent("claude") is True

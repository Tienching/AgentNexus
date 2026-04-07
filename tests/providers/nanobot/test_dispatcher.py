# -*- coding: utf-8 -*-
"""Tests for nanobot integration into the dispatcher."""

import os
import pytest
from unittest.mock import patch, MagicMock

from src.providers.dispatcher import normalize_provider, create_adapter, create_executor


class TestDispatcherNanobot:

    def test_normalize_nanobot(self):
        assert normalize_provider("nanobot") == "nanobot"
        assert normalize_provider("Nanobot") == "nanobot"
        assert normalize_provider("NANOBOT") == "nanobot"

    def test_normalize_existing_providers_unchanged(self):
        assert normalize_provider("claude") == "claude"
        assert normalize_provider("gemini") == "gemini"
        assert normalize_provider("codex") == "codex"
        assert normalize_provider("codebuddy") == "codebuddy"

    def test_normalize_default_fallback(self):
        """Empty/unknown name should fall back to nanobot (default)."""
        assert normalize_provider(None) == "nanobot"
        assert normalize_provider("") == "nanobot"
        assert normalize_provider("unknown") == "nanobot"

    def test_normalize_default_env_override(self):
        """AGENT_NEXUS_DEFAULT_PROVIDER can override the default."""
        with patch.dict(os.environ, {"AGENT_NEXUS_DEFAULT_PROVIDER": "claude"}, clear=False):
            assert normalize_provider(None) == "claude"
            assert normalize_provider("") == "claude"

    def test_create_adapter_nanobot(self):
        from src.providers.nanobot.adapter import NanobotAGUIAdapter
        adapter = create_adapter("nanobot")
        assert isinstance(adapter, NanobotAGUIAdapter)

    def test_create_adapter_claude_still_works(self):
        adapter = create_adapter("claude")
        assert adapter is not None
        assert hasattr(adapter, "convert")

    def test_create_executor_nanobot(self):
        config = MagicMock()
        config.nanobot_workspace = "/tmp/test"
        config.nanobot_model = "gpt-4o"
        executor = create_executor("nanobot", config=config)
        from src.providers.nanobot.executor import NanobotExecutor
        assert isinstance(executor, NanobotExecutor)

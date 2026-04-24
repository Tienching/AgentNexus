# -*- coding: utf-8 -*-
"""Tests for nexus integration into the dispatcher."""

import os
import pytest
from unittest.mock import patch, MagicMock

from src.providers.dispatcher import normalize_provider, create_adapter, create_executor


class TestDispatcherNexus:

    def test_normalize_nexus(self):
        assert normalize_provider("nexus") == "nexus"
        assert normalize_provider("Nexus") == "nexus"
        assert normalize_provider("NEXUS") == "nexus"
        assert normalize_provider("nanobot") == "nexus"

    def test_normalize_existing_providers_unchanged(self):
        assert normalize_provider("claude") == "claude"
        assert normalize_provider("gemini") == "gemini"
        assert normalize_provider("codex") == "codex"
        assert normalize_provider("codebuddy") == "codebuddy"

    def test_normalize_default_fallback(self):
        """Empty/unknown name should fall back to nexus (default)."""
        default_alias = normalize_provider(None)
        assert default_alias == "nexus"
        assert normalize_provider("") == default_alias
        assert normalize_provider("unknown") == default_alias

    def test_normalize_default_env_override(self):
        """AGENT_NEXUS_DEFAULT_PROVIDER can override the default."""
        with patch.dict(os.environ, {"AGENT_NEXUS_DEFAULT_PROVIDER": "claude"}, clear=False):
            assert normalize_provider(None) == "claude"
            assert normalize_provider("") == "claude"

    def test_create_adapter_nexus(self):
        from src.providers.nexus.adapter import NexusAGUIAdapter
        adapter = create_adapter("nexus")
        assert isinstance(adapter, NexusAGUIAdapter)

    def test_create_adapter_claude_still_works(self):
        adapter = create_adapter("claude")
        assert adapter is not None
        assert hasattr(adapter, "convert")

    def test_create_executor_nexus(self):
        config = MagicMock()
        config.nexus_workspace = "/tmp/test"
        config.nexus_model = "gpt-4o"
        executor = create_executor("nexus", config=config)
        from src.providers.nexus.executor import NexusExecutor
        assert isinstance(executor, NexusExecutor)

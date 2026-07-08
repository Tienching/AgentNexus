# -*- coding: utf-8 -*-
"""Legacy nexus/nanobot dispatcher alias behavior."""

import os
from unittest.mock import patch

from src.providers.dispatcher import normalize_provider, create_adapter, create_executor


class TestDispatcherLegacyNexusAliases:

    def test_legacy_aliases_resolve_to_nexus(self):
        assert normalize_provider("nexus") == "nexus"
        assert normalize_provider("Nexus") == "nexus"
        assert normalize_provider("NEXUS") == "nexus"
        assert normalize_provider("nanobot") == "nexus"

    def test_normalize_existing_providers_unchanged(self):
        assert normalize_provider("claude") == "claude"
        assert normalize_provider("codex") == "codex"
        assert normalize_provider("codebuddy") == "codebuddy"
        assert normalize_provider("hermes") == "hermes"

    def test_normalize_default_fallback(self):
        """Empty/unknown names fall back to the configured default provider."""
        default_alias = normalize_provider(None)
        assert default_alias == "claude"
        assert normalize_provider("") == default_alias
        assert normalize_provider("unknown") == default_alias

    def test_normalize_default_env_override(self):
        """AGENT_NEXUS_DEFAULT_PROVIDER can override the default."""
        with patch.dict(os.environ, {"AGENT_NEXUS_DEFAULT_PROVIDER": "codex"}, clear=False):
            assert normalize_provider(None) == "codex"
            assert normalize_provider("") == "codex"

    def test_create_adapter_nexus_uses_nexus_adapter(self):
        from src.runtime.adapters.nexus import NexusAGUIAdapter
        adapter = create_adapter("nexus")
        assert isinstance(adapter, NexusAGUIAdapter)

    def test_create_adapter_claude_still_works(self):
        adapter = create_adapter("claude")
        assert adapter is not None
        assert hasattr(adapter, "convert")

    def test_create_executor_nexus_uses_nexus_executor(self):
        from src.providers.nexus import NexusExecutor
        executor = create_executor("nexus")
        assert isinstance(executor, NexusExecutor)

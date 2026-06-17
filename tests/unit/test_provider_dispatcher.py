# -*- coding: utf-8 -*-
"""Unit tests for src.providers.dispatcher — centralized provider dispatch.

Covers the post-nexus-removal behavior:
  - normalize_provider() canonicalizes claude/codex/gemini/codebuddy + aliases
  - empty / unknown values fall back to providers.registry.DEFAULT_PROVIDER (claude)
  - create_executor() / create_adapter() dispatch to the correct factory
  - create_all_executors() pre-creates the four canonical providers
"""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# normalize_provider  (pure function)
# ---------------------------------------------------------------------------

class TestNormalizeProvider:
    def setup_method(self):
        from src.providers.dispatcher import normalize_provider
        self.normalize = normalize_provider

    def test_canonical_providers_returned_as_is(self):
        assert self.normalize("claude") == "claude"
        assert self.normalize("gemini") == "gemini"
        assert self.normalize("codex") == "codex"
        assert self.normalize("codebuddy") == "codebuddy"

    def test_case_insensitive(self):
        assert self.normalize("Claude") == "claude"
        assert self.normalize("GEMINI") == "gemini"
        assert self.normalize("Codex") == "codex"
        assert self.normalize("CodeBuddy") == "codebuddy"

    def test_whitespace_stripped(self):
        assert self.normalize("  gemini  ") == "gemini"
        assert self.normalize("\tcodex\n") == "codex"

    def test_none_defaults_to_claude(self):
        assert self.normalize(None) == "claude"
        assert self.normalize("") == "claude"
        assert self.normalize("   ") == "claude"

    def test_unknown_provider_falls_back_to_default(self):
        # nexus/nanobot were removed; they now fall through to the default.
        assert self.normalize("openai") == "claude"
        assert self.normalize("gpt4") == "claude"
        assert self.normalize("nexus") == "claude"
        assert self.normalize("nanobot") == "claude"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("AGENT_NEXUS_DEFAULT_PROVIDER", "codex")
        assert self.normalize(None) == "codex"
        assert self.normalize("unknown") == "codex"


# ---------------------------------------------------------------------------
# create_executor
# ---------------------------------------------------------------------------

class TestCreateExecutor:
    @patch("src.server.services.cli_executor.CLIExecutor")
    def test_claude_creates_cli_executor(self, MockCLI):
        MockCLI.return_value = MagicMock(name="CLIExecutor_instance")
        from src.providers.dispatcher import create_executor
        result = create_executor("claude", config=MagicMock())
        MockCLI.assert_called_once()
        assert result is MockCLI.return_value

    def test_gemini_creates_gemini_executor(self):
        mock_config = MagicMock()
        with patch("src.providers.gemini.GeminiExecutor") as MockGemini:
            MockGemini.return_value = MagicMock(name="GeminiExecutor_instance")
            from src.providers.dispatcher import create_executor
            result = create_executor("gemini", config=mock_config)
            MockGemini.assert_called_once_with(config=mock_config)
            assert result is MockGemini.return_value

    def test_codex_creates_codex_executor(self):
        with patch("src.providers.codex.CodexCLIExecutor") as MockCodex:
            MockCodex.return_value = MagicMock(name="CodexCLIExecutor_instance")
            from src.providers.dispatcher import create_executor
            result = create_executor("codex", config=MagicMock())
            assert result is MockCodex.return_value

    def test_codebuddy_creates_codebuddy_executor(self):
        with patch("src.providers.codebuddy.CodebuddyCLIExecutor") as MockCB:
            MockCB.return_value = MagicMock(name="CodebuddyCLIExecutor_instance")
            from src.providers.dispatcher import create_executor
            result = create_executor("codebuddy", config=MagicMock())
            assert result is MockCB.return_value

    def test_unknown_provider_falls_back_to_claude(self):
        """Removed providers (nexus/nanobot) + unknowns route to the claude default."""
        with patch("src.server.services.cli_executor.CLIExecutor") as MockCLI:
            MockCLI.return_value = MagicMock(name="CLIExecutor_instance")
            from src.providers.dispatcher import create_executor
            for name in ("nexus", "nanobot", "unknown_provider", None):
                result = create_executor(name, config=MagicMock())
                assert result is MockCLI.return_value


# ---------------------------------------------------------------------------
# create_adapter
# ---------------------------------------------------------------------------

class TestCreateAdapter:
    def test_claude_creates_agui_adapter(self):
        with patch("src.runtime.adapters.claude.AGUIAdapter") as MockAdapter:
            MockAdapter.return_value = MagicMock(name="AGUIAdapter_instance")
            from src.providers.dispatcher import create_adapter
            assert create_adapter("claude") is MockAdapter.return_value

    def test_gemini_creates_gemini_adapter(self):
        with patch("src.runtime.adapters.gemini.GeminiAGUIAdapter") as MockAdapter:
            MockAdapter.return_value = MagicMock(name="GeminiAGUIAdapter_instance")
            from src.providers.dispatcher import create_adapter
            assert create_adapter("gemini") is MockAdapter.return_value

    def test_codex_creates_codex_adapter(self):
        with patch("src.runtime.adapters.codex.CodexCLIAGUIAdapter") as MockAdapter:
            MockAdapter.return_value = MagicMock(name="CodexCLIAGUIAdapter_instance")
            from src.providers.dispatcher import create_adapter
            assert create_adapter("codex") is MockAdapter.return_value

    def test_codebuddy_creates_codebuddy_adapter(self):
        with patch("src.runtime.adapters.codebuddy.CodebuddyAGUIAdapter") as MockAdapter:
            MockAdapter.return_value = MagicMock(name="CodebuddyAGUIAdapter_instance")
            from src.providers.dispatcher import create_adapter
            assert create_adapter("codebuddy") is MockAdapter.return_value

    def test_unknown_provider_uses_claude_adapter(self):
        with patch("src.runtime.adapters.claude.AGUIAdapter") as MockAdapter:
            MockAdapter.return_value = MagicMock(name="AGUIAdapter_instance")
            from src.providers.dispatcher import create_adapter
            for name in ("nexus", "nanobot", "unknown"):
                assert create_adapter(name) is MockAdapter.return_value


# ---------------------------------------------------------------------------
# create_all_executors
# ---------------------------------------------------------------------------

class TestCreateAllExecutors:
    def test_returns_four_canonical_providers(self):
        with (
            patch("src.server.services.cli_executor.CLIExecutor"),
            patch("src.providers.gemini.GeminiExecutor"),
            patch("src.providers.codex.CodexCLIExecutor"),
            patch("src.providers.codebuddy.CodebuddyCLIExecutor"),
        ):
            from src.providers.dispatcher import create_all_executors
            result = create_all_executors(config=MagicMock())
            assert set(result) == {"claude", "gemini", "codex", "codebuddy"}
            assert "nexus" not in result and "nanobot" not in result

    def test_each_value_is_unique_instance(self):
        with (
            patch("src.server.services.cli_executor.CLIExecutor"),
            patch("src.providers.gemini.GeminiExecutor"),
            patch("src.providers.codex.CodexCLIExecutor"),
            patch("src.providers.codebuddy.CodebuddyCLIExecutor"),
        ):
            from src.providers.dispatcher import create_all_executors
            result = create_all_executors(config=MagicMock())
            values = list(result.values())
            for i in range(len(values)):
                for j in range(i + 1, len(values)):
                    assert values[i] is not values[j]

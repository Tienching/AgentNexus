# -*- coding: utf-8 -*-
"""Unit tests for src.providers.dispatcher — centralized provider dispatch.

Tests cover:
  - normalize_provider() name canonicalization
  - create_executor() returns correct type per provider
  - create_adapter() returns correct type per provider
  - create_all_executors() pre-creates all known providers
"""

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# normalize_provider  (pure function – no mocking needed)
# ---------------------------------------------------------------------------

class TestNormalizeProvider:
    """Test the normalize_provider() pure function."""

    def setup_method(self):
        from src.providers.dispatcher import normalize_provider
        self.normalize = normalize_provider

    def test_known_providers_returned_as_is(self):
        assert self.normalize("codex") == "codex"
        assert self.normalize("codebuddy") == "codebuddy"
        assert self.normalize("claude") == "claude"

    def test_claude_explicit(self):
        assert self.normalize("claude") == "claude"

    def test_none_defaults_to_claude(self):
        default_alias = self.normalize(None)
        assert default_alias == "claude"
        assert self.normalize("") == default_alias
        assert self.normalize("   ") == default_alias

    def test_empty_string_defaults_to_claude(self):
        assert self.normalize("") == "claude"

    def test_whitespace_defaults_to_claude(self):
        assert self.normalize("   ") == "claude"

    def test_case_insensitive(self):
        assert self.normalize("CODEX") == "codex"
        assert self.normalize("CodeBuddy") == "codebuddy"
        assert self.normalize("CLAUDE") == "claude"

    def test_leading_trailing_whitespace_stripped(self):
        assert self.normalize("\tcodex\n") == "codex"

    def test_legacy_aliases_normalize_to_nexus(self):
        assert self.normalize("nexus") == "nexus"
        assert self.normalize("nanobot") == "nexus"

    def test_unknown_provider_falls_back_to_claude(self):
        default_alias = self.normalize(None)
        assert default_alias == "claude"
        assert self.normalize("openai") == default_alias
        assert self.normalize("gpt4") == default_alias
        assert self.normalize("anthropic") == default_alias


# ---------------------------------------------------------------------------
# create_executor  (mock the actual executor classes to test dispatch logic)
# ---------------------------------------------------------------------------

class TestCreateExecutor:
    """Test create_executor() dispatches to the correct factory."""

    @patch("src.providers.dispatcher.CLIExecutor", create=True)
    def test_claude_creates_cli_executor(self, _mock_cls):
        """Claude provider returns CLIExecutor."""
        mock_config = MagicMock()
        with patch("src.server.services.cli_executor.CLIExecutor") as MockCLI:
            MockCLI.return_value = MagicMock(name="CLIExecutor_instance")
            from src.providers.dispatcher import create_executor
            result = create_executor("claude", config=mock_config)
            MockCLI.assert_called_once_with(config=mock_config)
            assert result is MockCLI.return_value

    def test_codex_creates_codex_executor(self):
        mock_config = MagicMock()
        with patch("src.providers.codex.CodexCLIExecutor") as MockCodex:
            MockCodex.return_value = MagicMock(name="CodexCLIExecutor_instance")
            from src.providers.dispatcher import create_executor
            result = create_executor("codex", config=mock_config)
            MockCodex.assert_called_once_with(config=mock_config)
            assert result is MockCodex.return_value

    def test_codebuddy_creates_codebuddy_executor(self):
        mock_config = MagicMock()
        with patch("src.providers.codebuddy.CodebuddyCLIExecutor") as MockCB:
            MockCB.return_value = MagicMock(name="CodebuddyCLIExecutor_instance")
            from src.providers.dispatcher import create_executor
            result = create_executor("codebuddy", config=mock_config)
            MockCB.assert_called_once_with(config=mock_config)
            assert result is MockCB.return_value

    def test_claude_creates_cli_executor(self):
        mock_config = MagicMock()
        from src.providers.dispatcher import create_executor
        from src.server.services.cli_executor import CLIExecutor
        result = create_executor("claude", config=mock_config)
        assert isinstance(result, CLIExecutor)

    def test_unknown_provider_falls_back_to_claude(self):
        mock_config = MagicMock()
        from src.providers.dispatcher import create_executor
        from src.server.services.cli_executor import CLIExecutor
        result = create_executor("unknown_provider", config=mock_config)
        assert isinstance(result, CLIExecutor)

    def test_none_provider_falls_back_to_claude(self):
        mock_config = MagicMock()
        from src.providers.dispatcher import create_executor
        from src.server.services.cli_executor import CLIExecutor
        result = create_executor(None, config=mock_config)
        assert isinstance(result, CLIExecutor)


# ---------------------------------------------------------------------------
# create_adapter
# ---------------------------------------------------------------------------

class TestCreateAdapter:
    """Test create_adapter() dispatches to the correct adapter factory."""

    def test_codex_creates_codex_adapter(self):
        with patch("src.runtime.adapters.codex.CodexCLIAGUIAdapter") as MockAdapter:
            MockAdapter.return_value = MagicMock(name="CodexCLIAGUIAdapter_instance")
            from src.providers.dispatcher import create_adapter
            result = create_adapter("codex")
            MockAdapter.assert_called_once()
            assert result is MockAdapter.return_value

    def test_codebuddy_creates_codebuddy_adapter(self):
        with patch("src.runtime.adapters.codebuddy.CodebuddyAGUIAdapter") as MockAdapter:
            MockAdapter.return_value = MagicMock(name="CodebuddyAGUIAdapter_instance")
            from src.providers.dispatcher import create_adapter
            result = create_adapter("codebuddy")
            MockAdapter.assert_called_once()
            assert result is MockAdapter.return_value

    def test_claude_creates_agui_adapter(self):
        with patch("src.runtime.adapters.claude.AGUIAdapter") as MockAdapter:
            MockAdapter.return_value = MagicMock(name="AGUIAdapter_instance")
            from src.providers.dispatcher import create_adapter
            result = create_adapter("claude")
            MockAdapter.assert_called_once()
            assert result is MockAdapter.return_value

    def test_claude_creates_claude_adapter(self):
        with patch("src.runtime.adapters.claude.AGUIAdapter") as MockAdapter:
            MockAdapter.return_value = MagicMock(name="AGUIAdapter_instance")
            from src.providers.dispatcher import create_adapter
            result = create_adapter("claude")
            MockAdapter.assert_called_once()
            assert result is MockAdapter.return_value

    def test_unknown_provider_uses_claude_adapter(self):
        from src.providers.dispatcher import create_adapter
        from src.runtime.adapters.claude import AGUIAdapter
        result = create_adapter("unknown")
        assert isinstance(result, AGUIAdapter)


# ---------------------------------------------------------------------------
# create_all_executors
# ---------------------------------------------------------------------------

class TestCreateAllExecutors:
    """Test create_all_executors() returns a dict with all known providers."""

    def test_returns_all_known_providers(self):
        mock_config = MagicMock()
        with (
            patch("src.server.services.cli_executor.CLIExecutor") as MockCLI,
            patch("src.providers.codex.CodexCLIExecutor") as MockCodex,
            patch("src.providers.codebuddy.CodebuddyCLIExecutor") as MockCB,
            patch("src.providers.hermes.HermesCLIExecutor") as MockHermes,
        ):
            MockCLI.return_value = MagicMock(name="CLIExecutor")
            MockCodex.return_value = MagicMock(name="CodexCLIExecutor")
            MockCB.return_value = MagicMock(name="CodebuddyCLIExecutor")
            MockHermes.return_value = MagicMock(name="HermesCLIExecutor")

            from src.providers.dispatcher import create_all_executors
            result = create_all_executors(config=mock_config)

            assert set(result.keys()) == {"claude", "codex", "codebuddy", "hermes", "nexus"}
            assert len(result) == 5

    def test_each_value_is_unique_instance(self):
        mock_config = MagicMock()
        with (
            patch("src.server.services.cli_executor.CLIExecutor"),
            patch("src.providers.codex.CodexCLIExecutor"),
            patch("src.providers.codebuddy.CodebuddyCLIExecutor"),
            patch("src.providers.hermes.HermesCLIExecutor"),
        ):
            from src.providers.dispatcher import create_all_executors
            result = create_all_executors(config=mock_config)

            canonical_values = [result[key] for key in ("claude", "codex", "codebuddy", "hermes")]
            for i in range(len(canonical_values)):
                for j in range(i + 1, len(canonical_values)):
                    assert canonical_values[i] is not canonical_values[j], (
                        "Canonical executors should be distinct instances"
                    )

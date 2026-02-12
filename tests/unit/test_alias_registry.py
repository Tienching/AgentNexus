# -*- coding: utf-8 -*-
"""AliasRegistry unit tests.

Tests:
- Built-in alias resolution
- Redis-based registration / unregistration
- Listing all aliases
- Error cases
"""

from unittest.mock import MagicMock, patch

import pytest

from src.runtime.stores.alias_registry import AliasRegistry, KNOWN_PROVIDERS


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    r = MagicMock()
    r.hget.return_value = None
    r.hgetall.return_value = {}
    r.hset.return_value = 1
    r.hdel.return_value = 1
    return r


@pytest.fixture
def registry(mock_redis):
    return AliasRegistry(redis_client=mock_redis)


class TestResolve:
    def test_builtin_claude_internal(self, registry):
        assert registry.resolve("claude-internal") == "claude"

    def test_builtin_gemini(self, registry):
        assert registry.resolve("gemini") == "gemini"

    def test_builtin_codex_internal(self, registry):
        assert registry.resolve("codex-internal") == "codex"

    def test_builtin_codebuddy(self, registry):
        assert registry.resolve("codebuddy") == "codebuddy"

    def test_unknown_alias_returns_none(self, registry):
        assert registry.resolve("nonexistent-tool") is None

    def test_empty_alias_returns_none(self, registry):
        assert registry.resolve("") is None
        assert registry.resolve(None) is None

    def test_redis_registered_overrides_builtin(self, registry, mock_redis):
        # Suppose someone re-registered "claude" -> "gemini" in Redis
        mock_redis.hget.return_value = "gemini"
        assert registry.resolve("claude") == "gemini"

    def test_redis_registered_custom_alias(self, registry, mock_redis):
        mock_redis.hget.return_value = "claude"
        assert registry.resolve("my-custom-claude") == "claude"

    def test_redis_failure_falls_back_to_builtin(self, registry, mock_redis):
        mock_redis.hget.side_effect = Exception("connection lost")
        # Should still resolve built-in
        assert registry.resolve("claude-internal") == "claude"

    def test_case_insensitive(self, registry):
        assert registry.resolve("Claude-Internal") == "claude"
        assert registry.resolve("GEMINI") == "gemini"


class TestRegister:
    def test_register_success(self, registry, mock_redis):
        assert registry.register("my-claude", "claude") is True
        mock_redis.hset.assert_called_once_with(
            AliasRegistry.REDIS_KEY, {"my-claude": "claude"}
        )

    def test_register_unknown_provider_raises(self, registry):
        with pytest.raises(ValueError, match="unknown provider"):
            registry.register("my-tool", "unknown-provider")

    def test_register_empty_alias_raises(self, registry):
        with pytest.raises(ValueError, match="alias cannot be empty"):
            registry.register("", "claude")

    def test_register_empty_provider_raises(self, registry):
        with pytest.raises(ValueError, match="provider cannot be empty"):
            registry.register("my-alias", "")

    def test_register_redis_failure_returns_false(self, registry, mock_redis):
        mock_redis.hset.side_effect = Exception("write error")
        assert registry.register("my-alias", "claude") is False


class TestUnregister:
    def test_unregister_success(self, registry, mock_redis):
        assert registry.unregister("my-custom") is True
        mock_redis.hdel.assert_called_once()

    def test_unregister_builtin_fails(self, registry):
        assert registry.unregister("claude-internal") is False

    def test_unregister_empty_returns_false(self, registry):
        assert registry.unregister("") is False

    def test_unregister_not_found(self, registry, mock_redis):
        mock_redis.hdel.return_value = 0
        assert registry.unregister("never-registered") is False


class TestListAll:
    def test_list_returns_builtins_when_redis_empty(self, registry):
        result = registry.list_all()
        assert "claude" in result
        assert "claude-internal" in result
        assert "gemini" in result
        assert result["claude-internal"] == "claude"

    def test_list_merges_redis_entries(self, registry, mock_redis):
        mock_redis.hgetall.return_value = {"my-tool": "codex"}
        result = registry.list_all()
        assert result["my-tool"] == "codex"
        assert "claude" in result  # builtins still present

    def test_list_redis_overrides_builtin(self, registry, mock_redis):
        mock_redis.hgetall.return_value = {"claude": "gemini"}
        result = registry.list_all()
        assert result["claude"] == "gemini"  # overridden

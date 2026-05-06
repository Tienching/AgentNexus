"""Tests for the identity management system."""

import pytest
from pathlib import Path
import tempfile

from src.nanobot.evolve.models import EvolutionConfig
from src.nanobot.evolve.identity import IdentityManager


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def config(tmp_dir):
    return EvolutionConfig(
        working_dir=str(tmp_dir),
        identity_file="IDENTITY.md",
        personality_file="PERSONALITY.md",
    )


@pytest.fixture
def manager(config):
    return IdentityManager(config)


class TestIdentityManager:
    def test_load_identity_missing(self, manager):
        """Should return empty string if IDENTITY.md doesn't exist."""
        result = manager.load_identity()
        assert result == ""

    def test_load_identity_present(self, manager, tmp_dir):
        """Should return content of IDENTITY.md."""
        (tmp_dir / "IDENTITY.md").write_text("I am agent-nexus.", encoding="utf-8")
        result = manager.load_identity()
        assert result == "I am agent-nexus."

    def test_load_personality_missing(self, manager):
        result = manager.load_personality()
        assert result == ""

    def test_load_personality_present(self, manager, tmp_dir):
        (tmp_dir / "PERSONALITY.md").write_text("I am precise.", encoding="utf-8")
        result = manager.load_personality()
        assert result == "I am precise."

    def test_build_context_structure(self, manager, tmp_dir):
        """Context should contain all four sections."""
        (tmp_dir / "IDENTITY.md").write_text("IDENTITY CONTENT", encoding="utf-8")
        (tmp_dir / "PERSONALITY.md").write_text("PERSONALITY CONTENT", encoding="utf-8")

        ctx = manager.build_context("LEARNINGS", "SOCIAL")

        assert "=== WHO YOU ARE ===" in ctx
        assert "IDENTITY CONTENT" in ctx
        assert "=== YOUR VOICE ===" in ctx
        assert "PERSONALITY CONTENT" in ctx
        assert "=== SELF-WISDOM ===" in ctx
        assert "LEARNINGS" in ctx
        assert "=== SOCIAL WISDOM ===" in ctx
        assert "SOCIAL" in ctx

    def test_build_context_defaults(self, manager):
        """Context with no files should still have all sections with defaults."""
        ctx = manager.build_context()
        assert "=== WHO YOU ARE ===" in ctx
        assert "=== YOUR VOICE ===" in ctx
        assert "=== SELF-WISDOM ===" in ctx
        assert "=== SOCIAL WISDOM ===" in ctx

    def test_get_protected_files(self, config):
        """Should return the configured protected files list."""
        manager = IdentityManager(config)
        protected = manager.get_protected_files()
        assert "IDENTITY.md" in protected
        assert "PERSONALITY.md" in protected

    def test_validate_changes_no_violations(self, manager):
        """Should return valid when no protected files are changed."""
        is_valid, violations = manager.validate_changes(["src/nexus/mission/types.py"])
        assert is_valid is True
        assert violations == []

    def test_validate_changes_violation(self, manager):
        """Should detect modification of protected files."""
        is_valid, violations = manager.validate_changes(["IDENTITY.md", "src/main.py"])
        assert is_valid is False
        assert "IDENTITY.md" in violations

    def test_validate_changes_multiple_violations(self, manager):
        is_valid, violations = manager.validate_changes(["IDENTITY.md", "PERSONALITY.md"])
        assert is_valid is False
        assert len(violations) == 2

"""Tests for the memory management system."""

import json
import pytest
import time
from pathlib import Path
import tempfile

from src.nanobot.evolve.models import EvolutionConfig, Lesson, SocialInsight
from src.nanobot.evolve.memory import MemoryManager


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def config(tmp_dir):
    return EvolutionConfig(
        working_dir=str(tmp_dir),
        memory_path=str(tmp_dir / "memory"),
    )


@pytest.fixture
def manager(config):
    return MemoryManager(config)


class TestMemoryManager:
    def test_init_creates_memory_dir(self, manager, tmp_dir):
        assert (tmp_dir / "memory").exists()

    def test_append_learning(self, manager):
        lesson = Lesson(
            day=1,
            source="evolution",
            title="Test lesson",
            context="Context here",
            takeaway="Important insight",
        )
        manager.append_learning(lesson)
        records = manager.load_archive(manager.learnings_archive)
        assert len(records) == 1
        assert records[0]["title"] == "Test lesson"
        assert records[0]["takeaway"] == "Important insight"
        assert records[0]["source"] == "evolution"
        assert records[0]["day"] == 1

    def test_append_multiple_learnings(self, manager):
        for i in range(3):
            manager.append_learning(Lesson(day=i, title=f"Lesson {i}", takeaway=f"Insight {i}"))
        records = manager.load_archive(manager.learnings_archive)
        assert len(records) == 3

    def test_append_social_learning(self, manager):
        insight = SocialInsight(
            day=2,
            source="discussion #5",
            who="@testuser",
            insight="Users prefer clear error messages.",
        )
        manager.append_social_learning(insight)
        records = manager.load_archive(manager.social_learnings_archive)
        assert len(records) == 1
        assert records[0]["who"] == "@testuser"
        assert records[0]["insight"] == "Users prefer clear error messages."

    def test_load_archive_empty(self, manager):
        records = manager.load_archive(manager.learnings_archive)
        assert records == []

    def test_load_archive_nonexistent(self, manager, tmp_dir):
        nonexistent = tmp_dir / "nonexistent.jsonl"
        records = manager.load_archive(nonexistent)
        assert records == []

    def test_load_active_learnings_empty(self, manager):
        result = manager.load_active_learnings()
        assert result == ""

    def test_load_active_learnings_present(self, manager):
        manager.active_learnings_path.write_text("# Active Learnings\n\nSome learning.", encoding="utf-8")
        result = manager.load_active_learnings()
        assert "Active Learnings" in result

    def test_atomic_write(self, manager, tmp_dir):
        target = tmp_dir / "test_atomic.txt"
        MemoryManager._atomic_write(target, "atomic content")
        assert target.read_text() == "atomic content"

    def test_archive_stats_empty(self, manager):
        stats = manager.get_archive_stats()
        assert stats["learnings_count"] == 0
        assert stats["social_learnings_count"] == 0
        assert stats["active_learnings_exists"] is False

    def test_archive_stats_with_data(self, manager):
        manager.append_learning(Lesson(day=1, title="A", takeaway="B"))
        manager.append_learning(Lesson(day=2, title="C", takeaway="D"))
        stats = manager.get_archive_stats()
        assert stats["learnings_count"] == 2

    def test_synthesize_empty(self, manager):
        """Synthesis with no data should create placeholder files."""
        manager.synthesize()
        active = manager.load_active_learnings()
        assert "No learnings yet" in active
        social = manager.load_active_social_learnings()
        assert "No social learnings" in social

    def test_synthesize_with_recent_learning(self, manager):
        """Recent learnings should appear in full in active context."""
        lesson = Lesson(
            day=1,
            source="evolution",
            title="Recent lesson",
            context="Context for recent",
            takeaway="Important recent insight",
        )
        manager.append_learning(lesson)
        manager.synthesize()
        active = manager.load_active_learnings()
        assert "Recent lesson" in active
        assert "Important recent insight" in active

    def test_synthesize_idempotent(self, manager):
        """Running synthesis twice should not corrupt data."""
        manager.append_learning(Lesson(day=1, title="Lesson", takeaway="Insight"))
        manager.synthesize()
        first = manager.load_active_learnings()
        manager.synthesize()
        second = manager.load_active_learnings()
        assert first == second

    def test_parse_timestamp_valid(self):
        ts = "2026-01-01T12:00:00Z"
        result = MemoryManager._parse_timestamp(ts)
        assert result > 0

    def test_parse_timestamp_invalid(self):
        result = MemoryManager._parse_timestamp("not-a-timestamp")
        assert result == 0.0

    def test_parse_timestamp_empty(self):
        result = MemoryManager._parse_timestamp("")
        assert result == 0.0

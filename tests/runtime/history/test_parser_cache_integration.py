# -*- coding: utf-8 -*-
"""End-to-end tests for parser cache integration.

These tests build tiny fake history trees on disk, then assert that:
  1. The first list_sessions call parses every file (miss)
  2. The second call hits cache for unchanged files (no re-parse)
  3. Mutating one file only re-parses that file
  4. Output is identical to a fresh (cache-less) run
"""
import json
import os
import time
from pathlib import Path

import pytest

from src.runtime.history.cache_store import CacheStore
from src.runtime.history.claude_parser import ClaudeHistoryParser
from src.runtime.history.codebuddy_parser import CodeBuddyHistoryParser
from src.runtime.history.codex_parser import CodexHistoryParser
from src.runtime.history.gemini_parser import GeminiHistoryParser


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch):
    """Give every test its own CacheStore file so tests don't leak into
    the user's real ~/.nexus/history_cache.sqlite."""
    db_path = tmp_path / "_cache" / "h.sqlite"
    monkeypatch.setenv("NEXUS_HISTORY_CACHE_PATH", str(db_path))
    CacheStore.reset_default()
    yield
    CacheStore.reset_default()


# ----------------------------------------------------------------------
#  Claude / CodeBuddy — shared helpers
# ----------------------------------------------------------------------

def _write_jsonl(path: Path, entries: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _claude_entry(session_id: str, role: str, text: str, ts: str) -> dict:
    return {
        "sessionId": session_id,
        "type": "user" if role == "user" else "assistant",
        "timestamp": ts,
        "message": {"role": role, "content": text},
    }


def _codebuddy_entry(session_id: str, role: str, text: str, ts: str) -> dict:
    return {
        "sessionId": session_id,
        "type": "message",
        "role": role,
        "timestamp": ts,
        "content": text,
    }


# ----------------------------------------------------------------------
#  Claude
# ----------------------------------------------------------------------

class TestClaudeCache:
    def _setup(self, tmp_path: Path) -> tuple[Path, str]:
        config = tmp_path / ".claude"
        # Claude project dir encoding: /home/test/proj -> -home-test-proj
        proj = config / "projects" / "-home-test-proj"
        proj.mkdir(parents=True)
        # Two files, two sessions
        _write_jsonl(proj / "s1.jsonl", [
            _claude_entry("sess-a", "user", "hello from A", "2026-04-22T10:00:00Z"),
            _claude_entry("sess-a", "assistant", "hi A!", "2026-04-22T10:00:01Z"),
        ])
        _write_jsonl(proj / "s2.jsonl", [
            _claude_entry("sess-b", "user", "hello from B", "2026-04-22T11:00:00Z"),
        ])
        return config, "/home/test/proj"

    def test_first_call_parses_all_files(self, tmp_path, monkeypatch):
        parser = ClaudeHistoryParser()
        config, project_path = self._setup(tmp_path)

        parse_counter = {"n": 0}
        real_parse = parser._parse_file_to_shards

        def counting_parse(f):
            parse_counter["n"] += 1
            return real_parse(f)

        monkeypatch.setattr(parser, "_parse_file_to_shards", counting_parse)

        sessions = parser.list_sessions(config, project_path)
        assert parse_counter["n"] == 2
        ids = sorted(s.id for s in sessions)
        assert ids == ["sess-a", "sess-b"]

    def test_second_call_is_full_cache_hit(self, tmp_path, monkeypatch):
        parser = ClaudeHistoryParser()
        config, project_path = self._setup(tmp_path)

        # Warm the cache
        first = parser.list_sessions(config, project_path)
        assert len(first) == 2

        parse_counter = {"n": 0}
        real_parse = parser._parse_file_to_shards
        monkeypatch.setattr(
            parser, "_parse_file_to_shards",
            lambda f: (parse_counter.__setitem__("n", parse_counter["n"] + 1) or real_parse(f)),
        )

        second = parser.list_sessions(config, project_path)
        assert parse_counter["n"] == 0, "cache should have absorbed every file"
        assert sorted(s.id for s in second) == sorted(s.id for s in first)
        assert {s.message_count for s in second} == {s.message_count for s in first}

    def test_mtime_change_reparses_only_dirty_file(self, tmp_path, monkeypatch):
        parser = ClaudeHistoryParser()
        config, project_path = self._setup(tmp_path)

        # Warm
        parser.list_sessions(config, project_path)

        # Touch s1 only — add one more message
        proj = config / "projects" / "-home-test-proj"
        _write_jsonl(proj / "s1.jsonl", [
            _claude_entry("sess-a", "user", "hello from A", "2026-04-22T10:00:00Z"),
            _claude_entry("sess-a", "assistant", "hi A!", "2026-04-22T10:00:01Z"),
            _claude_entry("sess-a", "user", "follow-up", "2026-04-22T12:00:00Z"),
        ])

        parse_counter = {"n": 0, "paths": []}
        real_parse = parser._parse_file_to_shards

        def counting_parse(f):
            parse_counter["n"] += 1
            parse_counter["paths"].append(str(f))
            return real_parse(f)

        monkeypatch.setattr(parser, "_parse_file_to_shards", counting_parse)

        sessions = parser.list_sessions(config, project_path)
        assert parse_counter["n"] == 1, "only the modified file should re-parse"
        assert parse_counter["paths"][0].endswith("s1.jsonl")
        sess_a = next(s for s in sessions if s.id == "sess-a")
        assert sess_a.message_count == 3  # 2 before + 1 new

    def test_cache_result_matches_fresh_parse(self, tmp_path):
        """Parity check: after a cache round-trip, the aggregated output
        must equal what a cold parser run produces."""
        parser = ClaudeHistoryParser()
        config, project_path = self._setup(tmp_path)

        warm = parser.list_sessions(config, project_path)
        # Nuke the cache DB and re-run with a fresh parser
        CacheStore.get_default().clear()
        fresh = parser.list_sessions(config, project_path)

        def _key(s):
            return (s.id, s.message_count, s.title, s.updated_at)

        assert sorted(map(_key, warm)) == sorted(map(_key, fresh))


# ----------------------------------------------------------------------
#  CodeBuddy  (same shape as Claude but dash-encoded differently)
# ----------------------------------------------------------------------

class TestCodeBuddyCache:
    def _setup(self, tmp_path: Path) -> tuple[Path, str]:
        config = tmp_path / ".codebuddy"
        proj = config / "projects" / "home-test-proj"  # no leading dash
        proj.mkdir(parents=True)
        _write_jsonl(proj / "f1.jsonl", [
            {"sessionId": "cb-1", "type": "topic", "topic": "first", "timestamp": "2026-04-22T10:00:00Z"},
            _codebuddy_entry("cb-1", "user", "hi", "2026-04-22T10:00:01Z"),
            _codebuddy_entry("cb-1", "assistant", "yo", "2026-04-22T10:00:02Z"),
        ])
        _write_jsonl(proj / "f2.jsonl", [
            _codebuddy_entry("cb-1", "user", "part two", "2026-04-22T11:00:00Z"),
        ])
        return config, "/home/test/proj"

    def test_cross_file_session_aggregation(self, tmp_path):
        """Same sessionId in two files must merge to one session with
        summed message_count."""
        parser = CodeBuddyHistoryParser()
        config, project_path = self._setup(tmp_path)

        sessions = parser.list_sessions(config, project_path)
        assert len(sessions) == 1
        assert sessions[0].id == "cb-1"
        # 1 user + 1 assistant in f1, 1 user in f2 → 3
        assert sessions[0].message_count == 3
        assert sessions[0].title == "first"  # topic wins over message fallback

    def test_second_call_is_cache_hit(self, tmp_path, monkeypatch):
        parser = CodeBuddyHistoryParser()
        config, project_path = self._setup(tmp_path)

        parser.list_sessions(config, project_path)  # warm

        parse_counter = {"n": 0}
        real_parse = parser._parse_file_to_shards
        monkeypatch.setattr(
            parser, "_parse_file_to_shards",
            lambda f: (parse_counter.__setitem__("n", parse_counter["n"] + 1) or real_parse(f)),
        )

        sessions = parser.list_sessions(config, project_path)
        assert parse_counter["n"] == 0
        assert sessions[0].message_count == 3

    def test_partial_file_change_updates_aggregate(self, tmp_path):
        """Appending a message to one of the two files must still give
        correct totals after cache hit on the unchanged file."""
        parser = CodeBuddyHistoryParser()
        config, project_path = self._setup(tmp_path)

        parser.list_sessions(config, project_path)  # warm

        # Add a new user msg to f2 only
        proj = config / "projects" / "home-test-proj"
        _write_jsonl(proj / "f2.jsonl", [
            _codebuddy_entry("cb-1", "user", "part two", "2026-04-22T11:00:00Z"),
            _codebuddy_entry("cb-1", "user", "part three", "2026-04-22T12:00:00Z"),
        ])

        sessions = parser.list_sessions(config, project_path)
        # 1 + 1 (f1) + 2 (f2) = 4
        assert sessions[0].message_count == 4


# ----------------------------------------------------------------------
#  Codex  (1 file == 1 session)
# ----------------------------------------------------------------------

class TestCodexCache:
    def _setup(self, tmp_path: Path) -> tuple[Path, str]:
        config = tmp_path / ".codex"
        sessions = config / "sessions"
        sessions.mkdir(parents=True)
        project = "/home/test/proj"
        _write_jsonl(sessions / "a.jsonl", [
            {
                "type": "session_meta",
                "timestamp": "2026-04-22T10:00:00Z",
                "payload": {"id": "cx-1", "cwd": project, "model": "gpt-5"},
            },
            {
                "type": "event_msg",
                "timestamp": "2026-04-22T10:00:01Z",
                "payload": {"type": "user_message", "message": "hello"},
            },
        ])
        _write_jsonl(sessions / "b.jsonl", [
            {
                "type": "session_meta",
                "timestamp": "2026-04-22T11:00:00Z",
                "payload": {"id": "cx-2", "cwd": "/other/proj", "model": "gpt-5"},
            },
            {
                "type": "event_msg",
                "timestamp": "2026-04-22T11:00:01Z",
                "payload": {"type": "user_message", "message": "hi"},
            },
        ])
        return config, project

    def test_project_filter_keeps_cache_hot(self, tmp_path, monkeypatch):
        """list_sessions filters by cwd *after* cache lookup, so calling
        it for a new project still hits cache for files seen by
        list_all_sessions."""
        parser = CodexHistoryParser()
        config, project_path = self._setup(tmp_path)

        # Prime the cache via list_all_sessions (sees both files)
        all_sessions = parser.list_all_sessions(config)
        assert len(all_sessions) == 2

        parse_counter = {"n": 0}
        real = parser._parse_session_meta_unfiltered
        monkeypatch.setattr(
            parser, "_parse_session_meta_unfiltered",
            lambda f: (parse_counter.__setitem__("n", parse_counter["n"] + 1) or real(f)),
        )

        # Now list for one specific project — should hit cache on both
        filtered = parser.list_sessions(config, project_path)
        assert parse_counter["n"] == 0
        assert [s.id for s in filtered] == ["cx-1"]

    def test_file_change_invalidates_that_row(self, tmp_path, monkeypatch):
        parser = CodexHistoryParser()
        config, project_path = self._setup(tmp_path)

        parser.list_all_sessions(config)  # warm

        # Append an extra user message to a.jsonl
        target = config / "sessions" / "a.jsonl"
        extra = json.dumps({
            "type": "event_msg",
            "timestamp": "2026-04-22T12:00:00Z",
            "payload": {"type": "user_message", "message": "follow-up"},
        }, ensure_ascii=False) + "\n"
        with target.open("a", encoding="utf-8") as f:
            f.write(extra)

        parse_counter = {"n": 0, "paths": []}
        real = parser._parse_session_meta_unfiltered

        def counting(f):
            parse_counter["n"] += 1
            parse_counter["paths"].append(str(f))
            return real(f)

        monkeypatch.setattr(parser, "_parse_session_meta_unfiltered", counting)

        sessions = parser.list_all_sessions(config)
        assert parse_counter["n"] == 1
        assert parse_counter["paths"][0].endswith("a.jsonl")
        cx1 = next(s for s in sessions if s.id == "cx-1")
        assert cx1.message_count == 2


# ----------------------------------------------------------------------
#  Gemini  (1 JSON file == 1 session)
# ----------------------------------------------------------------------

class TestGeminiCache:
    def _setup(self, tmp_path: Path) -> tuple[Path, str]:
        import hashlib
        config = tmp_path / ".gemini"
        project = "/home/test/proj"
        project_hash = hashlib.sha256(project.encode()).hexdigest()
        chats = config / "tmp" / project_hash / "chats"
        chats.mkdir(parents=True)

        (chats / "session-2026-04-22T10-00-gem-1.json").write_text(json.dumps({
            "sessionId": "gem-1",
            "startTime": "2026-04-22T10:00:00Z",
            "lastUpdated": "2026-04-22T10:05:00Z",
            "messages": [
                {"type": "user", "content": "hello", "timestamp": "2026-04-22T10:00:00Z"},
                {"type": "gemini", "content": "hi there", "timestamp": "2026-04-22T10:00:01Z"},
            ],
        }), encoding="utf-8")
        return config, project

    def test_list_sessions_warms_then_hits_cache(self, tmp_path, monkeypatch):
        parser = GeminiHistoryParser()
        config, project_path = self._setup(tmp_path)

        first = parser.list_sessions(config, project_path)
        assert len(first) == 1
        assert first[0].id == "gem-1"
        assert first[0].message_count == 2

        parse_counter = {"n": 0}
        real = parser._parse_file_to_meta
        monkeypatch.setattr(
            parser, "_parse_file_to_meta",
            lambda f: (parse_counter.__setitem__("n", parse_counter["n"] + 1) or real(f)),
        )

        second = parser.list_sessions(config, project_path)
        assert parse_counter["n"] == 0
        assert second[0].id == "gem-1"

    def test_list_all_sessions_injects_exec_dir(self, tmp_path):
        """Shard has no exec_dir; list_all_sessions must add the hash tag."""
        parser = GeminiHistoryParser()
        config, _ = self._setup(tmp_path)

        # Warm the cache via list_sessions (hash-scoped)
        parser.list_sessions(config, "/home/test/proj")
        # Now list_all_sessions must still produce the hash tag, even
        # though shards are cached without exec_dir
        all_s = parser.list_all_sessions(config)
        assert len(all_s) == 1
        assert all_s[0].exec_dir is not None
        assert all_s[0].exec_dir.startswith("[gemini:")

# -*- coding: utf-8 -*-
"""Unit tests for the history cache_store module.

Covers:
  * Basic insert / lookup roundtrip
  * Stale detection on mtime change
  * Stale detection on size change
  * Prune-missing removes absent paths and keeps extant ones
  * Roundtrip preserves all SessionMeta fields
  * Singleton (get_default) honours env var
"""
import os
import time
from pathlib import Path

import pytest

from src.core.models.session import SessionMeta, SessionStatus
from src.runtime.history.cache_store import (
    CacheStore,
    FileStamp,
    shards_from_json,
    shards_to_json,
    stat_paths,
)


# --------- helpers ---------

def _touch(path: Path, content: bytes = b"", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _sample_meta(i: int) -> SessionMeta:
    return SessionMeta(
        id=f"sess-{i}",
        thread_id=f"sess-{i}",
        title=f"hello {i}",
        username="alice",
        provider="claude",
        status=SessionStatus.COMPLETED,
        created_at=1_700_000_000_000 + i,
        updated_at=1_700_000_000_000 + i + 100,
        message_count=i * 3,
        source="history",
    )


@pytest.fixture
def cache(tmp_path: Path) -> CacheStore:
    db = tmp_path / "history_cache.sqlite"
    return CacheStore(db_path=db)


# --------- shard serialisation ---------

def test_shard_roundtrip_preserves_fields():
    meta = _sample_meta(1)
    payload = shards_to_json([meta])
    restored = shards_from_json(payload)
    assert len(restored) == 1
    r = restored[0]
    assert r.id == meta.id
    assert r.title == meta.title
    assert r.message_count == meta.message_count
    assert r.updated_at == meta.updated_at
    assert r.provider == meta.provider


def test_shard_from_json_tolerates_junk():
    assert shards_from_json("not-json") == []
    assert shards_from_json("[1, 2, 3]") == []  # non-dict entries skipped


# --------- FileStamp ---------

def test_filestamp_from_path_missing(tmp_path: Path):
    missing = tmp_path / "nope.jsonl"
    assert FileStamp.from_path(missing) is None


def test_filestamp_equality(tmp_path: Path):
    f = _touch(tmp_path / "a.jsonl", b"hello")
    s1 = FileStamp.from_path(f)
    s2 = FileStamp.from_path(f)
    assert s1 == s2


def test_stat_paths_drops_missing(tmp_path: Path):
    real = _touch(tmp_path / "a.jsonl", b"hi")
    ghost = tmp_path / "b.jsonl"
    stamps = stat_paths([real, ghost])
    assert real in stamps
    assert ghost not in stamps


# --------- CacheStore core ---------

def test_lookup_returns_nothing_when_empty(cache: CacheStore, tmp_path: Path):
    f = _touch(tmp_path / "a.jsonl", b"x")
    stamps = stat_paths([f])
    assert cache.lookup_many("claude", stamps) == {}


def test_store_then_lookup_hits(cache: CacheStore, tmp_path: Path):
    f = _touch(tmp_path / "a.jsonl", b"x")
    stamps = stat_paths([f])
    cache.store_many("claude", [(f, stamps[f], [_sample_meta(1)])])

    got = cache.lookup_many("claude", stamps)
    assert f in got
    assert len(got[f]) == 1
    assert got[f][0].id == "sess-1"


def test_lookup_misses_on_mtime_change(cache: CacheStore, tmp_path: Path):
    f = _touch(tmp_path / "a.jsonl", b"x", mtime=1_700_000_000)
    stamps = stat_paths([f])
    cache.store_many("claude", [(f, stamps[f], [_sample_meta(1)])])

    # Bump mtime only — size is identical
    os.utime(f, (1_700_000_500, 1_700_000_500))
    new_stamps = stat_paths([f])
    assert new_stamps[f].mtime_ns != stamps[f].mtime_ns

    got = cache.lookup_many("claude", new_stamps)
    assert got == {}  # cache entry is stale → miss


def test_lookup_misses_on_size_change(cache: CacheStore, tmp_path: Path):
    f = _touch(tmp_path / "a.jsonl", b"x" * 10, mtime=1_700_000_000)
    stamps = stat_paths([f])
    cache.store_many("claude", [(f, stamps[f], [_sample_meta(2)])])

    # Grow the file then force mtime back to the same value → size alone triggers miss
    _touch(f, b"x" * 20, mtime=1_700_000_000)
    new_stamps = stat_paths([f])
    assert new_stamps[f].size != stamps[f].size

    got = cache.lookup_many("claude", new_stamps)
    assert got == {}


def test_store_replace_overwrites_previous(cache: CacheStore, tmp_path: Path):
    f = _touch(tmp_path / "a.jsonl", b"x")
    stamps = stat_paths([f])
    cache.store_many("claude", [(f, stamps[f], [_sample_meta(1)])])
    # Rewrite with different content — use a new file stamp
    _touch(f, b"yy", mtime=time.time() + 10)
    stamps2 = stat_paths([f])
    cache.store_many("claude", [(f, stamps2[f], [_sample_meta(2), _sample_meta(3)])])

    got = cache.lookup_many("claude", stamps2)
    assert [s.id for s in got[f]] == ["sess-2", "sess-3"]
    # Old stamp no longer hits
    assert cache.lookup_many("claude", stamps) == {}


def test_provider_isolation(cache: CacheStore, tmp_path: Path):
    f = _touch(tmp_path / "a.jsonl", b"x")
    stamps = stat_paths([f])
    cache.store_many("claude", [(f, stamps[f], [_sample_meta(1)])])
    # Same path under a different provider — should not see claude's data
    assert cache.lookup_many("codex", stamps) == {}
    assert cache.lookup_many("claude", stamps) != {}


def test_prune_missing_removes_absent_only(cache: CacheStore, tmp_path: Path):
    f1 = _touch(tmp_path / "a.jsonl", b"1")
    f2 = _touch(tmp_path / "b.jsonl", b"2")
    stamps = stat_paths([f1, f2])
    cache.store_many(
        "claude",
        [
            (f1, stamps[f1], [_sample_meta(1)]),
            (f2, stamps[f2], [_sample_meta(2)]),
        ],
    )

    # Drop f2 from the filesystem; prune should reap only its row
    f2.unlink()
    removed = cache.prune_missing("claude", live_paths=[f1])
    assert removed == 1
    assert cache.count("claude") == 1
    assert cache.lookup_many("claude", {f1: stamps[f1]}) != {}


def test_prune_missing_empty_live_wipes_provider(cache: CacheStore, tmp_path: Path):
    f1 = _touch(tmp_path / "a.jsonl", b"1")
    stamps = stat_paths([f1])
    cache.store_many("claude", [(f1, stamps[f1], [_sample_meta(1)])])
    assert cache.prune_missing("claude", live_paths=[]) == 1
    assert cache.count("claude") == 0


def test_clear_provider(cache: CacheStore, tmp_path: Path):
    f = _touch(tmp_path / "a.jsonl", b"x")
    stamps = stat_paths([f])
    cache.store_many("claude", [(f, stamps[f], [_sample_meta(1)])])
    cache.store_many("codex", [(f, stamps[f], [_sample_meta(2)])])
    assert cache.count() == 2
    assert cache.clear("claude") == 1
    assert cache.count() == 1
    assert cache.count("codex") == 1


def test_empty_shard_roundtrip(cache: CacheStore, tmp_path: Path):
    """Files that parse to zero sessions still cache — important so we
    don't re-read them every time."""
    f = _touch(tmp_path / "empty.jsonl", b"")
    stamps = stat_paths([f])
    cache.store_many("claude", [(f, stamps[f], [])])
    got = cache.lookup_many("claude", stamps)
    assert f in got
    assert got[f] == []


# --------- singleton / env ---------

def test_get_default_honours_env(tmp_path: Path, monkeypatch):
    """The process-global default CacheStore must pick up
    NEXUS_HISTORY_CACHE_PATH when the singleton is reset."""
    custom = tmp_path / "custom" / "h.sqlite"
    monkeypatch.setenv("NEXUS_HISTORY_CACHE_PATH", str(custom))
    CacheStore.reset_default()
    try:
        store = CacheStore.get_default()
        assert store._db_path == custom
        assert custom.exists()
    finally:
        CacheStore.reset_default()

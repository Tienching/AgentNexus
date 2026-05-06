# -*- coding: utf-8 -*-
"""Persistent file-level cache for history parsers.

Design goal: make the second-and-later run of
``HistoryService.list_all_sessions`` ≈ O(files) instead of O(bytes).

Each JSONL / JSON file is treated as an opaque unit. The cache stores the
*already-parsed* ``SessionMeta`` shards produced from that single file,
keyed by ``(provider, file_path)`` and versioned by ``(mtime_ns, size)``.

When a parser scans a directory:
  1. stat every candidate file (cheap)
  2. ``CacheStore.lookup_many`` returns a dict of {path: shards} for
     paths whose (mtime_ns, size) still match
  3. the parser only re-reads the files that were *missing* or *stale*
  4. new shards are written back via ``CacheStore.store_many``
  5. files that no longer exist are evicted via ``CacheStore.prune_missing``

A "shard" is the list of SessionMeta objects derived from one file.
For providers where a single sessionId can span multiple files
(Claude / CodeBuddy), the parser is responsible for merging shards
across files at the aggregation step; each shard still contains only
the contribution from its own file.

SQLite uses WAL journalling by default so that multiple readers and a
single writer can coexist without blocking. The journal mode can be
overridden via ``NEXUS_SQLITE_JOURNAL_MODE`` for filesystems that do not
support WAL well. The database is safe to delete at any time — worst
case is one full cold re-scan.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..models.session import SessionMeta

logger = logging.getLogger(__name__)
_ALLOWED_JOURNAL_MODES = {"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"}


# -------- schema --------

_SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_shards (
    provider    TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    mtime_ns    INTEGER NOT NULL,
    size        INTEGER NOT NULL,
    shard_json  TEXT NOT NULL,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (provider, file_path)
);

CREATE INDEX IF NOT EXISTS idx_file_shards_provider
    ON file_shards (provider);
"""


def _default_cache_path() -> Path:
    """Resolve the default SQLite file location.

    Order of precedence:
      1. ``NEXUS_HISTORY_CACHE_PATH`` env var (absolute path, tests use this)
      2. ``~/.nexus/history_cache.sqlite``
    """
    override = os.environ.get("NEXUS_HISTORY_CACHE_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".nexus" / "history_cache.sqlite"


def _journal_mode() -> str:
    mode = os.environ.get("NEXUS_SQLITE_JOURNAL_MODE", "WAL").strip().upper()
    if mode in _ALLOWED_JOURNAL_MODES:
        return mode
    logger.warning("Invalid NEXUS_SQLITE_JOURNAL_MODE=%r, using WAL", mode)
    return "WAL"


# -------- shard (de)serialisation --------

def _session_to_dict(s: SessionMeta) -> dict:
    """Dump a SessionMeta to a JSON-safe dict using pydantic's model_dump.

    We deliberately rely on model_dump so that future field additions
    Just Work without schema migrations — the dict is stored verbatim
    and rehydrated via model_validate, so unknown fields are tolerated
    and missing fields fall back to their model defaults.
    """
    if hasattr(s, "model_dump"):
        return s.model_dump(mode="json")
    # Pydantic v1 fallback (shouldn't trigger in this codebase, but safe)
    return s.dict()


def _dict_to_session(data: dict) -> SessionMeta:
    if hasattr(SessionMeta, "model_validate"):
        return SessionMeta.model_validate(data)
    return SessionMeta.parse_obj(data)


def shards_to_json(shards: List[SessionMeta]) -> str:
    return json.dumps([_session_to_dict(s) for s in shards], ensure_ascii=False)


def shards_from_json(payload: str) -> List[SessionMeta]:
    try:
        raw = json.loads(payload)
    except (TypeError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    out: List[SessionMeta] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            out.append(_dict_to_session(item))
        except Exception:  # pragma: no cover — defensive; skip corrupt rows
            logger.debug("cache_store: skipping malformed shard entry", exc_info=True)
    return out


# -------- FileStamp --------

class FileStamp:
    """Cheap filesystem fingerprint used as the cache-validity key."""
    __slots__ = ("mtime_ns", "size")

    def __init__(self, mtime_ns: int, size: int):
        self.mtime_ns = int(mtime_ns)
        self.size = int(size)

    @classmethod
    def from_path(cls, path: Path) -> Optional["FileStamp"]:
        try:
            st = path.stat()
        except OSError:
            return None
        return cls(mtime_ns=st.st_mtime_ns, size=st.st_size)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, FileStamp)
            and self.mtime_ns == other.mtime_ns
            and self.size == other.size
        )

    def __repr__(self) -> str:  # pragma: no cover
        return f"FileStamp(mtime_ns={self.mtime_ns}, size={self.size})"


# -------- CacheStore --------

class CacheStore:
    """Thread-safe persistent cache keyed by (provider, file_path).

    Safety notes:
      * configurable SQLite journalling; WAL is the default
      * Every read/write goes through a private lock so a single
        ``CacheStore`` instance is safe across asyncio workers that
        use ``asyncio.to_thread``
      * On schema-version mismatch we drop the cache table and rebuild,
        which is safe because it's purely derived data
    """

    _DEFAULT_INSTANCE: Optional["CacheStore"] = None
    _DEFAULT_LOCK = threading.Lock()

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = Path(db_path) if db_path else _default_cache_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    # ---- classmethod / factory ----

    @classmethod
    def get_default(cls) -> "CacheStore":
        """Process-wide default instance. Re-resolves path each time a
        fresh singleton is missing so unit tests can swap
        ``NEXUS_HISTORY_CACHE_PATH`` via ``reset_default``."""
        with cls._DEFAULT_LOCK:
            if cls._DEFAULT_INSTANCE is None:
                cls._DEFAULT_INSTANCE = cls()
            return cls._DEFAULT_INSTANCE

    @classmethod
    def reset_default(cls) -> None:
        """Drop the cached singleton (tests only)."""
        with cls._DEFAULT_LOCK:
            if cls._DEFAULT_INSTANCE is not None:
                try:
                    cls._DEFAULT_INSTANCE.close()
                except Exception:  # pragma: no cover
                    pass
            cls._DEFAULT_INSTANCE = None

    # ---- lifecycle ----

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)
            conn.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES(?, ?)",
                ("version", str(_SCHEMA_VERSION)),
            )
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'version'"
            ).fetchone()
            current = int(row[0]) if row and str(row[0]).isdigit() else _SCHEMA_VERSION
            if current != _SCHEMA_VERSION:
                # Future-proofing: nuke and rebuild. Cache is purely derived.
                logger.info(
                    "history cache schema %s != expected %s — resetting",
                    current, _SCHEMA_VERSION,
                )
                conn.executescript(
                    "DROP TABLE IF EXISTS file_shards;"
                    "DROP TABLE IF EXISTS schema_meta;"
                )
                conn.executescript(_SCHEMA_SQL)
                conn.execute(
                    "INSERT OR REPLACE INTO schema_meta(key, value) VALUES(?, ?)",
                    ("version", str(_SCHEMA_VERSION)),
                )

    @contextmanager
    def _connect(self):
        """Yield a short-lived sqlite3 connection."""
        conn = sqlite3.connect(
            str(self._db_path),
            timeout=5.0,
            isolation_level=None,  # autocommit; we manage txns explicitly
            check_same_thread=False,
        )
        try:
            conn.execute(f"PRAGMA journal_mode={_journal_mode()}")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
        finally:
            try:
                conn.close()
            except Exception:  # pragma: no cover
                pass

    def close(self) -> None:
        # Connections are per-operation; nothing persistent to close.
        pass

    # ---- core API ----

    def lookup_many(
        self,
        provider: str,
        paths_with_stamps: Dict[Path, FileStamp],
    ) -> Dict[Path, List[SessionMeta]]:
        """Return cached shards for any path whose stamp still matches.

        Missing or stale paths are simply omitted from the result. The
        caller is expected to re-parse them and call ``store_many``.
        """
        if not paths_with_stamps:
            return {}

        path_strs = [str(p) for p in paths_with_stamps.keys()]

        # sqlite has a 999-param default limit; chunk to be safe.
        CHUNK = 500
        hits: Dict[str, Tuple[int, int, str]] = {}
        with self._lock, self._connect() as conn:
            for i in range(0, len(path_strs), CHUNK):
                batch = path_strs[i : i + CHUNK]
                placeholders = ",".join("?" * len(batch))
                rows = conn.execute(
                    f"SELECT file_path, mtime_ns, size, shard_json "
                    f"FROM file_shards "
                    f"WHERE provider = ? AND file_path IN ({placeholders})",
                    [provider, *batch],
                ).fetchall()
                for fp, mns, sz, payload in rows:
                    hits[fp] = (int(mns), int(sz), payload)

        result: Dict[Path, List[SessionMeta]] = {}
        for path, stamp in paths_with_stamps.items():
            row = hits.get(str(path))
            if not row:
                continue
            cached_mtime_ns, cached_size, payload = row
            if cached_mtime_ns == stamp.mtime_ns and cached_size == stamp.size:
                result[path] = shards_from_json(payload)
        return result

    def store_many(
        self,
        provider: str,
        entries: Iterable[Tuple[Path, FileStamp, List[SessionMeta]]],
    ) -> int:
        """Persist fresh shard lists. Returns the number of rows written."""
        rows = []
        import time as _time
        now_s = int(_time.time())
        for path, stamp, shards in entries:
            rows.append(
                (
                    provider,
                    str(path),
                    int(stamp.mtime_ns),
                    int(stamp.size),
                    shards_to_json(list(shards or [])),
                    now_s,
                )
            )
        if not rows:
            return 0

        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.executemany(
                    "INSERT OR REPLACE INTO file_shards "
                    "(provider, file_path, mtime_ns, size, shard_json, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    rows,
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return len(rows)

    def prune_missing(self, provider: str, live_paths: Iterable[Path]) -> int:
        """Delete cache rows for this provider whose file_path is not in live_paths.

        Call this *only* after a full directory scan where ``live_paths``
        is authoritative — otherwise you'll evict valid entries from
        directories you didn't touch this round.
        """
        live_set = {str(p) for p in live_paths}
        with self._lock, self._connect() as conn:
            existing = {
                r[0] for r in conn.execute(
                    "SELECT file_path FROM file_shards WHERE provider = ?",
                    (provider,),
                ).fetchall()
            }
            dead = existing - live_set
            if not dead:
                return 0
            CHUNK = 500
            conn.execute("BEGIN IMMEDIATE")
            try:
                dead_list = list(dead)
                for i in range(0, len(dead_list), CHUNK):
                    batch = dead_list[i : i + CHUNK]
                    placeholders = ",".join("?" * len(batch))
                    conn.execute(
                        f"DELETE FROM file_shards "
                        f"WHERE provider = ? AND file_path IN ({placeholders})",
                        [provider, *batch],
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            return len(dead)

    # ---- diagnostics ----

    def count(self, provider: Optional[str] = None) -> int:
        with self._lock, self._connect() as conn:
            if provider:
                row = conn.execute(
                    "SELECT COUNT(*) FROM file_shards WHERE provider = ?",
                    (provider,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM file_shards"
                ).fetchone()
            return int(row[0]) if row else 0

    def clear(self, provider: Optional[str] = None) -> int:
        with self._lock, self._connect() as conn:
            if provider:
                cur = conn.execute(
                    "DELETE FROM file_shards WHERE provider = ?", (provider,)
                )
            else:
                cur = conn.execute("DELETE FROM file_shards")
            return cur.rowcount or 0


# -------- helper for parsers --------

def stat_paths(paths: Iterable[Path]) -> Dict[Path, FileStamp]:
    """Stat a batch of paths, dropping any that no longer exist."""
    out: Dict[Path, FileStamp] = {}
    for p in paths:
        stamp = FileStamp.from_path(p)
        if stamp is not None:
            out[p] = stamp
    return out

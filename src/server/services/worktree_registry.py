# -*- coding: utf-8 -*-
"""Repository/worktree registry and lock service.

Provides a light-weight control-plane registry for repo/worktree metadata,
including best-effort cache entries and cooperative locks. This sits above
the lower-level git worktree helpers used by slash commands.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.runtime.stores.db import Database, get_db


@dataclass
class RepoWorktreeRecord:
    repo_key: str
    repo_url: Optional[str] = None
    repo_root: Optional[str] = None
    worktree_path: Optional[str] = None
    branch_name: Optional[str] = None
    workspace: Optional[str] = None
    task_id: Optional[str] = None
    prior_session_id: Optional[str] = None
    prior_work_dir: Optional[str] = None
    lock_owner: Optional[str] = None
    lock_token: Optional[str] = None
    lock_expires_at: Optional[float] = None
    last_used_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repo_key": self.repo_key,
            "repo_url": self.repo_url,
            "repo_root": self.repo_root,
            "worktree_path": self.worktree_path,
            "branch_name": self.branch_name,
            "workspace": self.workspace,
            "task_id": self.task_id,
            "prior_session_id": self.prior_session_id,
            "prior_work_dir": self.prior_work_dir,
            "lock_owner": self.lock_owner,
            "lock_token": self.lock_token,
            "lock_expires_at": self.lock_expires_at,
            "last_used_at": self.last_used_at,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class BareRepoCacheRecord:
    repo_key: str
    repo_url: Optional[str] = None
    repo_root: Optional[str] = None
    cache_path: Optional[str] = None
    lock_owner: Optional[str] = None
    lock_token: Optional[str] = None
    lock_expires_at: Optional[float] = None
    last_fetched_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repo_key": self.repo_key,
            "repo_url": self.repo_url,
            "repo_root": self.repo_root,
            "cache_path": self.cache_path,
            "lock_owner": self.lock_owner,
            "lock_token": self.lock_token,
            "lock_expires_at": self.lock_expires_at,
            "last_fetched_at": self.last_fetched_at,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class RepoWorktreeRegistry:
    """SQLite-backed repo/worktree registry and cooperative lock table."""

    def __init__(self, db: Optional[Database] = None):
        self._db = db or get_db()
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS repo_worktrees (
                    repo_key TEXT PRIMARY KEY,
                    repo_url TEXT,
                    repo_root TEXT,
                    worktree_path TEXT,
                    branch_name TEXT,
                    workspace TEXT,
                    task_id TEXT,
                    prior_session_id TEXT,
                    prior_work_dir TEXT,
                    lock_owner TEXT,
                    lock_token TEXT,
                    lock_expires_at REAL,
                    last_used_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_repo_worktrees_repo_root ON repo_worktrees(repo_root, updated_at DESC)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_repo_worktrees_worktree_path ON repo_worktrees(worktree_path, updated_at DESC)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_repo_worktrees_task_id ON repo_worktrees(task_id, updated_at DESC)"
            )
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS bare_repo_caches (
                    repo_key TEXT PRIMARY KEY,
                    repo_url TEXT,
                    repo_root TEXT,
                    cache_path TEXT,
                    lock_owner TEXT,
                    lock_token TEXT,
                    lock_expires_at REAL,
                    last_fetched_at REAL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_bare_repo_caches_repo_url ON bare_repo_caches(repo_url, updated_at DESC)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_bare_repo_caches_repo_root ON bare_repo_caches(repo_root, updated_at DESC)"
            )
        except Exception:
            pass

    @staticmethod
    def _hash_key(raw: str) -> str:
        return uuid.uuid5(uuid.NAMESPACE_URL, raw).hex[:16]

    @classmethod
    def _derive_repo_key(cls, repo_url: Optional[str], repo_root: Optional[str], worktree_path: Optional[str] = None) -> str:
        raw = (repo_url or repo_root or worktree_path or "").strip()
        if not raw:
            raw = f"repo:{int(time.time() * 1000)}"
        return cls._hash_key(raw)

    @classmethod
    def _derive_task_handoff_key(
        cls,
        *,
        task_id: Optional[str],
        repo_url: Optional[str],
        repo_root: Optional[str],
        worktree_path: Optional[str],
    ) -> str:
        if worktree_path and worktree_path.strip():
            raw = f"handoff:worktree:{worktree_path.strip()}"
        elif task_id and task_id.strip():
            raw = f"handoff:task:{task_id.strip()}"
        else:
            raw = f"handoff:repo:{(repo_url or repo_root or '').strip()}"
        return cls._hash_key(raw or f"handoff:{int(time.time() * 1000)}")

    def _row_to_record(self, row: Dict[str, Any]) -> RepoWorktreeRecord:
        metadata: Dict[str, Any] = {}
        raw = row.get("metadata_json")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    metadata = parsed
            except Exception:
                metadata = {}
        return RepoWorktreeRecord(
            repo_key=row.get("repo_key", ""),
            repo_url=row.get("repo_url") or None,
            repo_root=row.get("repo_root") or None,
            worktree_path=row.get("worktree_path") or None,
            branch_name=row.get("branch_name") or None,
            workspace=row.get("workspace") or None,
            task_id=row.get("task_id") or None,
            prior_session_id=row.get("prior_session_id") or None,
            prior_work_dir=row.get("prior_work_dir") or None,
            lock_owner=row.get("lock_owner") or None,
            lock_token=row.get("lock_token") or None,
            lock_expires_at=row.get("lock_expires_at") or None,
            last_used_at=float(row.get("last_used_at") or time.time()),
            metadata=metadata,
            created_at=float(row.get("created_at") or time.time()),
            updated_at=float(row.get("updated_at") or time.time()),
        )

    def _row_to_cache_record(self, row: Dict[str, Any]) -> BareRepoCacheRecord:
        metadata: Dict[str, Any] = {}
        raw = row.get("metadata_json")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    metadata = parsed
            except Exception:
                metadata = {}
        return BareRepoCacheRecord(
            repo_key=row.get("repo_key", ""),
            repo_url=row.get("repo_url") or None,
            repo_root=row.get("repo_root") or None,
            cache_path=row.get("cache_path") or None,
            lock_owner=row.get("lock_owner") or None,
            lock_token=row.get("lock_token") or None,
            lock_expires_at=row.get("lock_expires_at") or None,
            last_fetched_at=float(row.get("last_fetched_at")) if row.get("last_fetched_at") not in (None, "") else None,
            metadata=metadata,
            created_at=float(row.get("created_at") or time.time()),
            updated_at=float(row.get("updated_at") or time.time()),
        )

    def register(
        self,
        *,
        repo_url: Optional[str] = None,
        repo_root: Optional[str] = None,
        worktree_path: Optional[str] = None,
        branch_name: Optional[str] = None,
        workspace: Optional[str] = None,
        task_id: Optional[str] = None,
        prior_session_id: Optional[str] = None,
        prior_work_dir: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        _repo_key: Optional[str] = None,
    ) -> RepoWorktreeRecord:
        repo_key = _repo_key or self._derive_repo_key(repo_url, repo_root, worktree_path)
        now = time.time()
        existing = self.get(repo_key)
        record = RepoWorktreeRecord(
            repo_key=repo_key,
            repo_url=repo_url or (existing.repo_url if existing else None),
            repo_root=repo_root or (existing.repo_root if existing else None),
            worktree_path=worktree_path or (existing.worktree_path if existing else None),
            branch_name=branch_name or (existing.branch_name if existing else None),
            workspace=workspace or (existing.workspace if existing else None),
            task_id=task_id or (existing.task_id if existing else None),
            prior_session_id=prior_session_id or (existing.prior_session_id if existing else None),
            prior_work_dir=prior_work_dir or (existing.prior_work_dir if existing else None),
            lock_owner=existing.lock_owner if existing else None,
            lock_token=existing.lock_token if existing else None,
            lock_expires_at=existing.lock_expires_at if existing else None,
            last_used_at=now,
            metadata={**(existing.metadata if existing else {}), **(metadata or {})},
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO repo_worktrees (
                    repo_key, repo_url, repo_root, worktree_path, branch_name, workspace,
                    task_id, prior_session_id, prior_work_dir,
                    lock_owner, lock_token, lock_expires_at,
                    last_used_at, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo_key) DO UPDATE SET
                    repo_url=excluded.repo_url,
                    repo_root=excluded.repo_root,
                    worktree_path=excluded.worktree_path,
                    branch_name=excluded.branch_name,
                    workspace=excluded.workspace,
                    task_id=excluded.task_id,
                    prior_session_id=excluded.prior_session_id,
                    prior_work_dir=excluded.prior_work_dir,
                    last_used_at=excluded.last_used_at,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record.repo_key,
                    record.repo_url,
                    record.repo_root,
                    record.worktree_path,
                    record.branch_name,
                    record.workspace,
                    record.task_id,
                    record.prior_session_id,
                    record.prior_work_dir,
                    record.lock_owner,
                    record.lock_token,
                    record.lock_expires_at,
                    record.last_used_at,
                    json.dumps(record.metadata, ensure_ascii=False),
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def register_task_handoff(
        self,
        *,
        task_id: str,
        repo_url: Optional[str] = None,
        repo_root: Optional[str] = None,
        worktree_path: Optional[str] = None,
        workspace: Optional[str] = None,
        branch_name: Optional[str] = None,
        prior_session_id: Optional[str] = None,
        prior_work_dir: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RepoWorktreeRecord:
        payload = dict(metadata or {})
        payload["task_id"] = task_id
        repo_key = self._derive_task_handoff_key(
            task_id=task_id,
            repo_url=repo_url,
            repo_root=repo_root,
            worktree_path=worktree_path,
        )
        return self.register(
            repo_url=repo_url,
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch_name=branch_name,
            workspace=workspace,
            task_id=task_id,
            prior_session_id=prior_session_id,
            prior_work_dir=prior_work_dir,
            metadata=payload,
            _repo_key=repo_key,
        )

    def get(self, repo_key: str) -> Optional[RepoWorktreeRecord]:
        row = self._db.execute_fetchone("SELECT * FROM repo_worktrees WHERE repo_key = ?", (repo_key,))
        if not row:
            return None
        return self._row_to_record(row)

    def find_by_repo_root(self, repo_root: str) -> Optional[RepoWorktreeRecord]:
        row = self._db.execute_fetchone(
            "SELECT * FROM repo_worktrees WHERE repo_root = ? ORDER BY updated_at DESC LIMIT 1",
            (repo_root,),
        )
        return self._row_to_record(row) if row else None

    def find_by_worktree_path(self, worktree_path: str) -> Optional[RepoWorktreeRecord]:
        row = self._db.execute_fetchone(
            "SELECT * FROM repo_worktrees WHERE worktree_path = ? ORDER BY updated_at DESC LIMIT 1",
            (worktree_path,),
        )
        return self._row_to_record(row) if row else None

    def list_records(self, repo_root: Optional[str] = None, workspace: Optional[str] = None) -> List[RepoWorktreeRecord]:
        conditions: List[str] = []
        params: List[Any] = []
        if repo_root:
            conditions.append("repo_root = ?")
            params.append(repo_root)
        if workspace:
            conditions.append("workspace = ?")
            params.append(workspace)
        where = " AND ".join(conditions) if conditions else "1=1"
        rows = self._db.execute_fetchall(
            f"SELECT * FROM repo_worktrees WHERE {where} ORDER BY updated_at DESC",
            tuple(params),
        )
        return [self._row_to_record(row) for row in rows]

    def acquire_lock(
        self,
        repo_key: str,
        *,
        owner: str,
        token: Optional[str] = None,
        ttl_seconds: float = 300.0,
    ) -> bool:
        now = time.time()
        token = token or hashlib.sha1(f"{repo_key}:{owner}:{now}".encode("utf-8")).hexdigest()[:20]
        expires_at = now + ttl_seconds if ttl_seconds and ttl_seconds > 0 else None
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT lock_owner, lock_token, lock_expires_at FROM repo_worktrees WHERE repo_key = ?",
                (repo_key,),
            ).fetchone()
            if row is None:
                return False
            lock_owner = row[0]
            lock_token = row[1]
            lock_expires_at = row[2]
            if lock_token and lock_expires_at and lock_expires_at > now and lock_owner not in (None, "", owner):
                return False
            cursor = conn.execute(
                """
                UPDATE repo_worktrees
                SET lock_owner = ?, lock_token = ?, lock_expires_at = ?, updated_at = ?
                WHERE repo_key = ?
                """,
                (owner, token, expires_at, now, repo_key),
            )
        return bool(getattr(cursor, "rowcount", 0))

    def release_lock(self, repo_key: str, *, owner: Optional[str] = None, token: Optional[str] = None) -> bool:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT lock_owner, lock_token FROM repo_worktrees WHERE repo_key = ?",
                (repo_key,),
            ).fetchone()
            if row is None:
                return False
            if owner and row[0] and row[0] != owner:
                return False
            if token and row[1] and row[1] != token:
                return False
            cursor = conn.execute(
                """
                UPDATE repo_worktrees
                SET lock_owner = NULL, lock_token = NULL, lock_expires_at = NULL, updated_at = ?
                WHERE repo_key = ?
                """,
                (time.time(), repo_key),
            )
        return bool(getattr(cursor, "rowcount", 0))

    def touch(self, repo_key: str, *, metadata: Optional[Dict[str, Any]] = None) -> bool:
        record = self.get(repo_key)
        if not record:
            return False
        payload = {**(record.metadata or {}), **(metadata or {})}
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE repo_worktrees
                SET last_used_at = ?, metadata_json = ?, updated_at = ?
                WHERE repo_key = ?
                """,
                (time.time(), json.dumps(payload, ensure_ascii=False), time.time(), repo_key),
            )
        return True

    def register_cache(
        self,
        *,
        repo_url: Optional[str] = None,
        repo_root: Optional[str] = None,
        cache_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        last_fetched_at: Optional[float] = None,
    ) -> BareRepoCacheRecord:
        repo_key = self._derive_repo_key(repo_url, repo_root, cache_path)
        now = time.time()
        existing = self.get_cache(repo_key)
        record = BareRepoCacheRecord(
            repo_key=repo_key,
            repo_url=repo_url or (existing.repo_url if existing else None),
            repo_root=repo_root or (existing.repo_root if existing else None),
            cache_path=cache_path or (existing.cache_path if existing else None),
            lock_owner=existing.lock_owner if existing else None,
            lock_token=existing.lock_token if existing else None,
            lock_expires_at=existing.lock_expires_at if existing else None,
            last_fetched_at=last_fetched_at if last_fetched_at is not None else (existing.last_fetched_at if existing else None),
            metadata={**(existing.metadata if existing else {}), **(metadata or {})},
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO bare_repo_caches (
                    repo_key, repo_url, repo_root, cache_path,
                    lock_owner, lock_token, lock_expires_at,
                    last_fetched_at, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo_key) DO UPDATE SET
                    repo_url=excluded.repo_url,
                    repo_root=excluded.repo_root,
                    cache_path=excluded.cache_path,
                    last_fetched_at=excluded.last_fetched_at,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record.repo_key,
                    record.repo_url,
                    record.repo_root,
                    record.cache_path,
                    record.lock_owner,
                    record.lock_token,
                    record.lock_expires_at,
                    record.last_fetched_at,
                    json.dumps(record.metadata, ensure_ascii=False),
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def get_cache(self, repo_key: str) -> Optional[BareRepoCacheRecord]:
        row = self._db.execute_fetchone("SELECT * FROM bare_repo_caches WHERE repo_key = ?", (repo_key,))
        return self._row_to_cache_record(row) if row else None

    def find_cache(self, *, repo_url: Optional[str] = None, repo_root: Optional[str] = None) -> Optional[BareRepoCacheRecord]:
        if repo_url:
            row = self._db.execute_fetchone(
                "SELECT * FROM bare_repo_caches WHERE repo_url = ? ORDER BY updated_at DESC LIMIT 1",
                (repo_url,),
            )
            if row:
                return self._row_to_cache_record(row)
        if repo_root:
            row = self._db.execute_fetchone(
                "SELECT * FROM bare_repo_caches WHERE repo_root = ? ORDER BY updated_at DESC LIMIT 1",
                (repo_root,),
            )
            if row:
                return self._row_to_cache_record(row)
        return None

    def list_caches(self) -> List[BareRepoCacheRecord]:
        rows = self._db.execute_fetchall(
            "SELECT * FROM bare_repo_caches ORDER BY updated_at DESC, repo_key ASC"
        )
        return [self._row_to_cache_record(row) for row in rows]

    def acquire_cache_lock(
        self,
        repo_key: str,
        *,
        owner: str,
        token: Optional[str] = None,
        ttl_seconds: float = 300.0,
    ) -> bool:
        now = time.time()
        token = token or hashlib.sha1(f"cache:{repo_key}:{owner}:{now}".encode("utf-8")).hexdigest()[:20]
        expires_at = now + ttl_seconds if ttl_seconds and ttl_seconds > 0 else None
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT lock_owner, lock_token, lock_expires_at FROM bare_repo_caches WHERE repo_key = ?",
                (repo_key,),
            ).fetchone()
            if row is None:
                return False
            lock_owner = row[0]
            lock_token = row[1]
            lock_expires_at = row[2]
            if lock_token and lock_expires_at and lock_expires_at > now and lock_owner not in (None, "", owner):
                return False
            cursor = conn.execute(
                """
                UPDATE bare_repo_caches
                SET lock_owner = ?, lock_token = ?, lock_expires_at = ?, updated_at = ?
                WHERE repo_key = ?
                """,
                (owner, token, expires_at, now, repo_key),
            )
        return bool(getattr(cursor, "rowcount", 0))

    def release_cache_lock(self, repo_key: str, *, owner: Optional[str] = None, token: Optional[str] = None) -> bool:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT lock_owner, lock_token FROM bare_repo_caches WHERE repo_key = ?",
                (repo_key,),
            ).fetchone()
            if row is None:
                return False
            if owner and row[0] and row[0] != owner:
                return False
            if token and row[1] and row[1] != token:
                return False
            cursor = conn.execute(
                """
                UPDATE bare_repo_caches
                SET lock_owner = NULL, lock_token = NULL, lock_expires_at = NULL, updated_at = ?
                WHERE repo_key = ?
                """,
                (time.time(), repo_key),
            )
        return bool(getattr(cursor, "rowcount", 0))


_repo_worktree_registry: Optional[RepoWorktreeRegistry] = None


def get_repo_worktree_registry() -> RepoWorktreeRegistry:
    global _repo_worktree_registry
    if _repo_worktree_registry is None:
        _repo_worktree_registry = RepoWorktreeRegistry()
    return _repo_worktree_registry

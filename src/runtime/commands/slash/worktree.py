# -*- coding: utf-8 -*-
"""Git worktree helper with isolation levels, lifecycle management, and garbage collection.

This module encapsulates the logic for:
- verifying a directory is inside a git work tree
- computing deterministic worktree path + branch name for a task
- creating/reusing the worktree under /tmp
- managing worktree lifecycle with session/agent isolation
- garbage collection for stale worktrees

Pure functions (is_git_worktree, get_repo_root, etc.) are preserved for backward compat.
New classes (WorktreeManager, WorktreeGarbageCollector) build on top.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import subprocess


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class WorktreeError(RuntimeError):
    """Base error for worktree resolution."""


class NotGitRepoError(WorktreeError):
    """Raised when workspace is not inside a git work tree."""


class WorktreeDirConflictError(WorktreeError):
    """Raised when target dir exists but is not a registered worktree."""


class WorktreeCommandError(WorktreeError):
    """Raised when underlying git commands fail."""


class WorktreeNotFoundError(WorktreeError):
    """Raised when a requested worktree does not exist in the registry."""


# ---------------------------------------------------------------------------
# Legacy data model (kept for backward compat)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorktreeResult:
    repo_root: Path
    repo_name: str
    task_id: str
    branch: str
    worktree_dir: Path
    reused: bool


# ---------------------------------------------------------------------------
# Isolation model
# ---------------------------------------------------------------------------

class IsolationLevel(str, Enum):
    """Isolation level for worktree ownership."""
    SESSION = "session"   # Session-level: same session shares a worktree
    AGENT = "agent"       # Agent-level: each agent gets its own worktree


@dataclass
class WorktreeEntry:
    """Tracks full metadata for a single worktree."""
    worktree_id: str
    path: Path
    branch: str
    isolation_level: IsolationLevel
    session_key: str | None = None    # SESSION-level binding
    agent_name: str | None = None     # AGENT-level binding
    task_id: str | None = None
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    status: str = "active"  # "active" | "stale" | "garbage"

    def to_dict(self) -> dict:
        return {
            "worktree_id": self.worktree_id,
            "path": str(self.path),
            "branch": self.branch,
            "isolation_level": self.isolation_level.value,
            "session_key": self.session_key,
            "agent_name": self.agent_name,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorktreeEntry:
        return cls(
            worktree_id=data["worktree_id"],
            path=Path(data["path"]),
            branch=data["branch"],
            isolation_level=IsolationLevel(data["isolation_level"]),
            session_key=data.get("session_key"),
            agent_name=data.get("agent_name"),
            task_id=data.get("task_id"),
            created_at=data.get("created_at", time.time()),
            last_accessed=data.get("last_accessed", time.time()),
            status=data.get("status", "active"),
        )


# ---------------------------------------------------------------------------
# GC result
# ---------------------------------------------------------------------------

@dataclass
class GcResult:
    """Result from garbage collection run."""
    removed: list[str] = field(default_factory=list)   # worktree_ids removed
    stashed: list[str] = field(default_factory=list)   # had uncommitted changes, stashed
    skipped: list[str] = field(default_factory=list)   # still referenced, skipped
    errors: list[str] = field(default_factory=list)    # removal failures


# ---------------------------------------------------------------------------
# Low-level git helpers (pure functions — unchanged API)
# ---------------------------------------------------------------------------

def _run_git(repo_dir: Path, args: list[str]) -> subprocess.CompletedProcess:
    """Run `git -C <repo_dir> ...`.

    We never raise; caller inspects returncode/stdout/stderr.
    """
    return subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
    )


def is_git_worktree(path: Path) -> bool:
    """Return True if `path` is inside a git work tree."""
    path = Path(path)
    res = _run_git(path, ["rev-parse", "--is-inside-work-tree"])
    return res.returncode == 0 and (res.stdout or "").strip().lower() == "true"


def get_repo_root(path: Path) -> Path:
    """Resolve git repo root for `path`.

    Raises:
        WorktreeError: if `path` is not a git repo/worktree.
    """
    path = Path(path)
    res = _run_git(path, ["rev-parse", "--show-toplevel"])
    if res.returncode != 0:
        raise NotGitRepoError(
            f"目标目录不是 Git 仓库或不在 Git worktree 内：{path}"
        )
    root = (res.stdout or "").strip()
    if not root:
        raise WorktreeError(f"无法解析 Git repo root：{path}")
    return Path(root)


def _parse_worktree_list_porcelain(text: str) -> set[str]:
    """Parse `git worktree list --porcelain` output.

    Returns a set of absolute worktree paths as strings.
    """
    paths: set[str] = set()
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("worktree "):
            p = line[len("worktree "):].strip()
            if p:
                paths.add(str(Path(p)))
    return paths


def is_registered_worktree(repo_root: Path, worktree_dir: Path) -> bool:
    """Check whether `worktree_dir` is registered in `repo_root` worktree list."""
    repo_root = Path(repo_root)
    worktree_dir = Path(worktree_dir)

    res = _run_git(repo_root, ["worktree", "list", "--porcelain"])
    if res.returncode != 0:
        raise WorktreeCommandError(
            f"无法读取 git worktree 列表（repo={repo_root}）：{(res.stderr or '').strip()}"
        )
    registered = _parse_worktree_list_porcelain(res.stdout)
    return str(worktree_dir) in registered


def compute_worktree_dir(repo_root: Path, task_id: str, tmp_base: Path = Path("/tmp")) -> Path:
    repo_name = Path(repo_root).name
    return Path(tmp_base) / f"{repo_name}_feature_{task_id}"


def compute_branch_name(task_id: str) -> str:
    return f"feature_{task_id}"


def ensure_task_worktree(
    workspace: Path,
    task_id: str,
    tmp_base: Path = Path("/tmp"),
) -> WorktreeResult:
    """Ensure the task worktree exists.

    Rules (per product requirements):
    - `workspace` MUST be a git work tree; otherwise raise.
    - worktree dir is `/tmp/<repo>_feature_<taskId>`
    - branch is `feature_<taskId>`
    - if target dir exists:
      - reuse only if it is registered in `git worktree list`
      - otherwise raise
    """
    workspace = Path(workspace)
    repo_root = get_repo_root(workspace)
    repo_name = repo_root.name

    branch = compute_branch_name(task_id)
    target = compute_worktree_dir(repo_root, task_id=task_id, tmp_base=tmp_base)

    if target.exists():
        if is_registered_worktree(repo_root, target):
            return WorktreeResult(
                repo_root=repo_root,
                repo_name=repo_name,
                task_id=task_id,
                branch=branch,
                worktree_dir=target,
                reused=True,
            )
        raise WorktreeDirConflictError(
            f"worktree 目标目录已存在但未在 git worktree 中注册：{target}"
        )

    # Try to create worktree + branch
    res = _run_git(repo_root, ["worktree", "add", "-b", branch, str(target)])
    if res.returncode != 0:
        stderr = (res.stderr or "").strip()
        # If branch already exists, try reusing it.
        if "already exists" in stderr.lower() and "branch" in stderr.lower():
            res2 = _run_git(repo_root, ["worktree", "add", str(target), branch])
            if res2.returncode != 0:
                raise WorktreeCommandError(
                    f"git worktree add 失败（复用分支 {branch}）：{(res2.stderr or '').strip()}"
                )
        else:
            raise WorktreeCommandError(f"git worktree add 失败：{stderr}")

    return WorktreeResult(
        repo_root=repo_root,
        repo_name=repo_name,
        task_id=task_id,
        branch=branch,
        worktree_dir=target,
        reused=False,
    )


# ---------------------------------------------------------------------------
# WorktreeManager — lifecycle management with isolation
# ---------------------------------------------------------------------------

_REGISTRY_FILE = "worktree_registry.json"


class WorktreeManager:
    """Manage worktree lifecycle with session/agent isolation.

    Maintains an in-memory registry of WorktreeEntry objects, optionally
    persisted to a JSON file so the registry survives process restarts.
    """

    def __init__(self, workspace: Path, *, tmp_base: Path = Path("/tmp")):
        self.workspace = Path(workspace)
        self.tmp_base = Path(tmp_base)
        self._registry: dict[str, WorktreeEntry] = {}   # worktree_id -> entry
        self._session_map: dict[str, str] = {}           # session_key -> worktree_id
        self._agent_map: dict[str, str] = {}             # agent_name -> worktree_id
        self._registry_path = self.workspace / _REGISTRY_FILE
        self._load_registry()

    # ---- persistence ----

    def _load_registry(self) -> None:
        if not self._registry_path.exists():
            return
        try:
            data = json.loads(self._registry_path.read_text(encoding="utf-8"))
            for item in data.get("entries", []):
                entry = WorktreeEntry.from_dict(item)
                self._registry[entry.worktree_id] = entry
                if entry.session_key and entry.status == "active":
                    self._session_map[entry.session_key] = entry.worktree_id
                if entry.agent_name and entry.status == "active":
                    self._agent_map[entry.agent_name] = entry.worktree_id
        except Exception:
            pass  # Corrupted registry — start fresh

    def _save_registry(self) -> None:
        try:
            self._registry_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "entries": [e.to_dict() for e in self._registry.values()],
            }
            self._registry_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass  # Best-effort persistence

    # ---- create ----

    def create_isolated(
        self,
        isolation_level: IsolationLevel,
        session_key: str | None = None,
        agent_name: str | None = None,
        task_id: str | None = None,
    ) -> WorktreeEntry:
        """Create an isolated worktree.

        For SESSION isolation, if a worktree already exists for the session_key,
        it is returned (with last_accessed updated).
        For AGENT isolation, same behaviour keyed by agent_name.
        """
        # Check for existing binding
        if isolation_level == IsolationLevel.SESSION and session_key:
            existing = self.find_by_session(session_key)
            if existing:
                self.touch(existing.worktree_id)
                return existing

        if isolation_level == IsolationLevel.AGENT and agent_name:
            existing = self.find_by_agent(agent_name)
            if existing:
                self.touch(existing.worktree_id)
                return existing

        # Build deterministic identifiers
        effective_key = task_id or session_key or agent_name or uuid.uuid4().hex[:8]
        repo_root = get_repo_root(self.workspace)
        repo_name = repo_root.name

        # Determine branch and path based on isolation level
        if isolation_level == IsolationLevel.SESSION:
            suffix = f"session_{session_key or effective_key}"
        else:
            suffix = f"agent_{agent_name or effective_key}"

        if task_id:
            suffix = f"{suffix}_{task_id}"

        branch = f"feature_{suffix}"
        worktree_dir = self.tmp_base / f"{repo_name}_{suffix}"

        # Create the git worktree
        worktree_dir.parent.mkdir(parents=True, exist_ok=True)
        res = _run_git(repo_root, ["worktree", "add", "-b", branch, str(worktree_dir)])
        if res.returncode != 0:
            stderr = (res.stderr or "").strip()
            # Branch might already exist — try reusing it
            if "already exists" in stderr.lower() and "branch" in stderr.lower():
                res2 = _run_git(repo_root, ["worktree", "add", str(worktree_dir), branch])
                if res2.returncode != 0:
                    raise WorktreeCommandError(
                        f"git worktree add 失败（复用分支 {branch}）：{(res2.stderr or '').strip()}"
                    )
            else:
                raise WorktreeCommandError(f"git worktree add 失败：{stderr}")

        entry = WorktreeEntry(
            worktree_id=uuid.uuid4().hex[:12],
            path=worktree_dir,
            branch=branch,
            isolation_level=isolation_level,
            session_key=session_key if isolation_level == IsolationLevel.SESSION else None,
            agent_name=agent_name if isolation_level == IsolationLevel.AGENT else None,
            task_id=task_id,
        )

        self._registry[entry.worktree_id] = entry
        if entry.session_key:
            self._session_map[entry.session_key] = entry.worktree_id
        if entry.agent_name:
            self._agent_map[entry.agent_name] = entry.worktree_id

        self._save_registry()
        return entry

    # ---- find ----

    def find_by_session(self, session_key: str) -> WorktreeEntry | None:
        wid = self._session_map.get(session_key)
        if wid:
            return self._registry.get(wid)
        return None

    def find_by_agent(self, agent_name: str) -> WorktreeEntry | None:
        wid = self._agent_map.get(agent_name)
        if wid:
            return self._registry.get(wid)
        return None

    def find_by_id(self, worktree_id: str) -> WorktreeEntry | None:
        return self._registry.get(worktree_id)

    # ---- resume (fast-path) ----

    def resume_session(self, session_key: str) -> WorktreeEntry:
        """Resume a session-bound worktree. Raises if not found."""
        entry = self.find_by_session(session_key)
        if not entry:
            raise WorktreeNotFoundError(
                f"未找到会话 {session_key} 对应的 worktree"
            )
        if entry.status != "active":
            # Reactivate
            entry.status = "active"
            self._save_registry()
        self.touch(entry.worktree_id)
        return entry

    def resume_agent(self, agent_name: str) -> WorktreeEntry:
        """Resume an agent-bound worktree. Raises if not found."""
        entry = self.find_by_agent(agent_name)
        if not entry:
            raise WorktreeNotFoundError(
                f"未找到 agent {agent_name} 对应的 worktree"
            )
        if entry.status != "active":
            entry.status = "active"
            self._save_registry()
        self.touch(entry.worktree_id)
        return entry

    # ---- touch ----

    def touch(self, worktree_id: str) -> None:
        entry = self._registry.get(worktree_id)
        if entry:
            entry.last_accessed = time.time()
            self._save_registry()

    # ---- list ----

    def list_active(self) -> list[WorktreeEntry]:
        return [e for e in self._registry.values() if e.status == "active"]

    def list_stale(self, max_age_hours: float = 24.0) -> list[WorktreeEntry]:
        cutoff = time.time() - max_age_hours * 3600
        return [
            e for e in self._registry.values()
            if e.last_accessed < cutoff and e.status in ("active", "stale")
        ]

    def list_all(self) -> list[WorktreeEntry]:
        return list(self._registry.values())

    # ---- internal helpers ----

    def _unregister(self, worktree_id: str) -> None:
        """Remove entry from registry and index maps."""
        entry = self._registry.pop(worktree_id, None)
        if not entry:
            return
        if entry.session_key:
            self._session_map.pop(entry.session_key, None)
        if entry.agent_name:
            self._agent_map.pop(entry.agent_name, None)
        self._save_registry()


# ---------------------------------------------------------------------------
# WorktreeGarbageCollector
# ---------------------------------------------------------------------------

class WorktreeGarbageCollector:
    """Reclaim worktrees that are no longer needed."""

    def __init__(self, manager: WorktreeManager):
        self.manager = manager

    @staticmethod
    def _has_uncommitted_changes(worktree_path: Path) -> bool:
        """Check if a worktree has uncommitted changes."""
        res = _run_git(worktree_path, ["status", "--porcelain"])
        if res.returncode != 0:
            return False  # Cannot determine — assume clean
        return bool((res.stdout or "").strip())

    @staticmethod
    def _stash_and_remove(worktree_path: Path, repo_root: Path) -> bool:
        """Stash uncommitted changes and remove the worktree.

        Returns True on success.
        """
        # Stash in the worktree
        _run_git(worktree_path, ["stash", "--include-untracked"])

        # Remove the worktree from the main repo
        res = _run_git(repo_root, ["worktree", "remove", str(worktree_path), "--force"])
        return res.returncode == 0

    @staticmethod
    def _remove_worktree_clean(worktree_path: Path, repo_root: Path) -> bool:
        """Remove a clean worktree. Returns True on success."""
        res = _run_git(repo_root, ["worktree", "remove", str(worktree_path), "--force"])
        return res.returncode == 0

    @staticmethod
    def _delete_branch(repo_root: Path, branch: str) -> bool:
        """Delete a branch from the main repo. Returns True on success."""
        res = _run_git(repo_root, ["branch", "-D", branch])
        return res.returncode == 0

    def mark_stale(self, worktree_id: str) -> bool:
        """Mark a worktree as stale. Returns True if found and marked."""
        entry = self.manager.find_by_id(worktree_id)
        if not entry:
            return False
        entry.status = "stale"
        self.manager._save_registry()
        return True

    def force_remove(self, worktree_id: str) -> bool:
        """Force-remove a worktree regardless of state.

        Stashes uncommitted changes if any, then removes.
        Returns True on success.
        """
        entry = self.manager.find_by_id(worktree_id)
        if not entry:
            return False

        repo_root = get_repo_root(entry.path) if is_git_worktree(entry.path) else self.manager.workspace
        worktree_path = entry.path

        if worktree_path.exists() and is_git_worktree(worktree_path):
            if self._has_uncommitted_changes(worktree_path):
                self._stash_and_remove(worktree_path, repo_root)
            else:
                self._remove_worktree_clean(worktree_path, repo_root)

            # Best-effort branch deletion
            self._delete_branch(repo_root, entry.branch)

        self.manager._unregister(worktree_id)
        return True

    def collect(
        self,
        max_age_hours: float = 24.0,
        dry_run: bool = False,
    ) -> GcResult:
        """Collect stale/garbage worktrees.

        Args:
            max_age_hours: Worktrees not accessed in this many hours are collected.
            dry_run: If True, only report what would be done without actually removing.

        Returns:
            GcResult with details of what happened.
        """
        result = GcResult()
        stale_entries = self.manager.list_stale(max_age_hours=max_age_hours)
        garbage_entries = [
            e for e in self.manager.list_all() if e.status == "garbage"
        ]
        candidates = stale_entries + garbage_entries

        for entry in candidates:
            worktree_path = entry.path

            if not worktree_path.exists() or not is_git_worktree(worktree_path):
                # Already gone from disk — just clean registry
                if not dry_run:
                    self.manager._unregister(entry.worktree_id)
                result.removed.append(entry.worktree_id)
                continue

            repo_root = get_repo_root(worktree_path)

            if self._has_uncommitted_changes(worktree_path):
                if dry_run:
                    result.stashed.append(entry.worktree_id)
                else:
                    ok = self._stash_and_remove(worktree_path, repo_root)
                    if ok:
                        self._delete_branch(repo_root, entry.branch)
                        self.manager._unregister(entry.worktree_id)
                        result.stashed.append(entry.worktree_id)
                    else:
                        result.errors.append(
                            f"{entry.worktree_id}: stash+remove failed"
                        )
            else:
                if dry_run:
                    result.removed.append(entry.worktree_id)
                else:
                    ok = self._remove_worktree_clean(worktree_path, repo_root)
                    if ok:
                        self._delete_branch(repo_root, entry.branch)
                        self.manager._unregister(entry.worktree_id)
                        result.removed.append(entry.worktree_id)
                    else:
                        result.errors.append(
                            f"{entry.worktree_id}: remove failed"
                        )

        return result

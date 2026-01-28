# -*- coding: utf-8 -*-
"""Git worktree helper.

This module encapsulates the logic for:
- verifying a directory is inside a git work tree
- computing deterministic worktree path + branch name for a task
- creating/reusing the worktree under /tmp

It is intentionally small and pure (shells out to `git`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import subprocess


class WorktreeError(RuntimeError):
    """Base error for worktree resolution."""


class NotGitRepoError(WorktreeError):
    """Raised when workspace is not inside a git work tree."""


class WorktreeDirConflictError(WorktreeError):
    """Raised when target dir exists but is not a registered worktree."""


class WorktreeCommandError(WorktreeError):
    """Raised when underlying git commands fail."""


@dataclass(frozen=True)
class WorktreeResult:
    repo_root: Path
    repo_name: str
    task_id: str
    branch: str
    worktree_dir: Path
    reused: bool


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

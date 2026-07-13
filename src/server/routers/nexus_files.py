# -*- coding: utf-8 -*-
"""Nexus Files API Router

Provides REST API endpoints for session file management:
- List files in a session folder
- Download files from a session folder
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from ..config import settings
from ..services.user_directory import UserDirectoryManager
from ..services.session_storage import get_session_storage
from ..logger import get_logger
from ..security.exec_user_guard import validate_exec_user
from .nexus_auth import verify_nexus_auth
from .nexus_models import (
    FileItem,
    SessionFilesResponse,
    get_task_queue,
)

logger = get_logger(__name__)
_user_dir_manager = UserDirectoryManager(settings)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-files"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ---------------------------------------------------------------------------
# Path safety helpers
# Ported from mission-control src/lib/memory-path.ts (commit dd15409):
#   - Use is_relative_to() instead of str.startswith() to avoid the
#     "/tmp/sess" matches "/tmp/sess-evil" false-positive.
#   - Reject symlinks (lstat check) to prevent symlink escape attacks.
# ---------------------------------------------------------------------------

def _is_within_base(base: Path, candidate: Path) -> bool:
    """Return True iff candidate is the same as or a descendant of base.

    Uses Path.is_relative_to() (Python ≥3.9) which is separator-aware and
    avoids the classical startswith() false-positive where a base of
    '/tmp/session' would wrongly accept '/tmp/session-evil'.
    """
    try:
        return candidate == base or candidate.is_relative_to(base)
    except ValueError:
        return False


def _resolve_safe_path(base_dir: Path, relative_path: str) -> Path:
    """Resolve *relative_path* against *base_dir* with full containment checks.

    Raises HTTPException(400) if:
    - The resolved path escapes base_dir (directory traversal / symlink escape)
    - The target is a symbolic link (symlink-escape attack)

    Raises HTTPException(404) if the target does not exist.

    Ported from mission-control resolveSafeMemoryPath (commit dd15409).
    """
    # Resolve the base to its real (symlink-free) location
    base_real = base_dir.resolve()

    target = base_dir / relative_path

    # For paths that already exist: check for symlinks and containment
    if target.exists() or target.is_symlink():
        # lstat: does NOT follow symlinks — detects the symlink itself
        st = target.lstat()
        import stat as stat_module
        if stat_module.S_ISLNK(st.st_mode):
            raise HTTPException(status_code=400, detail="Symbolic links are not allowed")
        real_target = target.resolve()
        if not _is_within_base(base_real, real_target):
            raise HTTPException(status_code=400, detail="Path escapes base directory")
        return real_target

    # For non-existent paths: walk up to the nearest existing ancestor and
    # verify containment, matching MC's parent-walk logic
    current = target.parent
    while True:
        if current.exists():
            real_parent = current.resolve()
            if not _is_within_base(base_real, real_parent):
                raise HTTPException(status_code=400, detail="Path escapes base directory")
            return base_real / target.relative_to(base_dir)
        parent = current.parent
        if parent == current:
            raise HTTPException(status_code=400, detail="Invalid path: no valid ancestor")
        current = parent


def _resolve_session_folder(session_id: str, exec_user: str) -> Optional[Path]:
    """Resolve the folder path for a session.

    - Regular session: /home/{exec_user}/.nexus/sessions/{session_id}/
    - Task session with inplace workspace: workspace directory from task
    """
    # Check if this is a task session (has task_id in meta) and has an inplace workspace
    try:
        storage = get_session_storage()
        task_id = storage.get_task_id(session_id)
        if task_id:
            queue = get_task_queue(exec_user)
            task = queue.get_task(task_id)
            if task and task.workspace:
                workspace_path = Path(task.workspace)
                if workspace_path.exists():
                    return workspace_path
    except Exception:
        pass

    base_dir = _user_dir_manager.resolve_session_directory(exec_user, session_id)
    return base_dir if base_dir.exists() else None


@router.get("/sessions/{session_id}/files", response_model=SessionFilesResponse)
async def list_session_files(
    session_id: str,
    exec_user: str = Query(settings.exec_user, description="Exec user name"),
    subpath: str = Query("", description="Subdirectory path within session folder"),
):
    """List files in a session's folder.

    - **session_id**: The session ID
    - **exec_user**: Exec user for folder resolution
    - **subpath**: Optional subdirectory path
    """
    exec_user = await validate_exec_user(exec_user)
    folder = _resolve_session_folder(session_id, exec_user)

    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session folder not found for: {session_id}"
        )

    # Handle subpath
    target_path = folder
    if subpath:
        # Reject obvious traversal early (fast path)
        if ".." in Path(subpath).as_posix():
            raise HTTPException(status_code=400, detail="Invalid path")
        # Full containment + symlink check (ported from MC memory-path audit)
        target_path = _resolve_safe_path(folder, subpath)
        if not target_path.exists():
            raise HTTPException(status_code=404, detail=f"Path not found: {subpath}")

    files: List[FileItem] = []

    try:
        for entry in sorted(target_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            # Skip hidden files starting with .
            if entry.name.startswith("."):
                continue

            stat = entry.stat()
            modified_time = datetime.fromtimestamp(stat.st_mtime).isoformat()

            # Calculate relative path from session folder
            rel_path = str(entry.relative_to(folder))

            files.append(FileItem(
                name=entry.name,
                path=rel_path,
                is_dir=entry.is_dir(),
                size=stat.st_size if entry.is_file() else None,
                modified=modified_time,
            ))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list session files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list files")

    return SessionFilesResponse(
        session_id=session_id,
        folder_path=str(folder),
        files=files,
    )


@router.get("/sessions/{session_id}/files/download")
async def download_session_file(
    session_id: str,
    file_path: str = Query(..., description="File path relative to session folder"),
    exec_user: str = Query(settings.exec_user, description="Exec user name"),
):
    """Download a file from session folder.

    - **session_id**: The session ID
    - **file_path**: File path relative to session folder
    - **exec_user**: Exec user for folder resolution
    """
    exec_user = await validate_exec_user(exec_user)
    folder = _resolve_session_folder(session_id, exec_user)

    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session folder not found for: {session_id}"
        )

    # Reject obvious traversal early (fast path)
    if ".." in Path(file_path).as_posix():
        raise HTTPException(status_code=400, detail="Invalid path")

    # Full containment + symlink check (ported from MC memory-path audit)
    target_file = _resolve_safe_path(folder, file_path)

    if not target_file.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    if not target_file.is_file():
        raise HTTPException(status_code=400, detail="Cannot download directory")

    return FileResponse(
        path=str(target_file),
        filename=target_file.name,
        media_type="application/octet-stream",
    )

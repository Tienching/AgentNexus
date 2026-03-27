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


def _resolve_session_folder(session_id: str, exec_user: str) -> Optional[Path]:
    """Resolve the folder path for a session.

    - Regular session: /home/{exec_user}/.nexus/sessions/{session_id}/
    - Task session with inplace workspace: workspace directory from task
    """
    # Check if this is a task session (has task_id in meta) and has an inplace workspace
    try:
        storage = get_session_storage()
        task_id = storage._redis.hget(f"session:{session_id}:meta", "task_id")
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
    folder = _resolve_session_folder(session_id, exec_user)

    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session folder not found for: {session_id}"
        )

    # Handle subpath
    target_path = folder
    if subpath:
        # Prevent directory traversal attacks
        safe_subpath = Path(subpath).as_posix()
        if ".." in safe_subpath:
            raise HTTPException(status_code=400, detail="Invalid path")
        target_path = folder / safe_subpath
        if not target_path.exists():
            raise HTTPException(status_code=404, detail=f"Path not found: {subpath}")
        if not str(target_path.resolve()).startswith(str(folder.resolve())):
            raise HTTPException(status_code=400, detail="Invalid path")

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
    folder = _resolve_session_folder(session_id, exec_user)

    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session folder not found for: {session_id}"
        )

    # Prevent directory traversal attacks
    safe_path = Path(file_path).as_posix()
    if ".." in safe_path:
        raise HTTPException(status_code=400, detail="Invalid path")

    target_file = folder / safe_path

    # Verify the file is within the session folder
    if not str(target_file.resolve()).startswith(str(folder.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target_file.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    if not target_file.is_file():
        raise HTTPException(status_code=400, detail="Cannot download directory")

    return FileResponse(
        path=str(target_file),
        filename=target_file.name,
        media_type="application/octet-stream",
    )

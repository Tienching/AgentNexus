# -*- coding: utf-8 -*-
"""Global search and data cleanup/retention endpoints.

Ported from mission-control:
  - GET /api/search       (search/route.ts) — global search
  - GET /api/cleanup      (cleanup/route.ts) — retention preview
  - POST /api/cleanup     (cleanup/route.ts) — execute cleanup

Adapted for agent-nexus: SQLite-backed search across tasks and sessions,
configurable retention policies.
"""

from __future__ import annotations

import os
import time
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from ..services.task_storage import get_task_queue
from .nexus_auth import verify_nexus_auth

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-ops"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ═══════════════════════════════════════════════════════════════════════════
# Global Search
# ═══════════════════════════════════════════════════════════════════════════

class SearchResult(BaseModel):
    type: Literal["task", "session"]
    id: str
    title: str
    subtitle: Optional[str] = None
    excerpt: Optional[str] = None
    created_at: Optional[str] = None
    relevance: int = 1


class SearchResponse(BaseModel):
    query: str
    count: int
    results: List[SearchResult] = Field(default_factory=list)


def _truncate_match(text: Optional[str], query: str, max_len: int = 120) -> Optional[str]:
    """Extract a context window around the query match."""
    if not text:
        return None
    lower = text.lower()
    idx = lower.find(query.lower())
    if idx == -1:
        return text[:max_len] + ("..." if len(text) > max_len else "")
    start = max(0, idx - 40)
    end = min(len(text), idx + len(query) + 80)
    excerpt = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
    return excerpt


@router.get("/search", response_model=SearchResponse)
async def global_search(
    q: str = Query(..., min_length=2, description="Search query (min 2 chars)"),
    type: Optional[str] = Query(None, description="Filter by type: task, session"),
    limit: int = Query(30, ge=1, le=100, description="Max results"),
):
    """Global search across tasks and sessions.

    Searches task descriptions and session metadata in SQLite.
    Results ranked by relevance (title match > content match) then recency.
    """
    exec_user = getattr(settings, "exec_user", None) or "default"
    queue = get_task_queue(exec_user)
    results: List[SearchResult] = []
    query_lower = q.lower()

    # ── Search tasks ──
    if not type or type == "task":
        try:
            tasks, _total = queue.list_tasks(page=1, page_size=200, search=q)
            for t in tasks[:limit]:
                title = t.description or t.id
                subtitle_parts = [t.status or ""]
                if t.provider:
                    subtitle_parts.append(t.provider)
                if t.project_id:
                    subtitle_parts.append(t.project_id)

                relevance = 2 if query_lower in (t.description or "").lower()[:50] else 1
                results.append(SearchResult(
                    type="task",
                    id=t.id,
                    title=title[:120],
                    subtitle=" · ".join(filter(None, subtitle_parts)),
                    excerpt=_truncate_match(t.description, q),
                    created_at=t.created_at.isoformat() if hasattr(t.created_at, "isoformat") else str(t.created_at) if t.created_at else None,
                    relevance=relevance,
                ))
        except Exception as e:
            logger.warning(f"Task search failed: {e}")

    # ── Search sessions ──
    if not type or type == "session":
        try:
            from src.runtime.stores.db import get_db
            db = get_db()
            # Search in core_sessions table (created by session_storage migration)
            for table in ("core_sessions", "sessions"):
                try:
                    rows = db.execute_fetchall(
                        f"SELECT id, title, provider, username, exec_dir, created_at FROM {table} "
                        f"WHERE title LIKE ? OR id LIKE ? OR provider LIKE ? OR username LIKE ? "
                        f"ORDER BY updated_at DESC LIMIT ?",
                        (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", limit * 2),
                    )
                    for row in rows:
                        session_id = row.get("id", "")
                        title = row.get("title", "")
                        provider = row.get("provider", "")
                        created = row.get("created_at", "")

                        relevance = 2 if query_lower in (title or "").lower()[:50] else 1
                        results.append(SearchResult(
                            type="session",
                            id=session_id,
                            title=title[:120] if title else f"Session {session_id[:8]}",
                            subtitle=provider or "",
                            excerpt=_truncate_match(title, q) if title else None,
                            created_at=str(created) if created else None,
                            relevance=relevance,
                        ))
                    if rows:
                        break  # Got results from one table, no need to try the other
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Session search failed: {e}")

    # Sort: relevance desc, then recency
    results.sort(key=lambda r: (-r.relevance, -(r.created_at or "").__hash__()))
    results = results[:limit]

    return SearchResponse(query=q, count=len(results), results=results)


# ═══════════════════════════════════════════════════════════════════════════
# Data Cleanup / Retention
# ═══════════════════════════════════════════════════════════════════════════

# Default retention periods (days). 0 = keep forever.
DEFAULT_RETENTION = {
    "tasks_done": 90,
    "tasks_failed": 30,
    "sessions": 60,
}


class RetentionTarget(BaseModel):
    category: str
    retention_days: int
    cutoff_date: str
    stale_count: int
    note: str = ""


class CleanupPreview(BaseModel):
    retention: Dict[str, int]
    preview: List[RetentionTarget]
    total_stale: int


class CleanupResult(BaseModel):
    deleted: Dict[str, int]
    total_deleted: int
    duration_ms: int


def _get_retention() -> Dict[str, int]:
    """Read retention config from env or use defaults."""
    return {
        "tasks_done": int(os.environ.get("RETENTION_TASKS_DONE_DAYS", DEFAULT_RETENTION["tasks_done"])),
        "tasks_failed": int(os.environ.get("RETENTION_TASKS_FAILED_DAYS", DEFAULT_RETENTION["tasks_failed"])),
        "sessions": int(os.environ.get("RETENTION_SESSIONS_DAYS", DEFAULT_RETENTION["sessions"])),
    }


def _count_stale_sessions(cutoff_ms: int) -> int:
    """Count sessions older than cutoff (cutoff in ms timestamp)."""
    try:
        from src.runtime.stores.db import get_db
        db = get_db()
        for table in ("core_sessions", "sessions"):
            try:
                row = db.execute_fetchone(
                    f"SELECT COUNT(*) as cnt FROM {table} WHERE created_at < ?",
                    (cutoff_ms,),
                )
                if row:
                    return row["cnt"]
            except Exception:
                continue
    except Exception:
        pass
    return 0


def _delete_stale_sessions(cutoff_ms: int) -> int:
    """Delete sessions older than cutoff (cutoff in ms timestamp). Returns count."""
    try:
        from src.runtime.stores.db import get_db
        db = get_db()
        count = 0
        for table in ("core_sessions", "sessions"):
            try:
                # Get stale session IDs first
                rows = db.execute_fetchall(
                    f"SELECT id FROM {table} WHERE created_at < ?",
                    (cutoff_ms,),
                )
                if not rows:
                    continue
                ids = [r["id"] for r in rows]
                count = len(ids)
                # Delete associated data
                msg_table = table.replace("sessions", "session_messages")
                tc_table = table.replace("sessions", "session_tool_calls")
                ev_table = table.replace("sessions", "session_events")
                st_table = table.replace("sessions", "session_streaming")
                with db.transaction() as conn:
                    placeholders = ",".join("?" * len(ids))
                    for dep_table in (msg_table, tc_table, ev_table, st_table):
                        try:
                            conn.execute(
                                f"DELETE FROM {dep_table} WHERE session_id IN ({placeholders})",
                                ids,
                            )
                        except Exception:
                            pass
                    conn.execute(
                        f"DELETE FROM {table} WHERE id IN ({placeholders})",
                        ids,
                    )
                return count
            except Exception:
                continue
    except Exception:
        pass
    return 0


def _preview_cleanup(exec_user: str) -> CleanupPreview:
    """Scan SQLite for stale items without deleting anything."""
    retention = _get_retention()
    now = time.time()
    preview: List[RetentionTarget] = []

    queue = get_task_queue(exec_user)

    # ── Stale done tasks ──
    days = retention["tasks_done"]
    if days > 0:
        cutoff = now - days * 86400
        cutoff_date = time.strftime("%Y-%m-%d", time.gmtime(cutoff))
        stale = 0
        try:
            tasks, _ = queue.list_tasks(page=1, page_size=500, status="done")
            for t in tasks:
                completed_at = getattr(t, "completed_at", None)
                if completed_at:
                    ts = completed_at.timestamp() if hasattr(completed_at, "timestamp") else float(completed_at)
                    if ts < cutoff:
                        stale += 1
        except Exception:
            pass
        preview.append(RetentionTarget(
            category="Completed tasks",
            retention_days=days,
            cutoff_date=cutoff_date,
            stale_count=stale,
        ))

    # ── Stale failed tasks ──
    days = retention["tasks_failed"]
    if days > 0:
        cutoff = now - days * 86400
        cutoff_date = time.strftime("%Y-%m-%d", time.gmtime(cutoff))
        stale = 0
        try:
            tasks, _ = queue.list_tasks(page=1, page_size=500, status="failed")
            for t in tasks:
                completed_at = getattr(t, "completed_at", None)
                if completed_at:
                    ts = completed_at.timestamp() if hasattr(completed_at, "timestamp") else float(completed_at)
                    if ts < cutoff:
                        stale += 1
        except Exception:
            pass
        preview.append(RetentionTarget(
            category="Failed tasks",
            retention_days=days,
            cutoff_date=cutoff_date,
            stale_count=stale,
        ))

    # ── Stale sessions ──
    days = retention["sessions"]
    if days > 0:
        cutoff = now - days * 86400
        cutoff_date = time.strftime("%Y-%m-%d", time.gmtime(cutoff))
        # created_at is stored as ms timestamp
        cutoff_ms = int(cutoff * 1000)
        stale = _count_stale_sessions(cutoff_ms)
        preview.append(RetentionTarget(
            category="Sessions",
            retention_days=days,
            cutoff_date=cutoff_date,
            stale_count=stale,
        ))

    total_stale = sum(t.stale_count for t in preview)
    return CleanupPreview(retention=retention, preview=preview, total_stale=total_stale)


@router.get("/cleanup", response_model=CleanupPreview)
async def cleanup_preview():
    """Preview what data would be cleaned up based on retention policies."""
    exec_user = getattr(settings, "exec_user", None) or "default"
    return _preview_cleanup(exec_user)


@router.post("/cleanup", response_model=CleanupResult)
async def execute_cleanup(
    dry_run: bool = Query(False, description="If true, only preview without deleting"),
):
    """Execute data cleanup based on retention policies."""
    start = time.time()
    exec_user = getattr(settings, "exec_user", None) or "default"
    retention = _get_retention()
    now = time.time()
    deleted: Dict[str, int] = {}

    queue = get_task_queue(exec_user)

    # ── Clean done tasks ──
    days = retention["tasks_done"]
    count = 0
    if days > 0:
        cutoff = now - days * 86400
        try:
            tasks, _ = queue.list_tasks(page=1, page_size=500, status="done")
            for t in tasks:
                completed_at = getattr(t, "completed_at", None)
                if completed_at:
                    ts = completed_at.timestamp() if hasattr(completed_at, "timestamp") else float(completed_at)
                    if ts < cutoff:
                        if not dry_run:
                            try:
                                queue.delete_task(t.id)
                            except Exception:
                                pass
                        count += 1
        except Exception:
            pass
    deleted["tasks_done"] = count

    # ── Clean failed tasks ──
    days = retention["tasks_failed"]
    count = 0
    if days > 0:
        cutoff = now - days * 86400
        try:
            tasks, _ = queue.list_tasks(page=1, page_size=500, status="failed")
            for t in tasks:
                completed_at = getattr(t, "completed_at", None)
                if completed_at:
                    ts = completed_at.timestamp() if hasattr(completed_at, "timestamp") else float(completed_at)
                    if ts < cutoff:
                        if not dry_run:
                            try:
                                queue.delete_task(t.id)
                            except Exception:
                                pass
                        count += 1
        except Exception:
            pass
    deleted["tasks_failed"] = count

    # ── Clean sessions ──
    days = retention["sessions"]
    count = 0
    if days > 0:
        cutoff = now - days * 86400
        cutoff_ms = int(cutoff * 1000)
        if dry_run:
            count = _count_stale_sessions(cutoff_ms)
        else:
            count = _delete_stale_sessions(cutoff_ms)
    deleted["sessions"] = count

    duration_ms = int((time.time() - start) * 1000)
    total_deleted = sum(deleted.values())

    if not dry_run and total_deleted > 0:
        logger.info(f"Cleanup completed: {deleted} in {duration_ms}ms")

    return CleanupResult(deleted=deleted, total_deleted=total_deleted, duration_ms=duration_ms)

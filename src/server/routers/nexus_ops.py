# -*- coding: utf-8 -*-
"""Global search and data cleanup/retention endpoints.

Ported from mission-control:
  - GET /api/search       (search/route.ts) — global search
  - GET /api/cleanup      (cleanup/route.ts) — retention preview
  - POST /api/cleanup     (cleanup/route.ts) — execute cleanup

Adapted for agent-nexus: Redis-backed search across tasks and sessions,
configurable retention policies.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from ..services.redis_client import get_redis_client
from ..services.task_storage import TaskQueue
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

    Ported from mission-control GET /api/search (search/route.ts).
    Searches task descriptions, session messages, and metadata in Redis.
    Results ranked by relevance (title match > content match) then recency.
    """
    exec_user = getattr(settings, "exec_user", None) or "default"
    queue = TaskQueue(db_path=None, exec_user=exec_user)
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
            rc = get_redis_client()
            r = rc.client
            prefix = os.environ.get("REDIS_KEY_PREFIX", "aona:")

            # Scan session keys
            pattern = f"{prefix}session:*:meta"
            cursor = 0
            session_count = 0
            while session_count < limit * 2:  # scan more than needed for filtering
                cursor, keys = r.scan(cursor, match=pattern, count=200)
                for key in keys:
                    try:
                        raw = r.get(key)
                        if not raw:
                            continue
                        meta = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                        session_id = meta.get("session_id", "")
                        provider = meta.get("provider", "")
                        description = meta.get("description", "")
                        exec_user_s = meta.get("exec_user", "")
                        workspace = meta.get("workspace", "")
                        created = meta.get("created_at", "")

                        searchable = f"{session_id} {provider} {description} {exec_user_s} {workspace}".lower()
                        if query_lower in searchable:
                            relevance = 2 if query_lower in (description or "").lower()[:50] else 1
                            results.append(SearchResult(
                                type="session",
                                id=session_id,
                                title=description[:120] if description else f"Session {session_id[:8]}",
                                subtitle=f"{provider}" + (f" · {workspace}" if workspace else ""),
                                excerpt=_truncate_match(description, q) if description else None,
                                created_at=created if created else None,
                                relevance=relevance,
                            ))
                            session_count += 1
                    except Exception:
                        continue
                if cursor == 0:
                    break
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


def _preview_cleanup(exec_user: str) -> CleanupPreview:
    """Scan Redis for stale items without deleting anything."""
    retention = _get_retention()
    now = time.time()
    preview: List[RetentionTarget] = []

    queue = TaskQueue(db_path=None, exec_user=exec_user)

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
        stale = 0
        try:
            rc = get_redis_client()
            r = rc.client
            prefix = os.environ.get("REDIS_KEY_PREFIX", "aona:")
            pattern = f"{prefix}session:*:meta"
            cursor = 0
            while True:
                cursor, keys = r.scan(cursor, match=pattern, count=200)
                for key in keys:
                    try:
                        raw = r.get(key)
                        if not raw:
                            continue
                        meta = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                        created = meta.get("created_at", "")
                        if created:
                            from datetime import datetime
                            if isinstance(created, str):
                                try:
                                    ts = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                                except Exception:
                                    continue
                            else:
                                ts = float(created)
                            if ts < cutoff:
                                stale += 1
                    except Exception:
                        continue
                if cursor == 0:
                    break
        except Exception:
            pass
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
    """Preview what data would be cleaned up based on retention policies.

    Ported from mission-control GET /api/cleanup (cleanup/route.ts).
    Shows stale task/session counts without deleting anything.
    Configure retention via RETENTION_TASKS_DONE_DAYS, RETENTION_TASKS_FAILED_DAYS,
    RETENTION_SESSIONS_DAYS environment variables.
    """
    exec_user = getattr(settings, "exec_user", None) or "default"
    return _preview_cleanup(exec_user)


@router.post("/cleanup", response_model=CleanupResult)
async def execute_cleanup(
    dry_run: bool = Query(False, description="If true, only preview without deleting"),
):
    """Execute data cleanup based on retention policies.

    Ported from mission-control POST /api/cleanup (cleanup/route.ts).
    Deletes tasks and sessions older than their retention window.
    Use dry_run=true to preview first.
    """
    start = time.time()
    exec_user = getattr(settings, "exec_user", None) or "default"
    retention = _get_retention()
    now = time.time()
    deleted: Dict[str, int] = {}

    queue = TaskQueue(db_path=None, exec_user=exec_user)

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
        try:
            rc = get_redis_client()
            r = rc.client
            prefix = os.environ.get("REDIS_KEY_PREFIX", "aona:")
            pattern = f"{prefix}session:*:meta"
            cursor = 0
            stale_keys: List[str] = []
            while True:
                cursor, keys = r.scan(cursor, match=pattern, count=200)
                for key in keys:
                    try:
                        raw = r.get(key)
                        if not raw:
                            continue
                        meta = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                        created = meta.get("created_at", "")
                        if created:
                            from datetime import datetime
                            if isinstance(created, str):
                                try:
                                    ts = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                                except Exception:
                                    continue
                            else:
                                ts = float(created)
                            if ts < cutoff:
                                stale_keys.append(key)
                    except Exception:
                        continue
                if cursor == 0:
                    break

            if not dry_run and stale_keys:
                # Delete session meta and associated data
                for meta_key in stale_keys:
                    try:
                        # meta_key is like "aona:session:{id}:meta"
                        # Also delete messages, files etc.
                        base = meta_key.rsplit(":meta", 1)[0]
                        keys_to_del = [meta_key]
                        # Scan for related session keys
                        for related in r.scan_iter(match=f"{base}:*", count=100):
                            keys_to_del.append(related)
                        if keys_to_del:
                            r.delete(*keys_to_del)
                    except Exception:
                        pass
            count = len(stale_keys)
        except Exception:
            pass
    deleted["sessions"] = count

    duration_ms = int((time.time() - start) * 1000)
    total_deleted = sum(deleted.values())

    if not dry_run and total_deleted > 0:
        logger.info(f"Cleanup completed: {deleted} in {duration_ms}ms")

    return CleanupResult(deleted=deleted, total_deleted=total_deleted, duration_ms=duration_ms)

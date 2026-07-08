# -*- coding: utf-8 -*-
"""Natural language schedule parser and data export endpoints.

Ported from mission-control:
  - GET /api/schedule-parse  (lib/schedule-parser.ts) — NL → cron
  - GET /api/export          (api/export/route.ts)    — data export

Adapted for agent-nexus: zero-dependency regex parser, Redis-backed export.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from ..services.task_storage import get_task_queue
from .nexus_auth import verify_nexus_auth

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-utils"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ═══════════════════════════════════════════════════════════════════════════
# Slash Commands Listing
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/commands")
async def list_slash_commands():
    """Return all registered slash commands with metadata."""
    try:
        from src.runtime.commands.slash.parser import get_known_slash_commands
        from src.runtime.commands.slash.handler import _ensure_slash_extensions_loaded

        _ensure_slash_extensions_loaded()
        known = get_known_slash_commands()

        # Build description map from the static SLASH_COMMANDS list context
        descriptions = {
            "/task": "Create and manage tasks",
            "/check": "Check task status",
            "/usage": "Show resource usage",
            "/report": "Generate reports",
            "/cancel": "Cancel running operations",
            "/trash": "Manage trashed items",
            "/clear": "Clear conversation history",
            "/help": "Show available commands",
            "/chat": "Chat with an agent",
            "/workspace": "Manage workspaces",
            "/config": "View or update configuration",
            "/switch": "Switch context or provider",
            "/history": "View command history",
            "/worktree": "Manage git worktrees",
            "/exit": "Exit the current session",
        }

        result = []
        for cmd in known:
            name = cmd.lstrip("/")
            result.append({
                "name": name,
                "description": descriptions.get(cmd, ""),
            })
        return result
    except Exception as e:
        logger.warning(f"Failed to list slash commands: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# Schedule Parser (ported from lib/schedule-parser.ts)
# ═══════════════════════════════════════════════════════════════════════════

DAY_MAP: Dict[str, int] = {
    "sunday": 0, "sun": 0,
    "monday": 1, "mon": 1,
    "tuesday": 2, "tue": 2,
    "wednesday": 3, "wed": 3,
    "thursday": 4, "thu": 4,
    "friday": 5, "fri": 5,
    "saturday": 6, "sat": 6,
}

CRON_REGEX = re.compile(
    r"^(\*(?:/\d+)?|[\d,\-/]+)\s+(\*(?:/\d+)?|[\d,\-/]+)\s+(\*(?:/\d+)?|[\d,\-/]+)\s+(\*(?:/\d+)?|[\d,\-/]+)\s+(\*(?:/\d+)?|[\d,\-/]+)$"
)


class ParsedSchedule(BaseModel):
    cron_expr: str = Field(..., alias="cronExpr")
    human_readable: str = Field(..., alias="humanReadable")

    model_config = {"populate_by_name": True}


def _parse_time_expr(text: str) -> Optional[Dict[str, int]]:
    """Parse time like '9am', '9:30pm', '14:00', '9'."""
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", text.strip(), re.IGNORECASE)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    ampm = (m.group(3) or "").lower()

    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return {"hour": hour, "minute": minute}


def _format_time(hour: int, minute: int) -> str:
    """Format hour/minute as human-readable."""
    label = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    display_min = f":{minute:02d}" if minute > 0 else ""
    return f"{display_hour}{display_min} {label}"


def parse_natural_schedule(text: str) -> Optional[ParsedSchedule]:
    """Convert natural language schedule to cron expression.

    Ported from mission-control lib/schedule-parser.ts.
    Zero dependencies — regex-based pattern matching.
    """
    text = text.strip()
    if not text:
        return None

    # Raw cron passthrough
    if CRON_REGEX.match(text):
        return ParsedSchedule(cronExpr=text, humanReadable=f"Custom schedule ({text})")

    lower = text.lower()

    # "hourly"
    if lower == "hourly":
        return ParsedSchedule(cronExpr="0 * * * *", humanReadable="Every hour")

    # "daily" / "every day"
    if lower in ("daily", "every day"):
        return ParsedSchedule(cronExpr="0 9 * * *", humanReadable="Daily at 9:00 AM")

    # "weekly"
    if lower == "weekly":
        return ParsedSchedule(cronExpr="0 9 * * 1", humanReadable="Weekly on Monday at 9:00 AM")

    # "every N minutes"
    m = re.match(r"^every\s+(\d+)\s+minutes?$", lower)
    if m:
        n = int(m.group(1))
        if 0 < n <= 59:
            return ParsedSchedule(
                cronExpr=f"*/{n} * * * *",
                humanReadable=f"Every {n} minute{'s' if n > 1 else ''}",
            )

    # "every N hours"
    m = re.match(r"^every\s+(\d+)\s+hours?$", lower)
    if m:
        n = int(m.group(1))
        if 0 < n <= 23:
            return ParsedSchedule(
                cronExpr=f"0 */{n} * * *",
                humanReadable=f"Every {n} hour{'s' if n > 1 else ''}",
            )

    # "every morning/evening/day at TIME" / "daily at TIME"
    m = re.match(r"^(?:every\s+(?:morning|evening|day)|daily)\s+at\s+(.+)$", lower)
    if m:
        t = _parse_time_expr(m.group(1))
        if t:
            return ParsedSchedule(
                cronExpr=f"{t['minute']} {t['hour']} * * *",
                humanReadable=f"Daily at {_format_time(t['hour'], t['minute'])}",
            )

    # "at TIME every day"
    m = re.match(r"^at\s+(.+?)\s+every\s+day$", lower)
    if m:
        t = _parse_time_expr(m.group(1))
        if t:
            return ParsedSchedule(
                cronExpr=f"{t['minute']} {t['hour']} * * *",
                humanReadable=f"Daily at {_format_time(t['hour'], t['minute'])}",
            )

    # "weekly on DAYNAME" / "every DAYNAME"
    m = re.match(r"^(?:weekly\s+on|every)\s+(\w+)$", lower)
    if m:
        day_num = DAY_MAP.get(m.group(1))
        if day_num is not None:
            day_name = m.group(1).capitalize()
            return ParsedSchedule(
                cronExpr=f"0 9 * * {day_num}",
                humanReadable=f"Weekly on {day_name} at 9:00 AM",
            )

    # "every DAYNAME at TIME"
    m = re.match(r"^every\s+(\w+)\s+at\s+(.+)$", lower)
    if m:
        day_num = DAY_MAP.get(m.group(1))
        if day_num is not None:
            t = _parse_time_expr(m.group(2))
            if t:
                day_name = m.group(1).capitalize()
                return ParsedSchedule(
                    cronExpr=f"{t['minute']} {t['hour']} * * {day_num}",
                    humanReadable=f"Every {day_name} at {_format_time(t['hour'], t['minute'])}",
                )

    return None


@router.get("/schedule-parse")
async def schedule_parse(
    input: str = Query(..., min_length=1, description="Natural language schedule or raw cron"),
):
    """Parse natural language schedule into a cron expression.

    Ported from mission-control GET /api/schedule-parse (lib/schedule-parser.ts).

    Examples:
      - "every 5 minutes" → */5 * * * *
      - "daily at 9am" → 0 9 * * *
      - "every monday at 2:30pm" → 30 14 * * 1
      - "hourly" → 0 * * * *
      - "0 9 * * 1-5" → passthrough (raw cron)
    """
    result = parse_natural_schedule(input)
    if result is None:
        return {"error": "Could not parse schedule expression", "input": input}
    return result.model_dump(by_alias=True)


# ═══════════════════════════════════════════════════════════════════════════
# Data Export (ported from api/export/route.ts)
# ═══════════════════════════════════════════════════════════════════════════

EXPORT_TYPES = ("tasks", "sessions")


@router.get("/export")
async def export_data(
    type: str = Query(..., description="Export type: tasks, sessions"),
    format: str = Query("json", description="Output format: json, csv"),
    since: Optional[int] = Query(None, description="Unix timestamp — only export items created after this time"),
    until: Optional[int] = Query(None, description="Unix timestamp — only export items created before this time"),
    limit: int = Query(10000, ge=1, le=50000, description="Max records"),
):
    """Export tasks or sessions as JSON or CSV.

    Ported from mission-control GET /api/export (api/export/route.ts).
    """
    if type not in EXPORT_TYPES:
        return {"error": f"type required: {', '.join(EXPORT_TYPES)}"}

    exec_user = getattr(settings, "exec_user", None) or "default"
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    rows: List[Dict[str, Any]] = []

    if type == "tasks":
        queue = get_task_queue(exec_user)
        try:
            tasks, _ = queue.list_tasks(page=1, page_size=min(limit, 500))
            for t in tasks:
                created_ts = None
                if t.created_at:
                    created_ts = t.created_at.timestamp() if hasattr(t.created_at, "timestamp") else float(t.created_at)

                # Apply time filters
                if since and created_ts and created_ts < since:
                    continue
                if until and created_ts and created_ts > until:
                    continue

                rows.append({
                    "id": t.id,
                    "description": t.description or "",
                    "status": t.status or "",
                    "priority": t.priority or "",
                    "provider": t.provider or "",
                    "project_id": t.project_id or "",
                    "workspace": getattr(t, "workspace", "") or "",
                    "exec_user": t.exec_user or "",
                    "created_at": str(t.created_at) if t.created_at else "",
                    "completed_at": str(t.completed_at) if t.completed_at else "",
                    "attempt_count": getattr(t, "attempt_count", 0),
                })
        except Exception as e:
            logger.warning(f"Export tasks failed: {e}")

    elif type == "sessions":
        try:
            from src.runtime.stores.db import get_db
            db = get_db()
            # Try core_sessions first, then sessions
            for table in ("core_sessions", "sessions"):
                try:
                    session_rows = db.execute_fetchall(
                        f"SELECT id, provider, title, username, exec_dir, created_at, status "
                        f"FROM {table} ORDER BY updated_at DESC LIMIT ?",
                        (limit,),
                    )
                    for sr in session_rows:
                        created = sr.get("created_at", "")
                        created_ts = None
                        if created:
                            try:
                                created_ts = float(created) / 1000.0  # ms -> seconds
                            except Exception:
                                pass

                        if since and created_ts and created_ts < since:
                            continue
                        if until and created_ts and created_ts > until:
                            continue

                        rows.append({
                            "session_id": sr.get("id", ""),
                            "provider": sr.get("provider", ""),
                            "description": sr.get("title", ""),
                            "exec_user": sr.get("username", ""),
                            "workspace": sr.get("exec_dir", ""),
                            "created_at": str(created) if created else "",
                            "status": sr.get("status", ""),
                        })
                    if session_rows:
                        break
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Export sessions failed: {e}")

    rows = rows[:limit]

    if format == "csv":
        if not rows:
            return Response(content="", media_type="text/csv",
                          headers={"Content-Disposition": f'attachment; filename="{type}-export.csv"'})
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{type}-export.csv"'},
        )

    return {
        "type": type,
        "exported_at": now_iso,
        "count": len(rows),
        "data": rows,
    }

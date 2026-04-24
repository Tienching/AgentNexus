# -*- coding: utf-8 -*-
"""Domain event backbone for control-plane state changes.

Provides a light-weight, SQLite-backed event log that can be queried by
aggregate type/id, workspace, tenant, or runtime. The service is intentionally
generic so task/session/runtime/cost pipelines can all write to the same
read-model without introducing new infrastructure dependencies.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.runtime.stores.db import Database, get_db


@dataclass
class DomainEvent:
    id: Optional[int] = None
    event_type: str = ""
    aggregate_type: str = ""
    aggregate_id: str = ""
    actor: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    workspace_id: Optional[str] = None
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    runtime_id: Optional[str] = None
    task_id: Optional[str] = None
    cost_usd: Optional[float] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "actor": self.actor,
            "payload": self.payload,
            "workspace_id": self.workspace_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "runtime_id": self.runtime_id,
            "task_id": self.task_id,
            "cost_usd": self.cost_usd,
            "created_at": self.created_at,
        }


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS domain_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type      TEXT NOT NULL,
    aggregate_type  TEXT NOT NULL,
    aggregate_id    TEXT NOT NULL,
    actor           TEXT NOT NULL DEFAULT '',
    payload_json    TEXT NOT NULL DEFAULT '{}',
    workspace_id    TEXT,
    tenant_id       TEXT,
    session_id      TEXT,
    runtime_id      TEXT,
    task_id         TEXT,
    cost_usd        REAL,
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_domain_events_aggregate
    ON domain_events(aggregate_type, aggregate_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_domain_events_workspace
    ON domain_events(workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_domain_events_tenant
    ON domain_events(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_domain_events_session
    ON domain_events(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_domain_events_runtime
    ON domain_events(runtime_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_domain_events_task
    ON domain_events(task_id, created_at DESC);
"""

_schema_ready_paths: set[str] = set()


def _ensure_schema(db: Database) -> None:
    db_path = str(getattr(db, "db_path", ""))
    if db_path in _schema_ready_paths:
        return
    try:
        with db.transaction() as conn:
            conn.executescript(_SCHEMA_SQL)
        _schema_ready_paths.add(db_path)
    except Exception:
        # Best-effort: continue even if the table already exists but was created
        # by a concurrent process or older migration.
        _schema_ready_paths.add(db_path)


def record_domain_event(
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    *,
    actor: str = "",
    payload: Optional[Dict[str, Any]] = None,
    workspace_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    session_id: Optional[str] = None,
    runtime_id: Optional[str] = None,
    task_id: Optional[str] = None,
    cost_usd: Optional[float] = None,
) -> Optional[DomainEvent]:
    """Persist a domain event. Never raises."""
    try:
        db = get_db()
        _ensure_schema(db)
        evt = DomainEvent(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor=actor or "",
            payload=payload or {},
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            session_id=session_id,
            runtime_id=runtime_id,
            task_id=task_id,
            cost_usd=cost_usd,
        )
        with db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO domain_events (
                    event_type, aggregate_type, aggregate_id, actor, payload_json,
                    workspace_id, tenant_id, session_id, runtime_id, task_id,
                    cost_usd, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evt.event_type,
                    evt.aggregate_type,
                    evt.aggregate_id,
                    evt.actor,
                    json.dumps(evt.payload, ensure_ascii=False),
                    evt.workspace_id,
                    evt.tenant_id,
                    evt.session_id,
                    evt.runtime_id,
                    evt.task_id,
                    evt.cost_usd,
                    evt.created_at,
                ),
            )
            evt.id = cursor.lastrowid
        try:
            from src.server.services import get_event_bus

            get_event_bus().broadcast("domain_event.created", evt.to_dict())
        except Exception:
            pass
        return evt
    except Exception:
        return None


def query_domain_events(
    *,
    aggregate_type: Optional[str] = None,
    aggregate_id: Optional[str] = None,
    event_type: Optional[str] = None,
    workspace_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    session_id: Optional[str] = None,
    runtime_id: Optional[str] = None,
    task_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[DomainEvent]:
    """Query persisted domain events newest-first."""
    db = get_db()
    _ensure_schema(db)

    conditions: List[str] = []
    params: List[Any] = []
    if aggregate_type:
        conditions.append("aggregate_type = ?")
        params.append(aggregate_type)
    if aggregate_id:
        conditions.append("aggregate_id = ?")
        params.append(aggregate_id)
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if workspace_id:
        conditions.append("workspace_id = ?")
        params.append(workspace_id)
    if tenant_id:
        conditions.append("tenant_id = ?")
        params.append(tenant_id)
    if session_id:
        conditions.append("session_id = ?")
        params.append(session_id)
    if runtime_id:
        conditions.append("runtime_id = ?")
        params.append(runtime_id)
    if task_id:
        conditions.append("task_id = ?")
        params.append(task_id)

    where = " AND ".join(conditions) if conditions else "1=1"
    rows = db.execute_fetchall(
        f"SELECT * FROM domain_events WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params + [limit, offset]),
    )
    out: List[DomainEvent] = []
    for row in rows:
        payload = {}
        if row.get("payload_json"):
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                payload = {}
        out.append(
            DomainEvent(
                id=row.get("id"),
                event_type=row.get("event_type", ""),
                aggregate_type=row.get("aggregate_type", ""),
                aggregate_id=row.get("aggregate_id", ""),
                actor=row.get("actor", ""),
                payload=payload,
                workspace_id=row.get("workspace_id"),
                tenant_id=row.get("tenant_id"),
                session_id=row.get("session_id"),
                runtime_id=row.get("runtime_id"),
                task_id=row.get("task_id"),
                cost_usd=row.get("cost_usd"),
                created_at=row.get("created_at", time.time()),
            )
        )
    return out


def count_domain_events(**filters: Any) -> int:
    """Count events matching the provided filters."""
    db = get_db()
    _ensure_schema(db)

    conditions: List[str] = []
    params: List[Any] = []
    for key, column in (
        ("aggregate_type", "aggregate_type"),
        ("aggregate_id", "aggregate_id"),
        ("event_type", "event_type"),
        ("workspace_id", "workspace_id"),
        ("tenant_id", "tenant_id"),
        ("session_id", "session_id"),
        ("runtime_id", "runtime_id"),
        ("task_id", "task_id"),
    ):
        value = filters.get(key)
        if value:
            conditions.append(f"{column} = ?")
            params.append(value)

    where = " AND ".join(conditions) if conditions else "1=1"
    row = db.execute_fetchone(
        f"SELECT COUNT(*) AS cnt FROM domain_events WHERE {where}",
        tuple(params),
    )
    return int(row["cnt"]) if row else 0

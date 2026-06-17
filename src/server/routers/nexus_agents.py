# -*- coding: utf-8 -*-
"""Agent Lifecycle Management API.

Endpoints:
  - POST /api/nexus/agents/register    — Register a new agent
  - POST /api/nexus/agents/{id}/heartbeat — Record a heartbeat
  - GET  /api/nexus/agents              — List registered agents
  - GET  /api/nexus/agents/{id}         — Get agent details
  - PATCH /api/nexus/agents/{id}/status — Update agent status
  - DELETE /api/nexus/agents/{id}       — Deregister an agent
  - GET  /api/nexus/agents/stats        — Agent count by status
"""

from __future__ import annotations

import time
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from .nexus_auth import verify_nexus_auth
from .nexus_models import (
    AgentInfo,
    AgentBindingItem,
    AgentBindingUpdateRequest,
    AgentOverviewActivityItem,
    AgentOverviewSummary,
    AgentsOverviewResponse,
)

logger = get_logger(__name__)

_AGENT_BINDINGS: dict[str, dict] = {}

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-agents"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AgentRegisterRequest(BaseModel):
    name: str = Field(..., description="Agent name", min_length=1, max_length=100)
    provider: str = Field(..., description="Provider name (e.g. claude, gemini)")
    workspace: str = Field("", description="Working directory")
    capabilities: List[str] = Field(default_factory=list, description="Agent capabilities")
    model: str = Field("", description="Model identifier")
    alias: str = Field("", description="Provider alias")
    metadata: dict = Field(default_factory=dict, description="Extra metadata")


class AgentHeartbeatRequest(BaseModel):
    status: Optional[str] = Field(None, description="Optional status update (idle, running, error)")


class AgentStatusUpdateRequest(BaseModel):
    status: str = Field(..., description="New status: idle, running, error, offline")


class AgentResponse(BaseModel):
    id: str
    name: str
    provider: str
    status: str
    last_heartbeat: float
    workspace: str
    capabilities: List[str]
    model: str
    alias: str
    registered_at: float
    metadata: dict


class AgentListResponse(BaseModel):
    agents: List[AgentResponse]
    total: int


class AgentStatsResponse(BaseModel):
    counts: dict
    total: int


def _normalize_breakdown_item(entry: Any) -> dict[str, Any]:
    if hasattr(entry, "model_dump"):
        return dict(entry.model_dump())
    if hasattr(entry, "dict"):
        return dict(entry.dict())
    return dict(entry or {})


def _usage_payload(entry: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    item = dict(entry or {})
    return {
        "total_cost_usd": float(item.get("total_cost_usd", item.get("cost_usd", item.get("cost", 0.0))) or 0.0),
        "total_tokens": int(item.get("total_tokens", item.get("tokens", 0)) or 0),
        "request_count": int(item.get("count", item.get("request_count", 0)) or 0),
    }


def _identity_payload(*, title: str, subtitle: str = "", provider: str = "", alias: str = "", owner: str = "", role: str = "", external_id: str = "") -> dict[str, Any]:
    return {
        "title": title,
        "subtitle": subtitle,
        "provider": provider,
        "alias": alias,
        "owner": owner,
        "role": role,
        "external_id": external_id,
    }


def _runtime_payload(
    *,
    status: str = "",
    workspace: str = "",
    model: str = "",
    runtime_profile: str = "default",
    last_heartbeat: Optional[float] = None,
    registered_at: Optional[float] = None,
    team_name: str = "",
    enabled: bool = True,
    running_agents: int = 0,
    available_tasks: int = 0,
) -> dict[str, Any]:
    return {
        "status": status,
        "workspace": workspace,
        "model": model,
        "runtime_profile": runtime_profile,
        "last_heartbeat": last_heartbeat,
        "registered_at": registered_at,
        "team_name": team_name,
        "enabled": enabled,
        "running_agents": running_agents,
        "available_tasks": available_tasks,
    }


def _memory_payload(scope: str = "session", summary: str = "", entry_count: int = 0, last_updated_at: Optional[float] = None) -> dict[str, Any]:
    return {
        "scope": scope,
        "summary": summary,
        "entry_count": entry_count,
        "last_updated_at": last_updated_at,
    }


def _activity_payload(
    *,
    last_seen_at: Optional[float] = None,
    headline: str = "",
    status: str = "",
    recent_events: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    return {
        "last_seen_at": last_seen_at,
        "headline": headline,
        "status": status,
        "recent_events": list(recent_events or []),
    }


def _binding_defaults(info) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = dict(getattr(info, "metadata", {}) or {})
    persisted = dict(_AGENT_BINDINGS.get(info.id, {}) or {})
    merged_meta = dict(metadata)
    merged_meta.update(dict(persisted.get("metadata", {}) or {}))

    capabilities = list(
        persisted.get("capabilities")
        or persisted.get("tools")
        or merged_meta.get("capabilities")
        or merged_meta.get("tools")
        or info.capabilities
        or []
    )
    memory_scope = (
        persisted.get("memory_scope")
        or persisted.get("memory_policy")
        or merged_meta.get("memory_scope")
        or merged_meta.get("memory_policy")
        or "session"
    )
    binding = {
        "exec_user": persisted.get("exec_user") or merged_meta.get("exec_user") or merged_meta.get("owner") or "",
        "workspace": persisted.get("workspace") or info.workspace or "",
        "provider": persisted.get("provider") or info.provider,
        "alias": persisted.get("alias") or info.alias or info.provider,
        "model": persisted.get("model") or info.model or "",
        "runtime_profile": persisted.get("runtime_profile") or merged_meta.get("runtime_profile") or "default",
        "memory_scope": memory_scope,
        "team_name": persisted.get("team_name") or merged_meta.get("team_name") or "",
        "enabled": bool(persisted.get("enabled", merged_meta.get("enabled", info.status.value != "offline"))),
        "auto_start": bool(persisted.get("auto_start", merged_meta.get("auto_start", False))),
        "notes": str(persisted.get("notes") or merged_meta.get("notes") or ""),
        "capabilities": capabilities,
    }
    return binding, merged_meta


def _build_agent_activity_event(info) -> dict[str, Any]:
    timestamp = getattr(info, "last_heartbeat", None) or getattr(info, "registered_at", None) or time.time()
    return {
        "id": f"agent:{info.id}",
        "title": info.name,
        "subtitle": f"{info.provider} · {info.status.value}",
        "timestamp": timestamp,
        "level": "warning" if info.status.value in {"error", "offline"} else "info",
        "entity_type": "agent",
        "entity_id": info.id,
        "scope": "agent",
        "scope_id": info.id,
        "detail": info.workspace or "",
        "status": info.status.value,
    }


def _get_agent_binding_payload(info, *, cost_row: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    binding, merged_meta = _binding_defaults(info)
    activity_event = _build_agent_activity_event(info)
    usage = _usage_payload(cost_row)
    identity = _identity_payload(
        title=info.name or info.id,
        subtitle=" · ".join([part for part in [binding["provider"], binding["exec_user"] or None] if part]),
        provider=binding["provider"],
        alias=binding["alias"],
        owner=binding["exec_user"],
        role="agent",
        external_id=info.id,
    )
    runtime = _runtime_payload(
        status=info.status.value,
        workspace=binding["workspace"],
        model=binding["model"],
        runtime_profile=binding["runtime_profile"],
        last_heartbeat=getattr(info, "last_heartbeat", None),
        registered_at=getattr(info, "registered_at", None),
        team_name=binding["team_name"],
        enabled=binding["enabled"],
    )
    memory_entries = merged_meta.get("memory_entries") or []
    memory = _memory_payload(
        scope=binding["memory_scope"],
        summary=merged_meta.get("memory_summary") or (f"{len(memory_entries)} memory entries" if memory_entries else "No memory configured"),
        entry_count=len(memory_entries),
        last_updated_at=merged_meta.get("memory_updated_at") or activity_event["timestamp"],
    )
    activity = _activity_payload(
        last_seen_at=activity_event["timestamp"],
        headline=f"{info.name or info.id} is {info.status.value}",
        status=info.status.value,
        recent_events=[activity_event],
    )
    return {
        "agent_id": info.id,
        "provider": binding["provider"],
        "alias": binding["alias"],
        "model": binding["model"],
        "workspace": binding["workspace"],
        "memory_policy": binding["memory_scope"],
        "tools": list(binding["capabilities"]),
        "skills": list(_AGENT_BINDINGS.get(info.id, {}).get("skills") or merged_meta.get("skills") or []),
        "permissions": list(_AGENT_BINDINGS.get(info.id, {}).get("permissions") or merged_meta.get("permissions") or []),
        "metadata": merged_meta,
        "updated_at": _AGENT_BINDINGS.get(info.id, {}).get("updated_at") or getattr(info, "last_heartbeat", None) or time.time(),
        "binding": binding,
        "identity": identity,
        "runtime": runtime,
        "memory": memory,
        "capabilities": list(binding["capabilities"]),
        "activity": activity,
        "cost": usage,
    }


def _summarize_recent_activity(
    *,
    limit: int = 8,
    fallback_events: Optional[list[dict[str, Any]]] = None,
) -> list[AgentOverviewActivityItem]:
    try:
        from src.core.events.activity import get_recent_activities

        items = get_recent_activities(limit=limit)
    except Exception:
        items = []
    results: list[AgentOverviewActivityItem] = []
    for idx, item in enumerate(items):
        payload = item.to_dict() if hasattr(item, "to_dict") else dict(item or {})
        results.append(
            AgentOverviewActivityItem(
                id=str(payload.get("id") or payload.get("event_id") or idx),
                title=str(payload.get("activity_type") or payload.get("event_type") or payload.get("title") or "Activity"),
                subtitle=str(payload.get("summary") or payload.get("message") or payload.get("entity_id") or ""),
                timestamp=payload.get("created_at") or payload.get("timestamp"),
                level=str(payload.get("level") or "info"),
                entity_type=str(payload.get("entity_type") or ""),
                entity_id=str(payload.get("entity_id") or ""),
                scope=str(payload.get("scope") or payload.get("entity_type") or "global"),
                scope_id=str(payload.get("scope_id") or payload.get("entity_id") or ""),
                detail=str(payload.get("detail") or payload.get("message") or ""),
                status=str(payload.get("status") or ""),
            )
        )
    if not results:
        for idx, payload in enumerate(fallback_events or []):
            data = dict(payload or {})
            results.append(
                AgentOverviewActivityItem(
                    id=str(data.get("id") or idx),
                    title=str(data.get("title") or "Activity"),
                    subtitle=str(data.get("subtitle") or ""),
                    timestamp=data.get("timestamp"),
                    level=str(data.get("level") or "info"),
                    entity_type=str(data.get("entity_type") or ""),
                    entity_id=str(data.get("entity_id") or ""),
                    scope=str(data.get("scope") or "global"),
                    scope_id=str(data.get("scope_id") or ""),
                    detail=str(data.get("detail") or ""),
                    status=str(data.get("status") or ""),
                )
            )
    results.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return results[:limit]


def _build_cost_summary_payload() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        from src.core.cost.tracker import get_token_tracker

        tracker = get_token_tracker()
        stats = tracker.get_stats()
        breakdown = tracker.get_attribution_breakdown()
    except Exception:
        stats = None
        breakdown = {"by_workspace": [], "by_agent": [], "by_runtime": []}

    normalized = {
        "by_workspace": [_normalize_breakdown_item(item) for item in breakdown.get("by_workspace", []) or []],
        "by_agent": [_normalize_breakdown_item(item) for item in breakdown.get("by_agent", []) or []],
        "by_runtime": [_normalize_breakdown_item(item) for item in breakdown.get("by_runtime", []) or []],
    }
    payload = {
        "total_requests": int(getattr(stats, "total_requests", 0) or 0),
        "total_prompt_tokens": int(getattr(stats, "total_prompt_tokens", 0) or 0),
        "total_completion_tokens": int(getattr(stats, "total_completion_tokens", 0) or 0),
        "total_tokens": int(getattr(stats, "total_tokens", 0) or 0),
        "total_cost_usd": float(getattr(stats, "total_cost_usd", 0.0) or 0.0),
        "by_workspace": normalized["by_workspace"],
        "by_agent": normalized["by_agent"],
        "by_runtime": normalized["by_runtime"],
    }
    by_agent = {str(item.get("key") or ""): item for item in normalized["by_agent"] if item.get("key")}
    return payload, by_agent


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/agents/register", response_model=AgentResponse, status_code=201)
async def register_agent(req: AgentRegisterRequest):
    """Register a new agent."""
    from ..services.agent_registry import get_registry
    reg = get_registry()
    info = reg.register(
        name=req.name,
        provider=req.provider,
        workspace=req.workspace,
        capabilities=req.capabilities,
        model=req.model,
        alias=req.alias,
        metadata=req.metadata,
    )
    return AgentResponse(**info.to_dict())


@router.post("/agents/{agent_id}/heartbeat", response_model=AgentResponse)
async def agent_heartbeat(agent_id: str, req: AgentHeartbeatRequest):
    """Record a heartbeat for an agent."""
    from ..services.agent_registry import get_registry
    from ..services.agent_registry import AgentState

    reg = get_registry()
    status = None
    if req.status:
        try:
            status = AgentState(req.status)
        except ValueError:
            raise HTTPException(400, detail=f"Invalid status: {req.status}")

    info = reg.heartbeat(agent_id, status=status)
    if not info:
        raise HTTPException(404, detail=f"Agent not found: {agent_id}")
    return AgentResponse(**info.to_dict())


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    status: Optional[str] = Query(None, description="Filter by status"),
    provider: Optional[str] = Query(None, description="Filter by provider"),
):
    """List registered agents."""
    from ..services.agent_registry import get_registry
    from ..services.agent_registry import AgentState

    reg = get_registry()
    status_enum = None
    if status:
        try:
            status_enum = AgentState(status)
        except ValueError:
            raise HTTPException(400, detail=f"Invalid status: {status}")

    agents = reg.list_agents(status=status_enum, provider=provider)
    return AgentListResponse(
        agents=[AgentResponse(**a.to_dict()) for a in agents],
        total=len(agents),
    )


@router.get("/agents/overview", response_model=AgentsOverviewResponse)
async def agents_overview():
    """Aggregated dashboard-style summary for the Agents top-level surface."""
    from ..services.agent_registry import get_registry
    from .nexus_models import get_task_queue

    reg = get_registry()
    agents = reg.list_agents()
    costs_payload, cost_by_agent = _build_cost_summary_payload()
    agent_payload = []
    fallback_events: list[dict[str, Any]] = []
    for agent in agents:
        binding_payload = _get_agent_binding_payload(agent, cost_row=cost_by_agent.get(agent.id))
        activity_events = list(binding_payload.get("activity", {}).get("recent_events") or [])
        fallback_events.extend(activity_events)
        agent_payload.append(
            AgentInfo(
                id=agent.id,
                username=binding_payload["binding"].get("exec_user") or agent.name,
                agent_type=agent.provider,
                display_name=agent.name,
                available=agent.status.value != "offline",
                kind="agent",
                identity=binding_payload.get("identity") or {},
                runtime=binding_payload.get("runtime") or {},
                memory=binding_payload.get("memory") or {},
                capabilities=binding_payload.get("capabilities") or [],
                activity=binding_payload.get("activity") or {},
                cost=binding_payload.get("cost") or {},
            )
        )

    try:
        queue = get_task_queue(settings.exec_user or "ubuntu")
        tasks, total_tasks = queue.list_tasks(page=1, page_size=200)
    except Exception:
        tasks, total_tasks = [], 0

    active_tasks = 0
    failures = 0
    for task in tasks:
        status = str(getattr(task, "status", "") or "").strip().lower()
        if status in {"running", "in_review", "pending", "todo", "assigned", "awaiting_owner"}:
            active_tasks += 1
        if status == "failed":
            failures += 1

    # Agent-status tallies (consumed by the summary below).
    online = sum(1 for a in agents if a.status.value != "offline")
    running = sum(1 for a in agents if a.status.value == "running")
    offline = sum(1 for a in agents if a.status.value == "offline")
    idle = sum(1 for a in agents if a.status.value == "idle")
    error = sum(1 for a in agents if a.status.value == "error")

    teams: list = []
    active_teams = 0

    queue_depth = max(total_tasks - active_tasks, 0)
    summary = AgentOverviewSummary(
        total_agents=len(agents),
        online_agents=online,
        busy_agents=running,
        offline_agents=offline,
        teams_total=len(teams),
        active_tasks=active_tasks,
        queue_depth=queue_depth,
        recent_failures=failures,
        total_cost_usd=float(costs_payload.get("total_cost_usd", 0.0) or 0.0),
        idle_agents=idle,
        running_agents=running,
        error_agents=error,
        active_teams=active_teams,
        total_tokens=int(costs_payload.get("total_tokens", 0) or 0),
        recent_activity_count=0,
    )
    recent_activity = _summarize_recent_activity(limit=12, fallback_events=fallback_events)
    summary.recent_activity_count = len(recent_activity)
    return AgentsOverviewResponse(
        summary=summary,
        dashboard=AgentOverviewSummary(**summary.model_dump()),
        agents=agent_payload,
        teams=teams,
        recent_activity=recent_activity,
        recent_costs=list(costs_payload.get("by_agent") or [])[:5],
        costs=costs_payload,
    )


@router.get("/agents/stats", response_model=AgentStatsResponse)
async def agent_stats():
    """Get agent counts by status."""
    from ..services.agent_registry import get_registry

    reg = get_registry()
    counts = reg.count_by_status()
    return AgentStatsResponse(counts=counts, total=sum(counts.values()))


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str):
    """Get agent details by ID."""
    from ..services.agent_registry import get_registry

    reg = get_registry()
    info = reg.get(agent_id)
    if not info:
        raise HTTPException(404, detail=f"Agent not found: {agent_id}")
    return AgentResponse(**info.to_dict())


@router.get("/agents/{agent_id}/binding", response_model=AgentBindingItem)
async def get_agent_binding(agent_id: str):
    """Return agent-scoped runtime binding without mixing in global defaults."""
    from ..services.agent_registry import get_registry

    reg = get_registry()
    info = reg.get(agent_id)
    if not info:
        raise HTTPException(404, detail=f"Agent not found: {agent_id}")
    _, cost_by_agent = _build_cost_summary_payload()
    return AgentBindingItem(**_get_agent_binding_payload(info, cost_row=cost_by_agent.get(agent_id)))


@router.patch("/agents/{agent_id}/binding", response_model=AgentBindingItem)
async def update_agent_binding(agent_id: str, req: AgentBindingUpdateRequest):
    """Update agent-scoped runtime binding."""
    from ..services.agent_registry import get_registry

    reg = get_registry()
    info = reg.get(agent_id)
    if not info:
        raise HTTPException(404, detail=f"Agent not found: {agent_id}")

    updates = req.model_dump(exclude_none=True)
    if "capabilities" in updates and "tools" not in updates:
        updates["tools"] = list(updates.get("capabilities") or [])
    if "tools" in updates and "capabilities" not in updates:
        updates["capabilities"] = list(updates.get("tools") or [])
    if "memory_scope" in updates and "memory_policy" not in updates:
        updates["memory_policy"] = updates["memory_scope"]
    if "memory_policy" in updates and "memory_scope" not in updates:
        updates["memory_scope"] = updates["memory_policy"]

    persisted = dict(_AGENT_BINDINGS.get(agent_id, {}) or {})
    persisted.update(updates)
    persisted["updated_at"] = time.time()
    _AGENT_BINDINGS[agent_id] = persisted

    if "provider" in updates:
        info.provider = str(updates["provider"] or info.provider)
    if "alias" in updates:
        info.alias = str(updates["alias"] or info.alias)
    if "model" in updates:
        info.model = str(updates["model"] or info.model)
    if "workspace" in updates:
        info.workspace = str(updates["workspace"] or info.workspace)
    if "capabilities" in updates:
        info.capabilities = list(updates.get("capabilities") or [])
    metadata = dict(info.metadata or {})
    metadata.update(dict(updates.get("metadata") or {}))
    if "exec_user" in updates:
        metadata["exec_user"] = updates["exec_user"]
    if "runtime_profile" in updates:
        metadata["runtime_profile"] = updates["runtime_profile"]
    if "memory_scope" in updates:
        metadata["memory_scope"] = updates["memory_scope"]
        metadata["memory_policy"] = updates["memory_scope"]
    if "team_name" in updates:
        metadata["team_name"] = updates["team_name"]
    if "enabled" in updates:
        metadata["enabled"] = updates["enabled"]
    if "auto_start" in updates:
        metadata["auto_start"] = updates["auto_start"]
    if "notes" in updates:
        metadata["notes"] = updates["notes"]
    if "capabilities" in updates:
        metadata["capabilities"] = list(updates.get("capabilities") or [])
        metadata["tools"] = list(updates.get("capabilities") or [])
    if "skills" in updates:
        metadata["skills"] = list(updates.get("skills") or [])
    if "permissions" in updates:
        metadata["permissions"] = list(updates.get("permissions") or [])
    info.metadata = metadata

    _, cost_by_agent = _build_cost_summary_payload()
    return AgentBindingItem(**_get_agent_binding_payload(info, cost_row=cost_by_agent.get(agent_id)))


@router.patch("/agents/{agent_id}/status", response_model=AgentResponse)
async def update_agent_status(agent_id: str, req: AgentStatusUpdateRequest):
    """Update an agent's status."""
    from ..services.agent_registry import get_registry
    from ..services.agent_registry import AgentState

    reg = get_registry()
    try:
        new_status = AgentState(req.status)
    except ValueError:
        raise HTTPException(400, detail=f"Invalid status: {req.status}")

    info = reg.update_status(agent_id, new_status)
    if not info:
        raise HTTPException(
            400,
            detail=f"Agent not found or invalid transition: {agent_id} → {req.status}",
        )
    return AgentResponse(**info.to_dict())


@router.delete("/agents/{agent_id}")
async def deregister_agent(agent_id: str):
    """Deregister an agent."""
    from ..services.agent_registry import get_registry

    reg = get_registry()
    if not reg.deregister(agent_id):
        raise HTTPException(404, detail=f"Agent not found: {agent_id}")
    return {"success": True, "agent_id": agent_id}

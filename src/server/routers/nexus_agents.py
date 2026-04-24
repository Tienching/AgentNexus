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
  - POST /api/nexus/agents/teams        — Create a swarm team
  - GET  /api/nexus/agents/teams/{name} — Get team status
  - POST /api/nexus/agents/teams/{name}/shutdown — Shutdown a team
  - GET  /api/nexus/agents/teams/{name}/mailbox/{agent} — Get agent mailbox
  - POST /api/nexus/agents/teams/{name}/tasks/claim — Claim a task
"""

from __future__ import annotations

import time
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from ..services.observability import track_api_latency
from .nexus_auth import verify_nexus_auth
from .nexus_models import (
    AgentInfo,
    AgentBindingItem,
    AgentBindingUpdateRequest,
    AgentOverviewActivityItem,
    AgentOverviewSummary,
    AgentOverviewTeamItem,
    AgentsOverviewResponse,
    TeamConfigItem,
    TeamConfigUpdateRequest,
)

logger = get_logger(__name__)

_AGENT_BINDINGS: dict[str, dict] = {}
_TEAM_CONFIGS: dict[str, dict] = {}

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


# ---------------------------------------------------------------------------
# Swarm team request / response models
# ---------------------------------------------------------------------------

class TeamWorkerConfig(BaseModel):
    name: str = Field(..., description="Worker name")
    capabilities: List[str] = Field(default_factory=list, description="Worker capabilities")
    task: str = Field("", description="Initial task description for the worker")


class TeamLeadConfig(BaseModel):
    name: str = Field("lead", description="Lead agent name")
    capabilities: List[str] = Field(default_factory=list, description="Lead capabilities")
    task: str = Field("", description="Initial task description for the lead")


class TeamCreateRequest(BaseModel):
    name: str = Field(..., description="Team name", min_length=1, max_length=100)
    lead: TeamLeadConfig = Field(default_factory=TeamLeadConfig, description="Lead agent config")
    workers: List[TeamWorkerConfig] = Field(default_factory=list, description="Worker agent configs")


class TeamShutdownRequest(BaseModel):
    graceful: bool = Field(True, description="Graceful shutdown (negotiate) vs immediate cancel")


class TaskClaimRequest(BaseModel):
    agent_name: str = Field(..., description="Agent claiming the task")
    task_id: str = Field(..., description="Task ID to claim")


def _safe_subagent_manager():
    try:
        return _get_subagent_manager()
    except HTTPException:
        return None


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


def _build_team_members(status: Optional[dict]) -> list[dict[str, Any]]:
    members = list((status or {}).get("members") or [])
    normalized: list[dict[str, Any]] = []
    for member in members:
        item = dict(member or {})
        normalized.append(
            {
                "name": str(item.get("name") or ""),
                "agent_id": str(item.get("agent_id") or ""),
                "role": str(item.get("role") or "worker"),
                "status": str(item.get("status") or "idle"),
                "capabilities": list(item.get("capabilities") or []),
                "unread_mail": int(item.get("unread_mail", 0) or 0),
                "tasks": list(item.get("tasks") or []),
            }
        )
    return normalized


def _aggregate_team_usage(members: list[dict[str, Any]], cost_by_agent: dict[str, dict[str, Any]]) -> dict[str, Any]:
    total = {"total_cost_usd": 0.0, "total_tokens": 0, "request_count": 0}
    for member in members:
        usage = _usage_payload(cost_by_agent.get(member.get("agent_id") or ""))
        total["total_cost_usd"] += usage["total_cost_usd"]
        total["total_tokens"] += usage["total_tokens"]
        total["request_count"] += usage["request_count"]
    return total


def _team_runtime_status(status: Optional[dict], member_count: int) -> tuple[str, int, int]:
    data = dict(status or {})
    running_agents = len(data.get("running_agents") or [])
    available_tasks = len(data.get("available_tasks") or [])
    runtime_status = "running" if running_agents else ("idle" if member_count else "offline")
    return runtime_status, running_agents, available_tasks


def _get_team_config_payload(
    team_name: str,
    status: Optional[dict] = None,
    *,
    cost_by_agent: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    persisted = dict(_TEAM_CONFIGS.get(team_name, {}) or {})
    data = dict(status or {})
    detail = dict(data.get("detail", {}) or {})
    shared_state = dict(data.get("shared_state") or {})
    members = _build_team_members(data)
    member_ids = [member["agent_id"] for member in members if member.get("agent_id")]
    lead_agent_id = next((member["agent_id"] for member in members if member.get("role") == "lead" and member.get("agent_id")), "")
    runtime_status, running_agents, available_tasks = _team_runtime_status(data, len(members))

    config = {
        "display_name": persisted.get("display_name") or shared_state.get("display_name") or team_name,
        "mission": persisted.get("mission") or shared_state.get("mission") or "",
        "workspace": persisted.get("workspace") or shared_state.get("workspace") or "",
        "lead_agent_id": persisted.get("lead_agent_id") or lead_agent_id,
        "member_agent_ids": list(persisted.get("member_agent_ids") or member_ids),
        "shared_memory_policy": persisted.get("shared_memory_policy") or persisted.get("memory_policy") or shared_state.get("shared_memory_policy") or "team",
        "auto_balance": bool(persisted.get("auto_balance", shared_state.get("auto_balance", False))),
        "tags": list(persisted.get("tags") or shared_state.get("tags") or []),
        "notes": str(persisted.get("notes") or shared_state.get("notes") or ""),
    }
    provider = persisted.get("default_provider") or detail.get("provider") or "claude"
    alias = persisted.get("default_alias") or provider
    permissions = list(persisted.get("permissions") or detail.get("permissions") or [])
    capabilities = sorted({cap for member in members for cap in member.get("capabilities") or []})
    updated_at = persisted.get("updated_at") or time.time()
    activity_event = {
        "id": f"team:{team_name}",
        "title": config["display_name"] or team_name,
        "subtitle": f"{len(members)} members · {runtime_status}",
        "timestamp": updated_at,
        "level": "info",
        "entity_type": "team",
        "entity_id": team_name,
        "scope": "team",
        "scope_id": team_name,
        "detail": config["mission"] or "",
        "status": runtime_status,
    }
    usage = _aggregate_team_usage(members, cost_by_agent or {})
    identity = _identity_payload(
        title=config["display_name"] or team_name,
        subtitle=" · ".join([part for part in [f"{len(members)} members", runtime_status] if part]),
        provider=provider,
        alias=alias,
        owner=config["lead_agent_id"],
        role="team",
        external_id=team_name,
    )
    runtime = _runtime_payload(
        status=runtime_status,
        workspace=config["workspace"],
        model="",
        runtime_profile=persisted.get("runtime") or detail.get("runtime") or "swarm",
        team_name=team_name,
        enabled=True,
        running_agents=running_agents,
        available_tasks=available_tasks,
    )
    memory = _memory_payload(
        scope=config["shared_memory_policy"],
        summary=f"{len(shared_state)} shared state entries" if shared_state else "No shared state",
        entry_count=len(shared_state),
        last_updated_at=updated_at,
    )
    activity = _activity_payload(
        last_seen_at=updated_at,
        headline=f"{config['display_name'] or team_name} has {running_agents} running agents",
        status=runtime_status,
        recent_events=[activity_event],
    )
    return {
        "team_name": team_name,
        "runtime": runtime["runtime_profile"],
        "default_provider": provider,
        "default_alias": alias,
        "memory_policy": config["shared_memory_policy"],
        "coordination_mode": persisted.get("coordination_mode") or detail.get("coordination_mode") or "mailbox",
        "permissions": permissions,
        "metadata": {
            **dict(detail.get("metadata") or {}),
            **dict(shared_state or {}),
            **dict(persisted.get("metadata") or {}),
            "member_count": len(members),
        },
        "updated_at": updated_at,
        "config": config,
        "identity": identity,
        "runtime_detail": runtime,
        "memory": memory,
        "capabilities": capabilities,
        "activity": activity,
        "cost": usage,
        "members": members,
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
    from src.nanobot.agent.lifecycle import AgentState

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
    from src.nanobot.agent.lifecycle import AgentState

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

    teams: list[AgentOverviewTeamItem] = []
    mgr = _safe_subagent_manager()
    if mgr is not None:
        for name in list(getattr(mgr, "_teams", {}).keys()):
            status = mgr.get_team_status(name)
            if "error" in status:
                continue
            team_payload = _get_team_config_payload(name, status, cost_by_agent=cost_by_agent)
            team_members = list(team_payload.get("members") or [])
            claimed_tasks = sum(len(member.get("tasks") or []) for member in team_members)
            pending_messages = sum(int(member.get("unread_mail", 0) or 0) for member in team_members)
            fallback_events.extend(team_payload.get("activity", {}).get("recent_events") or [])
            teams.append(
                AgentOverviewTeamItem(
                    team_name=name,
                    member_count=len(team_members),
                    claimed_tasks=claimed_tasks,
                    pending_messages=pending_messages,
                    status=team_payload.get("runtime_detail", {}).get("status") or "idle",
                    kind="team",
                    identity=team_payload.get("identity") or {},
                    runtime=team_payload.get("runtime_detail") or {},
                    memory=team_payload.get("memory") or {},
                    capabilities=team_payload.get("capabilities") or [],
                    activity=team_payload.get("activity") or {},
                    cost=team_payload.get("cost") or {},
                    members=team_members,
                )
            )

    online = sum(1 for a in agents if a.status.value != "offline")
    idle = sum(1 for a in agents if a.status.value == "idle")
    running = sum(1 for a in agents if a.status.value == "running")
    error = sum(1 for a in agents if a.status.value == "error")
    offline = sum(1 for a in agents if a.status.value == "offline")
    active_teams = sum(1 for team in teams if (team.runtime or {}).get("running_agents") or (team.runtime or {}).get("available_tasks"))

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
    from src.nanobot.agent.lifecycle import AgentState

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


# ---------------------------------------------------------------------------
# Swarm team endpoints
# ---------------------------------------------------------------------------

def _get_subagent_manager():
    """Resolve the global SubagentManager instance."""
    from src.nanobot.agent.subagent import get_subagent_manager
    mgr = get_subagent_manager()
    if mgr is None:
        raise HTTPException(503, detail="SubagentManager not available")
    return mgr


@router.post("/agents/teams", status_code=201)
async def create_team(req: TeamCreateRequest):
    """Create a swarm team with a lead and workers."""
    mgr = _get_subagent_manager()

    team_config = {
        "name": req.name,
        "lead": {
            "name": req.lead.name,
            "capabilities": req.lead.capabilities,
            "task": req.lead.task,
        },
        "workers": [
            {
                "name": w.name,
                "capabilities": w.capabilities,
                "task": w.task,
            }
            for w in req.workers
        ],
    }

    result = await mgr.spawn_team(team_config)
    return {"success": True, "team_name": req.name, "detail": result}


@router.get("/agents/teams/{team_name}/config", response_model=TeamConfigItem)
async def get_team_config(team_name: str):
    """Return team-scoped coordination config."""
    mgr = _get_subagent_manager()
    status = mgr.get_team_status(team_name)
    if "error" in status:
        raise HTTPException(404, detail=status["error"])
    _, cost_by_agent = _build_cost_summary_payload()
    return TeamConfigItem(**_get_team_config_payload(team_name, status, cost_by_agent=cost_by_agent))


@router.patch("/agents/teams/{team_name}/config", response_model=TeamConfigItem)
async def update_team_config(team_name: str, req: TeamConfigUpdateRequest):
    """Update team-scoped coordination config."""
    mgr = _get_subagent_manager()
    status = mgr.get_team_status(team_name)
    if "error" in status:
        raise HTTPException(404, detail=status["error"])
    updates = req.model_dump(exclude_none=True)
    if "shared_memory_policy" in updates and "memory_policy" not in updates:
        updates["memory_policy"] = updates["shared_memory_policy"]
    if "memory_policy" in updates and "shared_memory_policy" not in updates:
        updates["shared_memory_policy"] = updates["memory_policy"]

    persisted = dict(_TEAM_CONFIGS.get(team_name, {}) or {})
    persisted.update(updates)
    persisted["updated_at"] = time.time()
    _TEAM_CONFIGS[team_name] = persisted

    _, cost_by_agent = _build_cost_summary_payload()
    return TeamConfigItem(**_get_team_config_payload(team_name, status, cost_by_agent=cost_by_agent))


@router.get("/agents/teams/{team_name}")
async def get_team_status(team_name: str):
    """Get the current status of a swarm team."""
    mgr = _get_subagent_manager()
    status = mgr.get_team_status(team_name)
    if "error" in status:
        raise HTTPException(404, detail=status["error"])
    return status


@router.post("/agents/teams/{team_name}/shutdown")
async def shutdown_team(team_name: str, req: TeamShutdownRequest | None = None):
    """Shutdown a swarm team."""
    mgr = _get_subagent_manager()
    result = await mgr.shutdown_team(team_name, graceful=True if req is None else req.graceful)
    return {"success": True, "detail": result}


@router.get("/agents/teams/{team_name}/mailbox/{agent_name}")
async def get_agent_mailbox(team_name: str, agent_name: str):
    """Get mailbox messages for a specific agent in a team."""
    mgr = _get_subagent_manager()
    handle = mgr._teams.get(team_name)
    if not handle:
        raise HTTPException(404, detail=f"Team not found: {team_name}")

    mailbox = handle["mailbox"]
    messages = mailbox.receive(agent_name)
    return {
        "team_name": team_name,
        "agent_name": agent_name,
        "messages": [m.to_dict() for m in messages],
        "unread_count": mailbox.get_unread_count(agent_name),
    }


@router.post("/agents/teams/{team_name}/tasks/claim")
async def claim_team_task(team_name: str, req: TaskClaimRequest):
    """Claim a task from the team task board."""
    mgr = _get_subagent_manager()
    handle = mgr._teams.get(team_name)
    if not handle:
        raise HTTPException(404, detail=f"Team not found: {team_name}")

    coordinator = handle["coordinator"]
    success = coordinator.claim_task(req.agent_name, req.task_id)
    if not success:
        raise HTTPException(409, detail=f"Task {req.task_id} not available for claiming")
    return {"success": True, "task_id": req.task_id, "claimed_by": req.agent_name}

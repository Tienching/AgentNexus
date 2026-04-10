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

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..logger import get_logger
from ..services.observability import track_api_latency
from .nexus_auth import verify_nexus_auth

logger = get_logger(__name__)

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


@router.get("/agents/teams/{team_name}")
async def get_team_status(team_name: str):
    """Get the current status of a swarm team."""
    mgr = _get_subagent_manager()
    status = mgr.get_team_status(team_name)
    if "error" in status:
        raise HTTPException(404, detail=status["error"])
    return status


@router.post("/agents/teams/{team_name}/shutdown")
async def shutdown_team(team_name: str, req: TeamShutdownRequest):
    """Shutdown a swarm team."""
    mgr = _get_subagent_manager()
    result = await mgr.shutdown_team(team_name, graceful=req.graceful)
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

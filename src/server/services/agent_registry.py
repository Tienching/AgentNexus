# -*- coding: utf-8 -*-
"""Agent lifecycle registry — the canonical home for agent identity on the board.

Tracks all registered agents, their health (via heartbeat), and capabilities.
This module is intentionally standalone (no engine, no DB) so it can be imported
by routers and services without circular dependencies. It was rehomed here from
the retired nanobot engine during the daemon-platform refactor.

Usage:
    from src.server.services.agent_registry import get_registry, AgentState

    reg = get_registry()
    info = reg.register(name="claude-1", provider="claude", workspace="/tmp/w")
    reg.heartbeat(info.id)
    agents = reg.list_agents(status=AgentState.IDLE)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any, Dict, List, Optional

from loguru import logger


class AgentState(str, Enum):
    """Agent lifecycle states."""
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    OFFLINE = "offline"


@dataclass
class AgentInfo:
    """Information about a registered agent."""
    id: str
    name: str
    provider: str
    status: AgentState = AgentState.IDLE
    last_heartbeat: float = field(default_factory=time.time)
    workspace: str = ""
    capabilities: List[str] = field(default_factory=list)
    model: str = ""
    alias: str = ""
    registered_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "status": self.status.value,
            "last_heartbeat": self.last_heartbeat,
            "workspace": self.workspace,
            "capabilities": self.capabilities,
            "model": self.model,
            "alias": self.alias,
            "registered_at": self.registered_at,
            "metadata": self.metadata,
        }


# Valid state transitions
_TRANSITIONS: Dict[AgentState, set] = {
    AgentState.IDLE: {AgentState.RUNNING, AgentState.OFFLINE, AgentState.ERROR},
    AgentState.RUNNING: {AgentState.IDLE, AgentState.ERROR, AgentState.OFFLINE},
    AgentState.ERROR: {AgentState.IDLE, AgentState.OFFLINE},
    AgentState.OFFLINE: {AgentState.IDLE},  # Can come back online
}


class AgentRegistry:
    """Thread-safe registry for tracking agent lifecycle.

    Features:
      - Register/deregister agents
      - Heartbeat tracking with configurable timeout
      - Status transitions with validation
      - Query by status, provider, or ID
      - Automatic offline detection via check_timeouts()
    """

    DEFAULT_HEARTBEAT_TIMEOUT = 60.0  # seconds

    def __init__(self, heartbeat_timeout: float = DEFAULT_HEARTBEAT_TIMEOUT):
        self._agents: Dict[str, AgentInfo] = {}
        self._lock = Lock()
        self._heartbeat_timeout = heartbeat_timeout

    def register(
        self,
        name: str,
        provider: str,
        workspace: str = "",
        capabilities: Optional[List[str]] = None,
        model: str = "",
        alias: str = "",
        agent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentInfo:
        """Register a new agent."""
        agent_id = agent_id or f"agent-{uuid.uuid4().hex[:12]}"
        info = AgentInfo(
            id=agent_id,
            name=name,
            provider=provider,
            workspace=workspace,
            capabilities=capabilities or [],
            model=model,
            alias=alias or provider,
            metadata=metadata or {},
        )
        with self._lock:
            self._agents[agent_id] = info
        logger.info("Agent registered: {} ({}/{})", agent_id, name, provider)
        return info

    def deregister(self, agent_id: str) -> bool:
        """Remove an agent from the registry. Returns True if found and removed."""
        with self._lock:
            removed = self._agents.pop(agent_id, None)
        if removed:
            logger.info("Agent deregistered: {} ({})", agent_id, removed.name)
            return True
        return False

    def heartbeat(self, agent_id: str, status: Optional[AgentState] = None) -> Optional[AgentInfo]:
        """Record a heartbeat for an agent."""
        with self._lock:
            info = self._agents.get(agent_id)
            if not info:
                return None
            info.last_heartbeat = time.time()
            if status and status != info.status:
                self._transition(info, status)
        return info

    def get(self, agent_id: str) -> Optional[AgentInfo]:
        """Get agent info by ID."""
        with self._lock:
            return self._agents.get(agent_id)

    def list_agents(
        self,
        status: Optional[AgentState] = None,
        provider: Optional[str] = None,
    ) -> List[AgentInfo]:
        """List registered agents, optionally filtered by status/provider."""
        with self._lock:
            agents = list(self._agents.values())
        if status:
            agents = [a for a in agents if a.status == status]
        if provider:
            agents = [a for a in agents if a.provider == provider]
        return agents

    def update_status(self, agent_id: str, new_status: AgentState) -> Optional[AgentInfo]:
        """Update an agent's status with transition validation."""
        with self._lock:
            info = self._agents.get(agent_id)
            if not info:
                return None
            if new_status not in _TRANSITIONS.get(info.status, set()):
                logger.warning(
                    "Invalid status transition for {}: {} -> {}",
                    agent_id, info.status.value, new_status.value,
                )
                return None
            self._transition(info, new_status)
        return info

    def check_timeouts(self) -> List[str]:
        """Check all agents for heartbeat timeout and mark them offline."""
        now = time.time()
        newly_offline: List[str] = []
        with self._lock:
            for agent_id, info in self._agents.items():
                if info.status == AgentState.OFFLINE:
                    continue
                elapsed = now - info.last_heartbeat
                if elapsed > self._heartbeat_timeout:
                    logger.warning(
                        "Agent {} heartbeat timeout ({:.0f}s), marking offline",
                        agent_id, elapsed,
                    )
                    self._transition(info, AgentState.OFFLINE)
                    newly_offline.append(agent_id)
        return newly_offline

    def _transition(self, info: AgentInfo, new_status: AgentState) -> None:
        """Apply a state transition (caller must hold lock)."""
        old = info.status
        info.status = new_status
        logger.info("Agent {} status: {} -> {}", info.id, old.value, new_status.value)

    def count_by_status(self) -> Dict[str, int]:
        """Get agent counts grouped by status."""
        counts: Dict[str, int] = {}
        with self._lock:
            for info in self._agents.values():
                key = info.status.value
                counts[key] = counts.get(key, 0) + 1
        return counts


# Module-level singleton accessor
_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    """Get the global AgentRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry

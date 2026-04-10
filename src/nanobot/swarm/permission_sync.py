# -*- coding: utf-8 -*-
"""PermissionSyncService — cross-agent permission synchronization.

Enables worker agents to request tool-call permissions from the team lead
via dual-path delivery (mailbox + file-lock), with approval caching and
background agent permission back-propagation.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .mailbox import SwarmMailbox, MailMessage
from .team_file import TeamFile

from src.nanobot.agent.permissions import ToolRisk, classify_tool


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PermissionRequest:
    """A pending permission request from a worker agent."""

    id: str
    agent_name: str
    tool_name: str
    tool_args: dict
    risk_level: str  # ToolRisk value
    status: str  # "pending" | "approved" | "rejected" | "expired"
    created_at: float = field(default_factory=time.time)
    approver: Optional[str] = None
    scope: str = "once"  # "once" | "session" | "permanent"
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PermissionRequest:
        return cls(**data)


@dataclass
class PermissionResponse:
    """Response to a permission request (approval or rejection)."""

    request_id: str
    approved: bool
    approver: str
    scope: str  # "once" | "session" | "permanent"
    reason: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PermissionResponse:
        return cls(**data)


# ---------------------------------------------------------------------------
# PermissionSyncService
# ---------------------------------------------------------------------------

class PermissionSyncService:
    """Cross-agent permission synchronization service.

    Worker agents submit permission requests that are routed to the team lead
    for approval via dual-path delivery (mailbox + shared file lock).  The lead
    can approve or reject with a scope (once / session / permanent).  Approved
    scopes are cached to avoid re-prompting for identical operations.

    Background agents can also sync their current permission state back to the
    lead and receive updates.
    """

    REQUEST_TIMEOUT = 120.0  # seconds before a pending request expires
    CLEANUP_INTERVAL = 60.0  # seconds between expired-request sweeps

    def __init__(self, team_file: TeamFile, mailbox: SwarmMailbox):
        self.team_file = team_file
        self.mailbox = mailbox

        # In-memory tracking of pending requests (on the service owner side)
        self._pending_requests: Dict[str, PermissionRequest] = {}

        # Approval cache: agent_name -> {tool_hash: approved}
        # "session" scope entries persist until the service is torn down.
        # "permanent" scope entries also go here (they survive re-inits via file).
        self._approval_cache: Dict[str, Dict[str, bool]] = {}

        # Event futures for awaiting responses (request_id -> asyncio.Future)
        self._waiters: Dict[str, asyncio.Future] = {}

        # Shared permission file path for the file-lock path
        self._perm_dir: Path = (
            team_file.base_dir
            / ".codebuddy"
            / "teams"
            / team_file.team_name
            / "permissions"
        )
        self._pending_dir: Path = self._perm_dir / "pending"
        self._approved_dir: Path = self._perm_dir / "approved"

        # Background cleanup task handle
        self._cleanup_task: Optional[asyncio.Task] = None

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Start the background cleanup task and load persisted approvals."""
        self._load_approval_cache()
        self._pending_dir.mkdir(parents=True, exist_ok=True)
        self._approved_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("PermissionSyncService started for team {}", self.team_file.team_name)

    async def stop(self) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("PermissionSyncService stopped for team {}", self.team_file.team_name)

    # -- permission request (worker -> lead) ---------------------------------

    async def request_permission(
        self,
        agent_name: str,
        tool_name: str,
        tool_args: dict,
        risk_level: ToolRisk | None = None,
    ) -> PermissionRequest:
        """Create a permission request and send it to the lead via dual paths.

        Returns the PermissionRequest (still in "pending" status).  Callers
        should use ``wait_for_response`` to block until the lead decides.
        """
        if risk_level is None:
            risk_level = classify_tool(tool_name)

        # Check approval cache first — if previously approved with session/permanent
        # scope, skip the request entirely.
        cached = await self.check_approval_cache(agent_name, tool_name, tool_args)
        if cached is True:
            req = PermissionRequest(
                id=f"perm-{uuid.uuid4().hex[:12]}",
                agent_name=agent_name,
                tool_name=tool_name,
                tool_args=tool_args,
                risk_level=risk_level.value if isinstance(risk_level, ToolRisk) else risk_level,
                status="approved",
                scope="session",
                reason="cached_approval",
            )
            return req

        req = PermissionRequest(
            id=f"perm-{uuid.uuid4().hex[:12]}",
            agent_name=agent_name,
            tool_name=tool_name,
            tool_args=tool_args,
            risk_level=risk_level.value if isinstance(risk_level, ToolRisk) else risk_level,
            status="pending",
        )

        self._pending_requests[req.id] = req

        # Send via both paths for reliability
        await self._send_via_mailbox(req)
        await self._send_via_file_lock(req)

        logger.info(
            "Permission request {} from {}: {} (risk={})",
            req.id, agent_name, tool_name, req.risk_level,
        )
        return req

    async def check_approval_cache(
        self,
        agent_name: str,
        tool_name: str,
        tool_args: dict,
    ) -> Optional[bool]:
        """Check the approval cache for a previous approval.

        Returns True if approved, False if previously denied, None if not cached.
        """
        tool_hash = self._hash_tool_call(tool_name, tool_args)
        agent_cache = self._approval_cache.get(agent_name, {})
        return agent_cache.get(tool_hash)

    # -- permission approval (lead actions) ----------------------------------

    async def approve_request(
        self,
        request_id: str,
        approver: str,
        scope: str = "once",
    ) -> None:
        """Approve a pending permission request."""
        req = self._pending_requests.get(request_id)
        if req is None:
            # Try loading from file-lock path
            req = self._load_request_from_file(request_id)
            if req is None:
                logger.warning("Cannot approve unknown request {}", request_id)
                return

        req.status = "approved"
        req.approver = approver
        req.scope = scope

        # Update approval cache for session/permanent scopes
        if scope in ("session", "permanent"):
            tool_hash = self._hash_tool_call(req.tool_name, req.tool_args)
            self._approval_cache.setdefault(req.agent_name, {})[tool_hash] = True
            if scope == "permanent":
                self._persist_approval(req.agent_name, tool_hash, True)

        # Write response to file
        resp = PermissionResponse(
            request_id=request_id,
            approved=True,
            approver=approver,
            scope=scope,
        )
        self._write_response_file(resp)

        # Send response via mailbox
        self._send_response_via_mailbox(req.agent_name, resp)

        # Remove from pending
        self._pending_requests.pop(request_id, None)
        self._remove_pending_file(request_id)

        # Resolve any waiter
        self._resolve_waiter(request_id, resp)

        logger.info("Permission {} approved by {} (scope={})", request_id, approver, scope)

    async def reject_request(
        self,
        request_id: str,
        approver: str,
        reason: str = "",
    ) -> None:
        """Reject a pending permission request."""
        req = self._pending_requests.get(request_id)
        if req is None:
            req = self._load_request_from_file(request_id)
            if req is None:
                logger.warning("Cannot reject unknown request {}", request_id)
                return

        req.status = "rejected"
        req.approver = approver
        req.reason = reason

        resp = PermissionResponse(
            request_id=request_id,
            approved=False,
            approver=approver,
            scope="once",
            reason=reason,
        )
        self._write_response_file(resp)
        self._send_response_via_mailbox(req.agent_name, resp)

        self._pending_requests.pop(request_id, None)
        self._remove_pending_file(request_id)

        self._resolve_waiter(request_id, resp)

        logger.info("Permission {} rejected by {}: {}", request_id, approver, reason)

    async def get_pending_requests(self) -> List[PermissionRequest]:
        """Return all pending (unresolved) permission requests."""
        # Merge in-memory and file-based pending requests
        file_requests = self._load_all_pending_from_files()
        seen_ids = set(self._pending_requests.keys())
        for req in file_requests:
            if req.id not in seen_ids:
                self._pending_requests[req.id] = req
        return [r for r in self._pending_requests.values() if r.status == "pending"]

    # -- dual-path delivery ---------------------------------------------------

    async def _send_via_mailbox(self, request: PermissionRequest) -> None:
        """Send permission request to the lead via the mailbox system."""
        lead = self._get_lead()
        if lead is None:
            logger.warning("No team lead found; mailbox delivery skipped for {}", request.id)
            return

        msg = MailMessage(
            id=f"perm-mail-{request.id}",
            from_agent=request.agent_name,
            to_agent=lead.name,
            type="permission_request",
            content=json.dumps(request.to_dict(), ensure_ascii=False),
        )
        self.mailbox.send(request.agent_name, lead.name, msg)
        logger.debug("Permission request {} sent via mailbox to {}", request.id, lead.name)

    async def _send_via_file_lock(self, request: PermissionRequest) -> None:
        """Write permission request to the shared pending directory."""
        self._pending_dir.mkdir(parents=True, exist_ok=True)
        path = self._pending_dir / f"{request.id}.json"
        path.write_text(
            json.dumps(request.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug("Permission request {} written to file-lock path", request.id)

    # -- wait for response ---------------------------------------------------

    async def _wait_for_response(
        self,
        request_id: str,
        timeout: float = 120.0,
    ) -> PermissionResponse:
        """Block until a response arrives for the given request, or timeout.

        The caller (worker agent loop) should use this to synchronously await
        the lead's decision.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._waiters[request_id] = future

        # Also poll the response file as a fallback
        try:
            resp = await asyncio.wait_for(future, timeout=timeout)
            return resp
        except asyncio.TimeoutError:
            self._waiters.pop(request_id, None)
            # Check if a response file appeared
            req = self._pending_requests.get(request_id)
            if req:
                resp = self._check_response_file(request_id)
                if resp:
                    return resp
            # Mark as expired
            if request_id in self._pending_requests:
                self._pending_requests[request_id].status = "expired"
            raise TimeoutError(
                f"Permission request {request_id} timed out after {timeout}s"
            )

    async def wait_for_approval(
        self,
        request: PermissionRequest,
        timeout: float = 120.0,
    ) -> bool:
        """Convenience: wait for a response and return True if approved."""
        if request.status == "approved":
            return True
        try:
            resp = await self._wait_for_response(request.id, timeout=timeout)
            return resp.approved
        except TimeoutError:
            return False

    # -- background agent permission back-propagation ------------------------

    async def sync_permissions_to_lead(self, agent_name: str) -> None:
        """Back-propagate an agent's current permission state to the lead.

        Collects the approval cache for the agent and sends it as a
        permission_sync message to the lead.
        """
        lead = self._get_lead()
        if lead is None:
            logger.warning("No team lead found; sync skipped for {}", agent_name)
            return

        agent_cache = self._approval_cache.get(agent_name, {})
        sync_data = {
            "agent_name": agent_name,
            "approved_tools": list(agent_cache.keys()),
            "timestamp": time.time(),
        }

        msg = MailMessage(
            id=f"perm-sync-{uuid.uuid4().hex[:12]}",
            from_agent=agent_name,
            to_agent=lead.name,
            type="permission_sync",
            content=json.dumps(sync_data, ensure_ascii=False),
        )
        self.mailbox.send(agent_name, lead.name, msg)
        logger.debug("Permission sync sent from {} to lead", agent_name)

    async def receive_permission_updates(self, agent_name: str) -> List[Dict[str, Any]]:
        """Check mailbox for permission updates addressed to this agent.

        Returns a list of update dicts (approved/denied decisions).
        """
        messages = self.mailbox.receive(agent_name)
        updates: List[Dict[str, Any]] = []
        for msg in messages:
            if msg.type == "permission_response" and not msg.read:
                try:
                    resp_data = json.loads(msg.content)
                    resp = PermissionResponse.from_dict(resp_data)
                    updates.append(resp.to_dict())

                    # Update local cache
                    self._apply_response(resp)

                    # Resolve any waiter
                    self._resolve_waiter(resp.request_id, resp)

                    self.mailbox.mark_read(agent_name, msg.id)
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning("Malformed permission response for {}: {}", agent_name, exc)
        return updates

    # -- internal helpers ----------------------------------------------------

    def _apply_response(self, resp: PermissionResponse) -> None:
        """Apply a PermissionResponse to the local state."""
        req = self._pending_requests.get(resp.request_id)
        if req is None:
            return

        req.status = "approved" if resp.approved else "rejected"
        req.approver = resp.approver
        req.scope = resp.scope
        req.reason = resp.reason

        if resp.approved and resp.scope in ("session", "permanent"):
            tool_hash = self._hash_tool_call(req.tool_name, req.tool_args)
            self._approval_cache.setdefault(req.agent_name, {})[tool_hash] = True
            if resp.scope == "permanent":
                self._persist_approval(req.agent_name, tool_hash, True)

        self._pending_requests.pop(resp.request_id, None)

    def _resolve_waiter(self, request_id: str, resp: PermissionResponse) -> None:
        """Resolve a waiting future with the given response."""
        future = self._waiters.pop(request_id, None)
        if future and not future.done():
            future.set_result(resp)

    def _send_response_via_mailbox(
        self, agent_name: str, resp: PermissionResponse
    ) -> None:
        """Send a permission response to the requesting agent via mailbox."""
        msg = MailMessage(
            id=f"perm-resp-{resp.request_id}",
            from_agent=resp.approver,
            to_agent=agent_name,
            type="permission_response",
            content=json.dumps(resp.to_dict(), ensure_ascii=False),
        )
        self.mailbox.send(resp.approver, agent_name, msg)

    def _write_response_file(self, resp: PermissionResponse) -> None:
        """Write a response to the approved/rejected directory."""
        self._approved_dir.mkdir(parents=True, exist_ok=True)
        status_dir = self._approved_dir / ("approved" if resp.approved else "rejected")
        status_dir.mkdir(parents=True, exist_ok=True)
        path = status_dir / f"{resp.request_id}.json"
        path.write_text(
            json.dumps(resp.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _check_response_file(self, request_id: str) -> Optional[PermissionResponse]:
        """Check if a response file exists for the given request."""
        for status in ("approved", "rejected"):
            path = self._approved_dir / status / f"{request_id}.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return PermissionResponse.from_dict(data)
                except (json.JSONDecodeError, TypeError):
                    return None
        return None

    def _load_request_from_file(self, request_id: str) -> Optional[PermissionRequest]:
        """Load a pending request from the file-lock path."""
        path = self._pending_dir / f"{request_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return PermissionRequest.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            return None

    def _load_all_pending_from_files(self) -> List[PermissionRequest]:
        """Load all pending requests from the file-lock path."""
        if not self._pending_dir.exists():
            return []
        requests: List[PermissionRequest] = []
        for f in self._pending_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                req = PermissionRequest.from_dict(data)
                if req.status == "pending":
                    requests.append(req)
            except (json.JSONDecodeError, TypeError):
                pass
        return requests

    def _remove_pending_file(self, request_id: str) -> None:
        """Remove a pending request file."""
        path = self._pending_dir / f"{request_id}.json"
        if path.exists():
            path.unlink()

    def _get_lead(self):
        """Return the team lead member, if any."""
        for m in self.team_file.members:
            if m.role == "lead":
                return m
        return None

    @staticmethod
    def _hash_tool_call(tool_name: str, tool_args: dict) -> str:
        """Create a deterministic hash for a tool call for cache lookup."""
        payload = json.dumps(
            {"tool": tool_name, "args": tool_args},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        import hashlib
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    # -- persistence for "permanent" scope approvals -------------------------

    def _persist_approval(self, agent_name: str, tool_hash: str, approved: bool) -> None:
        """Append a permanent-scope approval to the persistent cache file."""
        cache_path = self._perm_dir / "approval_cache.json"
        data: Dict[str, Any] = {}
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
        data.setdefault(agent_name, {})[tool_hash] = approved
        cache_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_approval_cache(self) -> None:
        """Load the persistent approval cache from disk."""
        cache_path = self._perm_dir / "approval_cache.json"
        if not cache_path.exists():
            return
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            for agent_name, hashes in data.items():
                self._approval_cache.setdefault(agent_name, {}).update(hashes)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load approval cache: {}", exc)

    # -- background cleanup --------------------------------------------------

    async def _cleanup_loop(self) -> None:
        """Periodically expire old pending requests."""
        while True:
            await asyncio.sleep(self.CLEANUP_INTERVAL)
            self._expire_old_requests()

    def _expire_old_requests(self) -> None:
        """Mark requests older than REQUEST_TIMEOUT as expired."""
        now = time.time()
        expired_ids: List[str] = []
        for rid, req in list(self._pending_requests.items()):
            if req.status == "pending" and (now - req.created_at) > self.REQUEST_TIMEOUT:
                req.status = "expired"
                expired_ids.append(rid)
                self._remove_pending_file(rid)
        if expired_ids:
            logger.info("Expired {} old permission requests", len(expired_ids))

    # -- stats / inspection --------------------------------------------------

    def get_approval_cache_snapshot(self) -> Dict[str, Dict[str, bool]]:
        """Return a snapshot of the approval cache (agent -> {hash: approved})."""
        return {k: dict(v) for k, v in self._approval_cache.items()}

    def get_stats(self) -> Dict[str, Any]:
        """Return service statistics."""
        pending = [r for r in self._pending_requests.values() if r.status == "pending"]
        return {
            "pending_count": len(pending),
            "cached_agents": len(self._approval_cache),
            "total_cached_entries": sum(len(v) for v in self._approval_cache.values()),
            "waiters": len(self._waiters),
        }

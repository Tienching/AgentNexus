# -*- coding: utf-8 -*-
"""Daemon client — registers discovered providers with a server and heartbeats.

This is the host-side counterpart to the server daemon registry
(``src/server/routers/nexus_runtimes.py``: register/heartbeat/health). It runs
on each machine, discovers local CLI providers, and keeps their runtime rows
fresh on the server so the board reflects a live multi-machine fleet.

Usage:
    cfg = DaemonConfig(server_url="http://server:8080")
    client = DaemonClient(cfg)
    await client.start()          # register + begin heartbeat loop
    ...
    await client.stop()           # deregister + cancel loop
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from .discovery import DiscoveredProvider, discover_providers
from .identity import DaemonIdentity, get_or_create_identity

logger = logging.getLogger(__name__)

DEFAULT_HEARTBEAT_INTERVAL = 15.0  # seconds (server freshness window = 2x this)
DEFAULT_REGISTER_TIMEOUT = 10.0
DEFAULT_HTTP_TIMEOUT = 8.0


@dataclass
class DaemonConfig:
    """Daemon runtime configuration."""

    server_url: str = ""  # e.g. "http://10.0.0.1:8080"; empty => disabled
    workspace: str = "default"
    heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL
    register_timeout: float = DEFAULT_REGISTER_TIMEOUT
    http_timeout: float = DEFAULT_HTTP_TIMEOUT
    auth_token: str = ""  # NEXUS_AUTH_TOKEN if the server requires it
    daemon_id_override: str = ""  # force a specific id (testing)
    identity_path: Optional[str] = None  # override ~/.agent-nexus/daemon.id

    @classmethod
    def from_env(cls) -> "DaemonConfig":
        return cls(
            server_url=os.environ.get("AGENT_NEXUS_SERVER_URL", "").strip(),
            workspace=os.environ.get("AGENT_NEXUS_WORKSPACE", "default").strip() or "default",
            heartbeat_interval=float(os.environ.get("AGENT_NEXUS_HEARTBEAT_INTERVAL", "0") or 0)
            or DEFAULT_HEARTBEAT_INTERVAL,
            auth_token=os.environ.get("AGENT_NEXUS_DAEMON_TOKEN", "")
            or os.environ.get("NEXUS_AUTH_TOKEN", ""),
            daemon_id_override=os.environ.get("AGENT_NEXUS_DAEMON_ID", "").strip(),
            identity_path=os.environ.get("AGENT_NEXUS_IDENTITY_PATH", "").strip() or None,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.server_url)


class DaemonClient:
    """Registers a host's providers with a server and maintains liveness.

    One instance per host. Discovers providers once at start; re-registers if
    the server reports the daemon as unknown (404 on heartbeat, e.g. after a
    server data wipe).
    """

    def __init__(self, config: Optional[DaemonConfig] = None):
        self.config = config or DaemonConfig.from_env()
        self._identity: Optional[DaemonIdentity] = None
        self._discovered: List[DiscoveredProvider] = []
        self._loop_task: Optional[asyncio.Task] = None
        self._registered = False
        self._stopping = False

    # ------------------------------------------------------------------ identity

    @property
    def identity(self) -> DaemonIdentity:
        if self._identity is None:
            self._identity = get_or_create_identity()
        return self._identity

    # ------------------------------------------------------------------ discovery

    def discover(self) -> List[DiscoveredProvider]:
        """Probe the host for installed CLI providers (cached after first call)."""
        if not self._discovered:
            self._discovered = discover_providers()
        return self._discovered

    # ------------------------------------------------------------------ http

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.config.auth_token:
            h["Authorization"] = f"Bearer {self.config.auth_token}"
        return h

    def _url(self, path: str) -> str:
        base = self.config.server_url.rstrip("/")
        return f"{base}{path}"

    # ------------------------------------------------------------------ registration

    async def register(self) -> bool:
        """Register each discovered provider as a runtime row on the server.

        The server upserts on ``(workspace, daemon_id, provider)``, so a host
        with claude + hermes produces two rows under the same daemon_id.
        """
        if not self.config.enabled:
            return False
        providers = self.discover()
        if not providers:
            logger.warning("Daemon %s has no installed CLI providers; skipping register", self.identity.daemon_id)
            return False

        async with httpx.AsyncClient(timeout=self.config.register_timeout) as client:
            for dp in providers:
                runtime_id = f"{self.identity.daemon_id}/{dp.provider}"
                payload: Dict[str, Any] = {
                    "daemon_id": self.identity.daemon_id,
                    "runtime_id": runtime_id,
                    "device_name": self.identity.device_name,
                    "status": "idle",
                    "health_endpoint": None,
                    "metadata": {
                        "workspace": self.config.workspace,
                        "provider": dp.provider,
                        "binary": dp.binary,
                        "cli_name": dp.name,
                    },
                }
                try:
                    resp = await client.post(
                        self._url("/api/nexus/runtimes/daemons/register"),
                        json=payload,
                        headers=self._headers(),
                    )
                    if resp.status_code in (200, 201):
                        logger.info(
                            "Registered runtime %s (%s) on %s",
                            runtime_id, dp.provider, self.config.server_url,
                        )
                    else:
                        logger.warning(
                            "Register %s failed: HTTP %s %s",
                            runtime_id, resp.status_code, resp.text[:200],
                        )
                except Exception as exc:
                    logger.warning("Register %s error: %s", runtime_id, exc)
        self._registered = True
        return True

    async def heartbeat_once(self) -> bool:
        """Send a single heartbeat for every registered runtime."""
        if not self._registered or not self.config.enabled:
            return False
        providers = self._discovered or self.discover()
        all_ok = True
        async with httpx.AsyncClient(timeout=self.config.http_timeout) as client:
            for dp in providers:
                payload = {
                    "status": "idle",
                    "pending_operations": 0,
                    "metadata": {
                        "workspace": self.config.workspace,
                        "provider": dp.provider,
                    },
                }
                try:
                    resp = await client.post(
                        self._url(
                            f"/api/nexus/runtimes/daemons/{self.identity.daemon_id}/heartbeat"
                        ),
                        json=payload,
                        headers=self._headers(),
                    )
                    if resp.status_code == 404:
                        # Server lost us (e.g. data wipe) — re-register on next tick.
                        logger.info("Server reports daemon %s unknown; will re-register", self.identity.daemon_id)
                        self._registered = False
                        return False
                    if resp.status_code != 200:
                        logger.debug("Heartbeat %s/%s: HTTP %s", self.identity.daemon_id, dp.provider, resp.status_code)
                        all_ok = False
                except Exception as exc:
                    logger.debug("Heartbeat %s/%s error: %s", self.identity.daemon_id, dp.provider, exc)
                    all_ok = False
        return all_ok

    # ------------------------------------------------------------------ lifecycle

    async def _heartbeat_loop(self) -> None:
        """Background loop: register, then heartbeat at the configured interval."""
        await self.register()
        while not self._stopping:
            try:
                if not self._registered:
                    await self.register()
                else:
                    await self.heartbeat_once()
            except Exception:
                logger.debug("Heartbeat loop iteration error", exc_info=True)
            try:
                await asyncio.wait_for(
                    asyncio.sleep(self.config.heartbeat_interval),
                    timeout=self.config.heartbeat_interval + 5,
                )
            except asyncio.TimeoutError:
                pass

    async def start(self) -> bool:
        """Begin discovery + registration + heartbeat loop. Returns False if disabled."""
        if not self.config.enabled:
            logger.debug("Daemon client disabled (no AGENT_NEXUS_SERVER_URL)")
            return False
        self._stopping = False
        self._loop_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(
            "Daemon %s started: %d provider(s) -> %s",
            self.identity.daemon_id,
            len(self.discover()),
            self.config.server_url,
        )
        return True

    async def stop(self) -> None:
        """Cancel the heartbeat loop. Best-effort deregister is left to the server sweeper."""
        self._stopping = True
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
        self._loop_task = None

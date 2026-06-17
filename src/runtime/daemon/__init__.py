# -*- coding: utf-8 -*-
"""Daemon package — the host-side agent runtime that aggregates a machine's
installed CLI providers and registers them with a server.

This is the client counterpart to the server-side daemon registry
(``src/server/services/agent_runtimes.py:RuntimeDaemonRegistry``). It was
evolved from the ``teleport`` provider during the daemon-platform refactor.

Lifecycle:
  1. Acquire (or mint) a persistent machine identity (``~/.agent-nexus/daemon.id``).
  2. Auto-discover installed CLI providers via ``shutil.which``.
  3. Register each discovered provider as a runtime row on the server.
  4. Heartbeat on a fixed interval; the server flips stale rows offline.
"""

from .identity import DaemonIdentity, get_or_create_identity, DEFAULT_IDENTITY_PATH
from .discovery import discover_providers, DiscoveredProvider
from .client import DaemonClient, DaemonConfig

__all__ = [
    "DaemonIdentity",
    "get_or_create_identity",
    "DEFAULT_IDENTITY_PATH",
    "discover_providers",
    "DiscoveredProvider",
    "DaemonClient",
    "DaemonConfig",
]

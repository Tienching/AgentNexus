# -*- coding: utf-8 -*-
"""Tests for the daemon subsystem (Phase 4): identity, discovery, client, registry."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

class TestDaemonIdentity:
    def test_mints_persistent_id(self, tmp_path):
        from src.runtime.daemon.identity import get_or_create_identity
        id_path = tmp_path / "daemon.id"
        ident = get_or_create_identity(id_path)
        assert ident.daemon_id.startswith("daemon-")
        # persisted
        data = json.loads(id_path.read_text())
        assert data["daemon_id"] == ident.daemon_id

    def test_reuses_existing_id(self, tmp_path):
        from src.runtime.daemon.identity import get_or_create_identity
        id_path = tmp_path / "daemon.id"
        id_path.parent.mkdir(parents=True, exist_ok=True)
        id_path.write_text(json.dumps({"daemon_id": "daemon-stable", "device_name": "old"}))
        ident = get_or_create_identity(id_path)
        assert ident.daemon_id == "daemon-stable"

    def test_env_override_forces_id(self, monkeypatch, tmp_path):
        from src.runtime.daemon.identity import get_or_create_identity
        monkeypatch.setenv("AGENT_NEXUS_DAEMON_ID", "daemon-forced-123")
        monkeypatch.setenv("AGENT_NEXUS_IDENTITY_PATH", str(tmp_path / "daemon.id"))
        ident = get_or_create_identity()
        assert ident.daemon_id == "daemon-forced-123"

    def test_corrupt_file_re_mints(self, tmp_path):
        from src.runtime.daemon.identity import get_or_create_identity
        id_path = tmp_path / "daemon.id"
        id_path.write_text("not json at all {{{")
        ident = get_or_create_identity(id_path)
        assert ident.daemon_id.startswith("daemon-")


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_discover_uses_registry_meta(self):
        from src.runtime.daemon.discovery import discover_providers
        # python3 itself isn't a provider, but the probe uses shutil.which on the
        # configured binary names. At minimum the function returns a list.
        found = discover_providers()
        assert isinstance(found, list)
        for dp in found:
            assert dp.provider
            assert dp.binary
            assert os.path.basename(dp.binary) or dp.binary

    def test_env_path_override(self, monkeypatch, tmp_path):
        from src.runtime.daemon.discovery import discover_providers, _which
        fake = tmp_path / "fakeclaude"
        fake.write_text("#!/bin/sh\n")
        monkeypatch.setenv("AGENT_NEXUS_CLAUDE_PATH", str(fake))
        # _should_ honor the override
        result = _which("claude")
        assert result == str(fake)


# ---------------------------------------------------------------------------
# triple-key registry
# ---------------------------------------------------------------------------

class TestTripleKeyRegistry:
    def test_one_daemon_multiple_providers(self, tmp_path, monkeypatch):
        from src.runtime.stores.db import Database
        monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "test1.db"))
        Database.reset_instances()
        import src.server.services.agent_runtimes as _ar
        _ar._runtime_daemon_registry = None
        from src.server.services.agent_runtimes import get_runtime_daemon_registry
        reg = get_runtime_daemon_registry()
        reg.register_daemon("host-1", "host-1/claude", workspace="ws", provider="claude")
        reg.register_daemon("host-1", "host-1/hermes", workspace="ws", provider="hermes")
        assert len(reg.list_daemons()) == 2

    def test_re_register_upserts_not_duplicates(self, tmp_path, monkeypatch):
        from src.runtime.stores.db import Database
        monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "test2.db"))
        Database.reset_instances()
        # invalidate the cached registry singleton so it rebuilds against the new DB
        import src.server.services.agent_runtimes as _ar
        _ar._runtime_daemon_registry = None
        from src.server.services.agent_runtimes import get_runtime_daemon_registry
        reg = get_runtime_daemon_registry()
        reg.register_daemon("host-2", "host-2/claude", workspace="ws", provider="claude")
        reg.register_daemon("host-2", "host-2/claude", workspace="ws", provider="claude")
        assert len(reg.list_daemons()) == 1

    def test_different_workspaces_dont_collide(self, tmp_path, monkeypatch):
        from src.runtime.stores.db import Database
        monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "test3.db"))
        Database.reset_instances()
        import src.server.services.agent_runtimes as _ar
        _ar._runtime_daemon_registry = None
        from src.server.services.agent_runtimes import get_runtime_daemon_registry
        reg = get_runtime_daemon_registry()
        reg.register_daemon("host-3", "host-3/claude", workspace="ws-a", provider="claude")
        reg.register_daemon("host-3", "host-3/claude", workspace="ws-b", provider="claude")
        assert len(reg.list_daemons()) == 2


# ---------------------------------------------------------------------------
# client (registration + heartbeat loop, with mocked httpx)
# ---------------------------------------------------------------------------

class TestDaemonClient:
    def test_disabled_when_no_server_url(self):
        from src.runtime.daemon.client import DaemonClient, DaemonConfig
        client = DaemonClient(DaemonConfig(server_url=""))
        assert not client.config.enabled

    async def test_register_calls_server_for_each_provider(self, monkeypatch):
        from src.runtime.daemon.client import DaemonClient, DaemonConfig
        from src.runtime.daemon.discovery import DiscoveredProvider
        cfg = DaemonConfig(server_url="http://server:8080", daemon_id_override="daemon-test")
        client = DaemonClient(cfg)
        # stub discovery to two providers
        client._discovered = [
            DiscoveredProvider("claude", "/usr/bin/claude", "Claude"),
            DiscoveredProvider("hermes", "/home/u/.local/bin/hermes", "Hermes"),
        ]
        mock_resp = MagicMock(status_code=201)
        mock_post = AsyncMock(return_value=mock_resp)
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = mock_post
        with patch("src.runtime.daemon.client.httpx.AsyncClient", return_value=mock_client):
            result = await client.register()
        assert result is True
        assert mock_post.call_count == 2  # one per provider

    async def test_heartbeat_reregisters_on_404(self):
        from src.runtime.daemon.client import DaemonClient, DaemonConfig
        from src.runtime.daemon.discovery import DiscoveredProvider
        cfg = DaemonConfig(server_url="http://server:8080", daemon_id_override="daemon-test")
        client = DaemonClient(cfg)
        client._discovered = [DiscoveredProvider("claude", "/usr/bin/claude", "Claude")]
        client._registered = True
        mock_resp = MagicMock(status_code=404, text="not found")
        mock_post = AsyncMock(return_value=mock_resp)
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = mock_post
        with patch("src.runtime.daemon.client.httpx.AsyncClient", return_value=mock_client):
            result = await client.heartbeat_once()
        assert result is False
        assert client._registered is False  # should re-register next tick


# ---------------------------------------------------------------------------
# WS hub
# ---------------------------------------------------------------------------

class TestDaemonHub:
    async def test_hub_broadcast_sends_to_connections(self):
        from src.server.routers.daemon_ws import DaemonConnectionHub
        hub = DaemonConnectionHub()
        ws1 = MagicMock()
        ws2 = MagicMock()
        ws1.send_text = AsyncMock()
        ws2.send_text = AsyncMock()
        hub._connections.add(ws1)
        hub._connections.add(ws2)
        await hub.broadcast({"type": "task_available"})
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()

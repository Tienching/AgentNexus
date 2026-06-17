# -*- coding: utf-8 -*-
"""Tests for server/relay node mode (Phase 5): runtime_mode column + relay registration."""

from __future__ import annotations

import os
import pytest


class TestNodeRoleConfig:
    def test_default_node_role_is_server(self):
        from src.server.config import ServerSettings
        ss = ServerSettings()
        assert ss.node_role == "server"
        assert ss.relay_upstream_url == ""

    def test_node_role_can_be_relay(self):
        from src.server.config import ServerSettings
        ss = ServerSettings(node_role="relay", relay_upstream_url="http://upstream:8080")
        assert ss.node_role == "relay"
        assert ss.relay_upstream_url == "http://upstream:8080"


class TestRuntimeModeColumn:
    def test_register_local_runtime(self, tmp_path, monkeypatch):
        from src.runtime.stores.db import Database
        monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "local.db"))
        Database.reset_instances()
        import src.server.services.agent_runtimes as _ar
        _ar._runtime_daemon_registry = None
        from src.server.services.agent_runtimes import get_runtime_daemon_registry
        reg = get_runtime_daemon_registry()
        d = reg.register_daemon("host-local", "host-local/claude",
                                workspace="ws", provider="claude", runtime_mode="local")
        assert d.runtime_mode == "local"

    def test_register_relay_runtime(self, tmp_path, monkeypatch):
        from src.runtime.stores.db import Database
        monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "relay.db"))
        Database.reset_instances()
        import src.server.services.agent_runtimes as _ar
        _ar._runtime_daemon_registry = None
        from src.server.services.agent_runtimes import get_runtime_daemon_registry
        reg = get_runtime_daemon_registry()
        d = reg.register_daemon("relay-1", "relay-1/hermes",
                                workspace="ws", provider="hermes", runtime_mode="relay")
        assert d.runtime_mode == "relay"

    def test_local_and_relay_coexist_on_one_board(self, tmp_path, monkeypatch):
        from src.runtime.stores.db import Database
        monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "mixed.db"))
        Database.reset_instances()
        import src.server.services.agent_runtimes as _ar
        _ar._runtime_daemon_registry = None
        from src.server.services.agent_runtimes import get_runtime_daemon_registry
        reg = get_runtime_daemon_registry()
        reg.register_daemon("host-a", "host-a/claude", workspace="ws", provider="claude", runtime_mode="local")
        reg.register_daemon("relay-1", "relay-1/hermes", workspace="ws", provider="hermes", runtime_mode="relay")
        daemons = reg.list_daemons()
        modes = {d.runtime_mode for d in daemons}
        assert modes == {"local", "relay"}


class TestDaemonClientRelay:
    def test_client_runtime_mode_from_node_role_env(self, monkeypatch):
        from src.runtime.daemon.client import DaemonConfig
        monkeypatch.setenv("AGENT_NEXUS_NODE_ROLE", "relay")
        cfg = DaemonConfig.from_env()
        assert cfg.runtime_mode == "relay"

    def test_client_runtime_mode_defaults_local(self, monkeypatch):
        from src.runtime.daemon.client import DaemonConfig
        monkeypatch.delenv("AGENT_NEXUS_NODE_ROLE", raising=False)
        cfg = DaemonConfig.from_env()
        assert cfg.runtime_mode == "local"

    async def test_relay_register_sends_relay_mode(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock, patch
        from src.runtime.daemon.client import DaemonClient, DaemonConfig
        from src.runtime.daemon.discovery import DiscoveredProvider
        cfg = DaemonConfig(server_url="http://upstream:8080",
                           daemon_id_override="relay-test", runtime_mode="relay")
        client = DaemonClient(cfg)
        client._discovered = [DiscoveredProvider("hermes", "/home/u/hermes", "Hermes")]
        captured = {}
        mock_resp = MagicMock(status_code=201)
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        async def capture_post(url, json=None, headers=None):
            captured["payload"] = json
            return mock_resp
        mock_client.post = capture_post
        with patch("src.runtime.daemon.client.httpx.AsyncClient", return_value=mock_client):
            await client.register()
        assert captured["payload"]["runtime_mode"] == "relay"

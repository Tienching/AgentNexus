# -*- coding: utf-8 -*-
"""Regression tests for the 8 CRITICAL issues found in code review.

Each test maps to a review finding (C1-C8) and verifies the fix holds.
These exist precisely because the original tests gave false confidence
(notably C8's --model leak passed a shallow assertion).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# C1+C2+C3: multi-provider aggregation (server-side)
# ---------------------------------------------------------------------------

class TestMultiProviderAggregation:
    """C1 (register triple-key), C2 (heartbeat per-provider), C3 (no false registered)."""

    def _fresh_registry(self, tmp_path, monkeypatch):
        from src.runtime.stores.db import Database
        monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "agg.db"))
        Database.reset_instances()
        import src.server.services.agent_runtimes as _ar
        _ar._runtime_daemon_registry = None
        from src.server.services.agent_runtimes import get_runtime_daemon_registry
        return get_runtime_daemon_registry()

    def test_one_daemon_three_providers_three_rows(self, tmp_path, monkeypatch):
        reg = self._fresh_registry(tmp_path, monkeypatch)
        for prov in ("claude", "hermes", "codex"):
            reg.register_daemon("host-A", f"host-A/{prov}", workspace="ws", provider=prov)
        assert len(reg.list_daemons()) == 3

    def test_heartbeat_targets_specific_provider_row(self, tmp_path, monkeypatch):
        import time
        reg = self._fresh_registry(tmp_path, monkeypatch)
        for prov in ("claude", "hermes"):
            reg.register_daemon("host-B", f"host-B/{prov}", workspace="ws", provider=prov)
        before = {d.provider: d.last_heartbeat for d in reg.list_daemons()}
        time.sleep(0.02)
        reg.record_daemon_heartbeat("host-B", status="running", workspace="ws", provider="hermes")
        after = {d.provider: d.last_heartbeat for d in reg.list_daemons()}
        assert after["hermes"] > before["hermes"], "hermes should advance"
        assert after["claude"] == before["claude"], "claude must NOT advance (C2 leak)"

    def test_get_daemon_with_provider_returns_exact_row(self, tmp_path, monkeypatch):
        reg = self._fresh_registry(tmp_path, monkeypatch)
        reg.register_daemon("host-C", "host-C/claude", workspace="ws", provider="claude")
        reg.register_daemon("host-C", "host-C/hermes", workspace="ws", provider="hermes")
        hermes = reg.get_daemon("host-C", workspace="ws", provider="hermes")
        assert hermes.provider == "hermes"
        claude = reg.get_daemon("host-C", workspace="ws", provider="claude")
        assert claude.provider == "claude"

    async def test_client_register_sends_top_level_workspace_provider(self, monkeypatch):
        """C1: the register payload must carry workspace/provider at top level."""
        from src.runtime.daemon.client import DaemonClient, DaemonConfig
        from src.runtime.daemon.discovery import DiscoveredProvider
        cfg = DaemonConfig(server_url="http://s:8080", daemon_id_override="d-test")
        client = DaemonClient(cfg)
        client._discovered = [DiscoveredProvider("hermes", "/usr/bin/hermes", "Hermes")]
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
        assert captured["payload"]["provider"] == "hermes", "provider must be top-level"
        assert captured["payload"]["workspace"] == "default", "workspace must be top-level"

    async def test_client_not_registered_when_all_providers_fail(self, monkeypatch):
        """C3: _registered stays False if every provider POST fails."""
        from src.runtime.daemon.client import DaemonClient, DaemonConfig
        from src.runtime.daemon.discovery import DiscoveredProvider
        cfg = DaemonConfig(server_url="http://s:8080", daemon_id_override="d-fail")
        client = DaemonClient(cfg)
        client._discovered = [DiscoveredProvider("claude", "/usr/bin/claude", "Claude")]
        mock_resp = MagicMock(status_code=500, text="server error")
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)
        with patch("src.runtime.daemon.client.httpx.AsyncClient", return_value=mock_client):
            result = await client.register()
        assert result is False
        assert client._registered is False, "C3: must not claim registered on total failure"


# ---------------------------------------------------------------------------
# C4: WebSocket auth consistency
# ---------------------------------------------------------------------------

class TestWebSocketAuth:
    def test_token_source_is_nexus_auth_token(self, monkeypatch):
        from src.server.routers.daemon_ws import _authorized
        monkeypatch.setenv("NEXUS_AUTH_TOKEN", "secret-token")
        # nexus_password unset → must use the token, not the password
        from src.server.config import settings
        monkeypatch.setattr(settings, "nexus_password", "", raising=False)
        assert _authorized("secret-token") is True
        assert _authorized("wrong") is False
        assert _authorized(None) is False

    def test_falls_back_to_password_when_no_token(self, monkeypatch):
        from src.server.routers.daemon_ws import _authorized
        monkeypatch.delenv("NEXUS_AUTH_TOKEN", raising=False)
        from src.server.config import settings
        monkeypatch.setattr(settings, "nexus_password", "pw123", raising=False)
        assert _authorized("pw123") is True
        assert _authorized("other") is False

    def test_open_when_nothing_configured(self, monkeypatch):
        from src.server.routers.daemon_ws import _authorized
        monkeypatch.delenv("NEXUS_AUTH_TOKEN", raising=False)
        from src.server.config import settings
        monkeypatch.setattr(settings, "nexus_password", "", raising=False)
        assert _authorized(None) is True


# ---------------------------------------------------------------------------
# C5: identity atomic write
# ---------------------------------------------------------------------------

class TestAtomicIdentity:
    def test_mint_writes_atomically(self, tmp_path, monkeypatch):
        # The fix uses temp+os.replace; verify the file lands intact.
        from src.runtime.daemon.identity import get_or_create_identity
        id_path = tmp_path / "daemon.id"
        ident = get_or_create_identity(id_path)
        import json
        data = json.loads(id_path.read_text())
        assert data["daemon_id"] == ident.daemon_id
        # No leftover temp files in the dir.
        leftovers = [p for p in tmp_path.iterdir() if p.name != "daemon.id"]
        assert leftovers == [], f"temp file leaked: {leftovers}"


# ---------------------------------------------------------------------------
# C6: data-layer nexus defaults replaced by claude
# ---------------------------------------------------------------------------

class TestNexusDefaultsReplaced:
    def test_task_model_default_provider_is_claude(self):
        # Task may be a dataclass or a pydantic model; check the source line directly.
        import pathlib
        src = pathlib.Path("/home/ubuntu/Projects/agent-nexus_feature-dev/src/runtime/models/task_models.py").read_text()
        # Find the provider field declaration and confirm its default is claude.
        import re
        m = re.search(r'provider\s*:\s*str\s*=\s*"(\w+)"', src)
        assert m, "provider field declaration not found"
        assert m.group(1) == "claude", f"expected claude, got {m.group(1)}"

    def test_no_nexus_default_remaining_in_data_layer(self):
        """Grep the data layer for any lingering 'nexus' default."""
        import subprocess, pathlib
        ROOT = pathlib.Path("/home/ubuntu/Projects/agent-nexus_feature-dev")
        files = [
            "src/runtime/models/task_models.py",
            "src/runtime/stores/task_storage.py",
            "src/server/services/task_execution_service.py",
            "src/server/services/run_service.py",
        ]
        hits = []
        for f in files:
            content = (ROOT / f).read_text()
            for i, line in enumerate(content.splitlines(), 1):
                if '"nexus"' in line and ("default" in line.lower() or "or " in line or "= " in line):
                    if "nexus_password" not in line and "NexusSettings" not in line:
                        hits.append(f"{f}:{i}: {line.strip()}")
        assert not hits, f"lingering nexus defaults: {hits}"


# ---------------------------------------------------------------------------
# C7: mission_bridge.py deleted
# ---------------------------------------------------------------------------

def test_mission_bridge_removed():
    import pathlib
    p = pathlib.Path("/home/ubuntu/Projects/agent-nexus_feature-dev/src/server/services/mission_bridge.py")
    assert not p.exists(), "mission_bridge.py should be deleted (C7)"


# ---------------------------------------------------------------------------
# C8: openclaw strips inline --model
# ---------------------------------------------------------------------------

class TestOpenClawModelStripping:
    def test_model_directive_stripped_from_message(self):
        """C8: the --model directive must NOT appear in the --message payload."""
        from src.providers.openclaw import OpenClawCLIExecutor
        from src.providers.base import RequestContext
        ex = OpenClawCLIExecutor()
        ctx = RequestContext(
            session_id="s1", exec_user="u",
            content="--model gpt-4 do the thing", provider="openclaw",
        )
        cmd = ex._build_command(ctx)
        # --model must not be a flag
        assert "--model" not in cmd
        # the message payload must not contain the directive
        msg_idx = cmd.index("--message")
        message = cmd[msg_idx + 1]
        assert "--model" not in message, f"C8 LEAK: message={message!r}"
        assert "do the thing" in message
        assert "gpt-4" not in message

    def test_no_model_directive_passes_through(self):
        from src.providers.openclaw import OpenClawCLIExecutor
        from src.providers.base import RequestContext
        ex = OpenClawCLIExecutor()
        ctx = RequestContext(
            session_id="s1", exec_user="u", content="plain task", provider="openclaw",
        )
        cmd = ex._build_command(ctx)
        msg_idx = cmd.index("--message")
        assert cmd[msg_idx + 1] == "plain task"

    def test_parse_model_param_returns_stripped_model(self):
        from src.providers.openclaw import OpenClawCLIExecutor
        ex = OpenClawCLIExecutor()
        cleaned, model = ex._parse_model_param("--model gpt-4o real task here")
        assert model == "gpt-4o"
        assert "real task here" in cleaned
        assert "--model" not in cleaned

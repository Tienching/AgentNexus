from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.server.routers import nexus_teleport


RAW_ERROR = "connection failed at /srv/private/config with token=secret-value"


@pytest.fixture(autouse=True)
def disable_debug_error_details(monkeypatch):
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("NEXUS_DEBUG_ERRORS", raising=False)


def _assert_sanitized(exc: HTTPException):
    assert exc.status_code == 500
    assert RAW_ERROR not in str(exc.detail)
    assert "/srv/private/config" not in str(exc.detail)
    assert "secret-value" not in str(exc.detail)


@pytest.mark.asyncio
async def test_connect_error_is_sanitized(monkeypatch):
    bridge = SimpleNamespace(connect=AsyncMock(side_effect=RuntimeError(RAW_ERROR)))
    monkeypatch.setattr(nexus_teleport, "_get_bridge", lambda: bridge)

    with pytest.raises(HTTPException) as error:
        await nexus_teleport.connect_remote(
            nexus_teleport.TeleportConnectRequest(remote_url="https://remote.example")
        )

    _assert_sanitized(error.value)


@pytest.mark.asyncio
async def test_execute_error_is_sanitized(monkeypatch):
    bridge = SimpleNamespace(execute_remote=AsyncMock(side_effect=RuntimeError(RAW_ERROR)))
    monkeypatch.setattr(nexus_teleport, "_get_bridge", lambda: bridge)

    with pytest.raises(HTTPException) as error:
        await nexus_teleport.execute_remote(
            nexus_teleport.TeleportExecuteRequest(session_id="session-1", task="run")
        )

    _assert_sanitized(error.value)


@pytest.mark.asyncio
async def test_sync_error_is_sanitized(monkeypatch):
    bridge = SimpleNamespace(sync_state=AsyncMock(side_effect=RuntimeError(RAW_ERROR)))
    monkeypatch.setattr(nexus_teleport, "_get_bridge", lambda: bridge)

    with pytest.raises(HTTPException) as error:
        await nexus_teleport.sync_state(
            nexus_teleport.TeleportSyncRequest(session_id="session-1")
        )

    _assert_sanitized(error.value)

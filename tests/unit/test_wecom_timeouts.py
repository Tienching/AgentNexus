# -*- coding: utf-8 -*-
"""WeCom timeout alignment tests."""

from src.providers.codex import CodexCLIExecutor
from src.server.config import settings
from src.server.routers.nexus import _resolve_session_stale_timeout_seconds
from src.server.services.channel_service import ChannelService


def test_resolve_cli_timeout_uses_wecom_override(monkeypatch):
    monkeypatch.setattr(settings, "cli_timeout", 600)
    monkeypatch.setattr(settings, "wecom_cli_timeout", 1800)
    monkeypatch.setattr(settings, "wecom_bot_cli_timeout", 900)

    assert ChannelService._resolve_cli_timeout("wecom") == 1800
    assert ChannelService._resolve_cli_timeout("wecom_bot") == 900
    assert ChannelService._resolve_cli_timeout("telegram") == 600



def test_resolve_session_stale_timeout_seconds_uses_wecom_override(monkeypatch):
    monkeypatch.setattr(settings, "cli_timeout", 600)
    monkeypatch.setattr(settings, "wecom_cli_timeout", 1800)
    monkeypatch.setattr(settings, "wecom_bot_cli_timeout", 900)

    assert _resolve_session_stale_timeout_seconds("channel_wecom_chat-1") == 1860
    assert _resolve_session_stale_timeout_seconds("channel_wecom_bot_chat-1") == 960
    assert _resolve_session_stale_timeout_seconds("session_abc") == 660



def test_codex_executor_accepts_settings_like_timeout(monkeypatch):
    monkeypatch.setattr(settings, "cli_timeout", 987)

    executor = CodexCLIExecutor(config=settings)

    assert executor.config.timeout == 987

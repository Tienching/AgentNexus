# -*- coding: utf-8 -*-
"""Tests for session_bridge module."""

from src.providers.nanobot.session_bridge import (
    from_nanobot_session_key,
    to_nanobot_channel_and_chat,
    to_nanobot_session_key,
)


class TestToNanobotSessionKey:
    def test_basic(self):
        assert to_nanobot_session_key("abc123") == "nexus:abc123"

    def test_empty(self):
        assert to_nanobot_session_key("") == "nexus:"


class TestToNanobotChannelAndChat:
    def test_basic(self):
        channel, chat_id = to_nanobot_channel_and_chat("abc123")
        assert channel == "nexus"
        assert chat_id == "abc123"


class TestFromNanobotSessionKey:
    def test_round_trip(self):
        session_id = "my-session"
        key = to_nanobot_session_key(session_id)
        assert from_nanobot_session_key(key) == session_id

    def test_non_nexus_key(self):
        assert from_nanobot_session_key("telegram:12345") is None

    def test_cli_key(self):
        assert from_nanobot_session_key("cli:direct") is None

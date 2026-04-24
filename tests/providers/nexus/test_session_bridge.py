# -*- coding: utf-8 -*-
"""Tests for session_bridge module."""

from src.providers.nexus.session_bridge import (
    from_nexus_session_key,
    to_nexus_channel_and_chat,
    to_nexus_session_key,
)


class TestToNexusSessionKey:
    def test_basic(self):
        assert to_nexus_session_key("abc123") == "nexus:abc123"

    def test_empty(self):
        assert to_nexus_session_key("") == "nexus:"


class TestToNexusChannelAndChat:
    def test_basic(self):
        channel, chat_id = to_nexus_channel_and_chat("abc123")
        assert channel == "nexus"
        assert chat_id == "abc123"


class TestFromNexusSessionKey:
    def test_round_trip(self):
        session_id = "my-session"
        key = to_nexus_session_key(session_id)
        assert from_nexus_session_key(key) == session_id

    def test_non_nexus_key(self):
        assert from_nexus_session_key("telegram:12345") is None

    def test_cli_key(self):
        assert from_nexus_session_key("cli:direct") is None

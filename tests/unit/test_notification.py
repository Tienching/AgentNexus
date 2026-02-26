# -*- coding: utf-8 -*-
"""Tests for the unified notification system"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.server.services.notification.models import NotificationTarget, NotificationResult
from src.server.services.notification.base import NotificationSink
from src.server.services.notification.http_webhook_sink import HttpWebhookSink
from src.server.services.notification.telegram_sink import TelegramSink, _split_text
from src.server.services.notification.discord_sink import (
    DiscordSink,
    _split_text as discord_split_text,
    DISCORD_MAX_LENGTH,
    DISCORD_EDIT_THRESHOLD,
)
from src.server.services.notification.feishu_sink import (
    FeishuSink,
    _split_text as feishu_split_text,
    FEISHU_MAX_LENGTH,
    FEISHU_EDIT_THRESHOLD,
)
from src.server.services.notification.slack_sink import (
    SlackSink,
    _split_text as slack_split_text,
    SLACK_MAX_LENGTH,
    SLACK_EDIT_THRESHOLD,
)
from src.server.services.notification.unified_handler import (
    UnifiedNotificationHandler,
    get_notification_handler,
)


# ============== Model Tests ==============

class TestNotificationTarget:
    def test_default_values(self):
        target = NotificationTarget(sink_type="response_url")
        assert target.sink_type == "response_url"
        assert target.response_url == ""
        assert target.channel_name == ""
        assert target.chat_id == ""
        assert target.message_id == ""
        assert target.request_data == {}

    def test_response_url_target(self):
        target = NotificationTarget(
            sink_type="response_url",
            response_url="https://example.com/callback",
            request_data={"msg_id": "123", "user": "test"},
        )
        assert target.response_url == "https://example.com/callback"
        assert target.request_data["msg_id"] == "123"

    def test_telegram_target(self):
        target = NotificationTarget(
            sink_type="telegram",
            channel_name="telegram",
            chat_id="123456",
            message_id="42",
        )
        assert target.sink_type == "telegram"
        assert target.chat_id == "123456"
        assert target.message_id == "42"


class TestNotificationResult:
    def test_success(self):
        result = NotificationResult(success=True, sink_type="telegram", message_id="99")
        assert result.success
        assert result.message_id == "99"
        assert result.error is None

    def test_failure(self):
        result = NotificationResult(success=False, sink_type="response_url", error="timeout")
        assert not result.success
        assert result.error == "timeout"


# ============== Helper Tests ==============

class TestSplitText:
    def test_short_text(self):
        assert _split_text("hello", 4096) == ["hello"]

    def test_exact_limit(self):
        text = "a" * 4096
        assert _split_text(text, 4096) == [text]

    def test_long_text_split(self):
        text = "a" * 5000
        chunks = _split_text(text, 4096)
        assert len(chunks) >= 2
        # Reassembled text should equal original
        reassembled = "".join(chunks)
        assert reassembled == text

    def test_split_at_newline(self):
        text = "line1\n" * 1000
        chunks = _split_text(text, 100)
        for chunk in chunks:
            assert len(chunk) <= 100

    def test_empty_text(self):
        assert _split_text("", 4096) == [""]


# ============== HttpWebhookSink Tests ==============

class TestHttpWebhookSink:
    @pytest.fixture
    def sink(self):
        s = HttpWebhookSink()
        s._handler = AsyncMock()
        return s

    @pytest.mark.asyncio
    async def test_send_text_success(self, sink):
        sink._handler.send_callback = AsyncMock(return_value=True)
        target = NotificationTarget(
            sink_type="response_url",
            response_url="https://example.com/cb",
        )
        result = await sink.send_text(target, "hello")
        assert result.success
        sink._handler.send_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_text_no_url(self, sink):
        target = NotificationTarget(sink_type="response_url")
        result = await sink.send_text(target, "hello")
        assert not result.success
        assert "No response_url" in result.error

    @pytest.mark.asyncio
    async def test_send_progress(self, sink):
        sink._handler.send_callback = AsyncMock(return_value=True)
        target = NotificationTarget(
            sink_type="response_url",
            response_url="https://example.com/cb",
        )
        result = await sink.send_progress(target, "processing…")
        assert result.success

    @pytest.mark.asyncio
    async def test_send_completion_success(self, sink):
        sink._handler.send_callback = AsyncMock(return_value=True)
        target = NotificationTarget(
            sink_type="response_url",
            response_url="https://example.com/cb",
        )
        result = await sink.send_completion(target, "done!", success=True)
        assert result.success
        # Verify the prefix was added
        call_args = sink._handler.send_callback.call_args
        sent_messages = call_args[1].get("messages") or call_args[0][1]
        assert any("✅" in m for m in sent_messages)

    @pytest.mark.asyncio
    async def test_send_completion_failure(self, sink):
        sink._handler.send_callback = AsyncMock(return_value=True)
        target = NotificationTarget(
            sink_type="response_url",
            response_url="https://example.com/cb",
        )
        result = await sink.send_completion(target, "error!", success=False)
        assert result.success
        call_args = sink._handler.send_callback.call_args
        sent_messages = call_args[1].get("messages") or call_args[0][1]
        assert any("❌" in m for m in sent_messages)


# ============== TelegramSink Tests ==============

class TestTelegramSink:
    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        # send_message returns an object with message_id
        msg = MagicMock()
        msg.message_id = 42
        bot.send_message = AsyncMock(return_value=msg)
        bot.edit_message_text = AsyncMock()
        return bot

    @pytest.fixture
    def sink(self, mock_bot):
        s = TelegramSink()
        s._get_bot = MagicMock(return_value=mock_bot)
        return s

    @pytest.mark.asyncio
    async def test_send_text_success(self, sink, mock_bot):
        target = NotificationTarget(
            sink_type="telegram",
            chat_id="123456",
        )
        result = await sink.send_text(target, "hello world")
        assert result.success
        assert result.message_id == "42"
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_text_long_message_splits(self, sink, mock_bot):
        target = NotificationTarget(
            sink_type="telegram",
            chat_id="123456",
        )
        long_text = "x" * 5000
        result = await sink.send_text(target, long_text)
        assert result.success
        # Should have been split into 2 messages
        assert mock_bot.send_message.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_text_no_bot(self):
        s = TelegramSink()
        s._get_bot = MagicMock(return_value=None)
        target = NotificationTarget(sink_type="telegram", chat_id="123")
        result = await s.send_text(target, "test")
        assert not result.success
        assert "not available" in result.error

    @pytest.mark.asyncio
    async def test_send_text_no_chat_id(self, sink):
        target = NotificationTarget(sink_type="telegram", chat_id="")
        result = await sink.send_text(target, "test")
        assert not result.success
        assert "No chat_id" in result.error

    @pytest.mark.asyncio
    async def test_send_progress_new_message(self, sink, mock_bot):
        target = NotificationTarget(
            sink_type="telegram",
            chat_id="123456",
        )
        result = await sink.send_progress(target, "⏳ processing…")
        assert result.success
        assert result.message_id == "42"
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_progress_edit_existing(self, sink, mock_bot):
        target = NotificationTarget(
            sink_type="telegram",
            chat_id="123456",
            message_id="10",
        )
        result = await sink.send_progress(target, "⏳ 50% done")
        assert result.success
        assert result.message_id == "10"
        mock_bot.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_progress_edit_fails_fallback(self, sink, mock_bot):
        """When edit fails, should fall back to sending a new message."""
        mock_bot.edit_message_text = AsyncMock(side_effect=Exception("too old"))
        target = NotificationTarget(
            sink_type="telegram",
            chat_id="123456",
            message_id="10",
        )
        result = await sink.send_progress(target, "⏳ retry")
        assert result.success
        assert result.message_id == "42"
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_completion_short_edits_placeholder(self, sink, mock_bot):
        target = NotificationTarget(
            sink_type="telegram",
            chat_id="123456",
            message_id="10",
        )
        result = await sink.send_completion(target, "task done", success=True)
        assert result.success
        # Should try to edit the existing message
        mock_bot.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_completion_long_sends_new(self, sink, mock_bot):
        target = NotificationTarget(
            sink_type="telegram",
            chat_id="123456",
            message_id="10",
        )
        long_content = "x" * 5000
        result = await sink.send_completion(target, long_content, success=True)
        assert result.success
        # Long content can't be edited in place, should send new messages
        assert mock_bot.send_message.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_text_negative_chat_id(self, sink, mock_bot):
        """Negative chat IDs (group chats) should be handled correctly."""
        target = NotificationTarget(
            sink_type="telegram",
            chat_id="-1001234567890",
        )
        result = await sink.send_text(target, "hello group")
        assert result.success
        call_kwargs = mock_bot.send_message.call_args[1]
        assert call_kwargs["chat_id"] == -1001234567890


# ============== UnifiedNotificationHandler Tests ==============

class TestUnifiedNotificationHandler:
    @pytest.fixture
    def handler(self):
        return UnifiedNotificationHandler()

    @pytest.mark.asyncio
    async def test_unknown_sink_type(self, handler):
        target = NotificationTarget(sink_type="unknown_platform")
        result = await handler.notify(target, "test")
        assert not result.success
        assert "Unknown" in result.error

    @pytest.mark.asyncio
    async def test_notify_routes_to_correct_sink(self, handler):
        mock_sink = AsyncMock(spec=NotificationSink)
        mock_sink.send_text = AsyncMock(
            return_value=NotificationResult(success=True, sink_type="custom")
        )
        handler.register_sink("custom", mock_sink)

        target = NotificationTarget(sink_type="custom")
        result = await handler.notify(target, "hello")
        assert result.success
        mock_sink.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_progress_routes(self, handler):
        mock_sink = AsyncMock(spec=NotificationSink)
        mock_sink.send_progress = AsyncMock(
            return_value=NotificationResult(success=True, sink_type="custom", message_id="99")
        )
        handler.register_sink("custom", mock_sink)

        target = NotificationTarget(sink_type="custom")
        result = await handler.notify_progress(target, "working…")
        assert result.success
        assert result.message_id == "99"

    @pytest.mark.asyncio
    async def test_notify_completion_routes(self, handler):
        mock_sink = AsyncMock(spec=NotificationSink)
        mock_sink.send_completion = AsyncMock(
            return_value=NotificationResult(success=True, sink_type="custom")
        )
        handler.register_sink("custom", mock_sink)

        target = NotificationTarget(sink_type="custom")
        result = await handler.notify_completion(target, "done", success=True)
        assert result.success

    def test_build_target_from_response_url(self, handler):
        target = handler.build_target_from_response_url(
            "https://example.com/cb",
            {"msg_id": "123"},
        )
        assert target.sink_type == "response_url"
        assert target.response_url == "https://example.com/cb"
        assert target.request_data["msg_id"] == "123"

    def test_build_target_from_channel(self, handler):
        target = handler.build_target_from_channel("telegram", "123456", "42")
        assert target.sink_type == "telegram"
        assert target.channel_name == "telegram"
        assert target.chat_id == "123456"
        assert target.message_id == "42"


class TestGetNotificationHandler:
    def test_returns_singleton(self):
        h1 = get_notification_handler()
        h2 = get_notification_handler()
        assert h1 is h2

    def test_has_default_sinks(self):
        handler = get_notification_handler()
        assert handler._get_sink("response_url") is not None
        assert handler._get_sink("telegram") is not None
        assert handler._get_sink("discord") is not None
        assert handler._get_sink("feishu") is not None
        assert handler._get_sink("slack") is not None


# ============== Discord Split Text Tests ==============

class TestDiscordSplitText:
    def test_short_text(self):
        assert discord_split_text("hello", DISCORD_MAX_LENGTH) == ["hello"]

    def test_exact_limit(self):
        text = "a" * DISCORD_MAX_LENGTH
        assert discord_split_text(text, DISCORD_MAX_LENGTH) == [text]

    def test_long_text_split(self):
        text = "a" * 3000
        chunks = discord_split_text(text, DISCORD_MAX_LENGTH)
        assert len(chunks) >= 2
        reassembled = "".join(chunks)
        assert reassembled == text

    def test_split_at_newline(self):
        text = "line1\n" * 500
        chunks = discord_split_text(text, 100)
        for chunk in chunks:
            assert len(chunk) <= 100

    def test_empty_text(self):
        assert discord_split_text("", DISCORD_MAX_LENGTH) == [""]


# ============== DiscordSink Tests ==============

class TestDiscordSink:
    @pytest.fixture
    def mock_channel(self):
        """Mock a discord text channel."""
        ch = AsyncMock()
        msg = MagicMock()
        msg.id = 100
        ch.send = AsyncMock(return_value=msg)
        # fetch_message returns a message object with edit
        fetched_msg = AsyncMock()
        fetched_msg.edit = AsyncMock()
        ch.fetch_message = AsyncMock(return_value=fetched_msg)
        return ch

    @pytest.fixture
    def mock_client(self, mock_channel):
        """Mock the discord.Client."""
        client = AsyncMock()
        client.get_channel = MagicMock(return_value=mock_channel)
        client.fetch_user = AsyncMock()
        return client

    @pytest.fixture
    def sink(self, mock_client):
        s = DiscordSink()
        s._get_client = MagicMock(return_value=mock_client)
        return s

    @pytest.mark.asyncio
    async def test_send_text_success(self, sink, mock_channel):
        target = NotificationTarget(sink_type="discord", chat_id="999")
        result = await sink.send_text(target, "hello discord")
        assert result.success
        assert result.message_id == "100"
        mock_channel.send.assert_called_once_with(content="hello discord")

    @pytest.mark.asyncio
    async def test_send_text_long_message_splits(self, sink, mock_channel):
        target = NotificationTarget(sink_type="discord", chat_id="999")
        long_text = "x" * 3000
        result = await sink.send_text(target, long_text)
        assert result.success
        assert mock_channel.send.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_text_no_client(self):
        s = DiscordSink()
        s._get_client = MagicMock(return_value=None)
        target = NotificationTarget(sink_type="discord", chat_id="999")
        result = await s.send_text(target, "test")
        assert not result.success
        assert "not available" in result.error

    @pytest.mark.asyncio
    async def test_send_text_no_chat_id(self, sink):
        target = NotificationTarget(sink_type="discord", chat_id="")
        result = await sink.send_text(target, "test")
        assert not result.success
        assert "No chat_id" in result.error

    @pytest.mark.asyncio
    async def test_send_text_channel_not_found(self, sink, mock_client):
        mock_client.get_channel = MagicMock(return_value=None)
        mock_client.fetch_user = AsyncMock(return_value=None)
        target = NotificationTarget(sink_type="discord", chat_id="999")
        result = await sink.send_text(target, "test")
        assert not result.success
        assert "Channel not found" in result.error

    @pytest.mark.asyncio
    async def test_send_text_dm_fallback(self, sink, mock_client, mock_channel):
        """When get_channel returns None, should try fetch_user + create_dm."""
        mock_client.get_channel = MagicMock(return_value=None)
        mock_user = AsyncMock()
        mock_user.create_dm = AsyncMock(return_value=mock_channel)
        mock_client.fetch_user = AsyncMock(return_value=mock_user)
        target = NotificationTarget(sink_type="discord", chat_id="999")
        result = await sink.send_text(target, "hello DM")
        assert result.success
        mock_user.create_dm.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_progress_new_message(self, sink, mock_channel):
        target = NotificationTarget(sink_type="discord", chat_id="999")
        result = await sink.send_progress(target, "⏳ processing…")
        assert result.success
        assert result.message_id == "100"
        mock_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_progress_edit_existing(self, sink, mock_channel):
        target = NotificationTarget(
            sink_type="discord", chat_id="999", message_id="50"
        )
        result = await sink.send_progress(target, "⏳ 50% done")
        assert result.success
        assert result.message_id == "50"
        mock_channel.fetch_message.assert_called_once_with(50)

    @pytest.mark.asyncio
    async def test_send_progress_edit_fails_fallback(self, sink, mock_channel):
        """When edit fails, should fall back to sending a new message."""
        mock_channel.fetch_message = AsyncMock(side_effect=Exception("not found"))
        target = NotificationTarget(
            sink_type="discord", chat_id="999", message_id="50"
        )
        result = await sink.send_progress(target, "⏳ retry")
        assert result.success
        assert result.message_id == "100"
        mock_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_progress_truncates_long_status(self, sink, mock_channel):
        """Status text should be truncated to DISCORD_EDIT_THRESHOLD when editing."""
        target = NotificationTarget(
            sink_type="discord", chat_id="999", message_id="50"
        )
        long_status = "x" * 3000
        fetched_msg = AsyncMock()
        fetched_msg.edit = AsyncMock()
        mock_channel.fetch_message = AsyncMock(return_value=fetched_msg)
        result = await sink.send_progress(target, long_status)
        assert result.success
        # Verify the text was truncated
        edit_kwargs = fetched_msg.edit.call_args[1]
        assert len(edit_kwargs["content"]) == DISCORD_EDIT_THRESHOLD

    @pytest.mark.asyncio
    async def test_send_completion_short_edits_placeholder(self, sink, mock_channel):
        target = NotificationTarget(
            sink_type="discord", chat_id="999", message_id="50"
        )
        result = await sink.send_completion(target, "task done", success=True)
        assert result.success
        assert result.message_id == "50"
        # Should fetch the message and edit it
        mock_channel.fetch_message.assert_called_once_with(50)

    @pytest.mark.asyncio
    async def test_send_completion_long_sends_new(self, sink, mock_channel):
        target = NotificationTarget(
            sink_type="discord", chat_id="999", message_id="50"
        )
        long_content = "x" * 3000
        result = await sink.send_completion(target, long_content, success=True)
        assert result.success
        # Long content should be sent as new messages (split)
        assert mock_channel.send.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_completion_failure_prefix(self, sink, mock_channel):
        target = NotificationTarget(sink_type="discord", chat_id="999")
        result = await sink.send_completion(target, "error!", success=False)
        assert result.success
        call_args = mock_channel.send.call_args[1]
        assert "❌" in call_args["content"]

    @pytest.mark.asyncio
    async def test_send_completion_success_prefix(self, sink, mock_channel):
        target = NotificationTarget(sink_type="discord", chat_id="999")
        result = await sink.send_completion(target, "done!", success=True)
        assert result.success
        call_args = mock_channel.send.call_args[1]
        assert "✅" in call_args["content"]

    @pytest.mark.asyncio
    async def test_send_completion_edit_fails_falls_through(self, sink, mock_channel):
        """When editing fails on completion, should fall through to send_text."""
        mock_channel.fetch_message = AsyncMock(side_effect=Exception("forbidden"))
        target = NotificationTarget(
            sink_type="discord", chat_id="999", message_id="50"
        )
        result = await sink.send_completion(target, "short", success=True)
        assert result.success
        # Should have fallen back to send (new message)
        mock_channel.send.assert_called()


# ============== Feishu Split Text Tests ==============

class TestFeishuSplitText:
    def test_short_text(self):
        assert feishu_split_text("hello", FEISHU_MAX_LENGTH) == ["hello"]

    def test_exact_limit(self):
        text = "a" * FEISHU_MAX_LENGTH
        assert feishu_split_text(text, FEISHU_MAX_LENGTH) == [text]

    def test_long_text_split(self):
        text = "a" * 6000
        chunks = feishu_split_text(text, FEISHU_MAX_LENGTH)
        assert len(chunks) >= 2
        reassembled = "".join(chunks)
        assert reassembled == text

    def test_split_at_newline(self):
        text = "line1\n" * 1000
        chunks = feishu_split_text(text, 100)
        for chunk in chunks:
            assert len(chunk) <= 100

    def test_empty_text(self):
        assert feishu_split_text("", FEISHU_MAX_LENGTH) == [""]


# ============== FeishuSink Tests ==============

class TestFeishuSink:
    @pytest.fixture
    def mock_feishu_channel(self):
        """Mock a FeishuChannel instance."""
        ch = AsyncMock()
        # _send_message returns a message_id string
        ch._send_message = AsyncMock(return_value="om_abc123")
        ch.edit_message = AsyncMock(return_value=True)
        return ch

    @pytest.fixture
    def sink(self, mock_feishu_channel):
        s = FeishuSink()
        s._get_channel = MagicMock(return_value=mock_feishu_channel)
        return s

    @pytest.mark.asyncio
    async def test_send_text_success(self, sink, mock_feishu_channel):
        target = NotificationTarget(sink_type="feishu", chat_id="oc_123")
        result = await sink.send_text(target, "hello feishu")
        assert result.success
        assert result.message_id == "om_abc123"
        mock_feishu_channel._send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_text_long_message_splits(self, sink, mock_feishu_channel):
        target = NotificationTarget(sink_type="feishu", chat_id="oc_123")
        long_text = "x" * 6000
        result = await sink.send_text(target, long_text)
        assert result.success
        assert mock_feishu_channel._send_message.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_text_no_channel(self):
        s = FeishuSink()
        s._get_channel = MagicMock(return_value=None)
        target = NotificationTarget(sink_type="feishu", chat_id="oc_123")
        result = await s.send_text(target, "test")
        assert not result.success
        assert "not available" in result.error

    @pytest.mark.asyncio
    async def test_send_text_no_chat_id(self, sink):
        target = NotificationTarget(sink_type="feishu", chat_id="")
        result = await sink.send_text(target, "test")
        assert not result.success
        assert "No chat_id" in result.error

    @pytest.mark.asyncio
    async def test_send_text_send_fails(self, sink, mock_feishu_channel):
        mock_feishu_channel._send_message = AsyncMock(return_value=None)
        target = NotificationTarget(sink_type="feishu", chat_id="oc_123")
        result = await sink.send_text(target, "test")
        assert not result.success
        assert "Failed to send" in result.error

    @pytest.mark.asyncio
    async def test_send_progress_new_message(self, sink, mock_feishu_channel):
        target = NotificationTarget(sink_type="feishu", chat_id="oc_123")
        result = await sink.send_progress(target, "⏳ processing…")
        assert result.success
        assert result.message_id == "om_abc123"
        mock_feishu_channel._send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_progress_edit_existing(self, sink, mock_feishu_channel):
        target = NotificationTarget(
            sink_type="feishu", chat_id="oc_123", message_id="om_existing"
        )
        result = await sink.send_progress(target, "⏳ 50% done")
        assert result.success
        assert result.message_id == "om_existing"
        mock_feishu_channel.edit_message.assert_called_once_with(
            "om_existing", "⏳ 50% done"
        )

    @pytest.mark.asyncio
    async def test_send_progress_edit_fails_fallback(self, sink, mock_feishu_channel):
        """When edit fails, should fall back to sending a new message."""
        mock_feishu_channel.edit_message = AsyncMock(side_effect=Exception("forbidden"))
        target = NotificationTarget(
            sink_type="feishu", chat_id="oc_123", message_id="om_existing"
        )
        result = await sink.send_progress(target, "⏳ retry")
        assert result.success
        assert result.message_id == "om_abc123"
        mock_feishu_channel._send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_progress_edit_returns_false_fallback(self, sink, mock_feishu_channel):
        """When edit returns False, should fall back to sending a new message."""
        mock_feishu_channel.edit_message = AsyncMock(return_value=False)
        target = NotificationTarget(
            sink_type="feishu", chat_id="oc_123", message_id="om_existing"
        )
        result = await sink.send_progress(target, "⏳ retry")
        assert result.success
        assert result.message_id == "om_abc123"
        mock_feishu_channel._send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_progress_truncates_long_status(self, sink, mock_feishu_channel):
        """Status text should be truncated to FEISHU_EDIT_THRESHOLD when editing."""
        target = NotificationTarget(
            sink_type="feishu", chat_id="oc_123", message_id="om_existing"
        )
        long_status = "x" * 6000
        result = await sink.send_progress(target, long_status)
        assert result.success
        # Verify edit was called with truncated text
        edit_args = mock_feishu_channel.edit_message.call_args[0]
        assert len(edit_args[1]) == FEISHU_EDIT_THRESHOLD

    @pytest.mark.asyncio
    async def test_send_completion_short_edits_placeholder(self, sink, mock_feishu_channel):
        target = NotificationTarget(
            sink_type="feishu", chat_id="oc_123", message_id="om_existing"
        )
        result = await sink.send_completion(target, "task done", success=True)
        assert result.success
        assert result.message_id == "om_existing"
        mock_feishu_channel.edit_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_completion_long_sends_new(self, sink, mock_feishu_channel):
        target = NotificationTarget(
            sink_type="feishu", chat_id="oc_123", message_id="om_existing"
        )
        long_content = "x" * 6000
        result = await sink.send_completion(target, long_content, success=True)
        assert result.success
        # Long content should be sent as new messages (split)
        assert mock_feishu_channel._send_message.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_completion_failure_prefix(self, sink, mock_feishu_channel):
        target = NotificationTarget(sink_type="feishu", chat_id="oc_123")
        result = await sink.send_completion(target, "error!", success=False)
        assert result.success
        call_args = mock_feishu_channel._send_message.call_args
        msg = call_args[0][0]  # OutboundMessage
        assert "❌" in msg.content

    @pytest.mark.asyncio
    async def test_send_completion_success_prefix(self, sink, mock_feishu_channel):
        target = NotificationTarget(sink_type="feishu", chat_id="oc_123")
        result = await sink.send_completion(target, "done!", success=True)
        assert result.success
        call_args = mock_feishu_channel._send_message.call_args
        msg = call_args[0][0]  # OutboundMessage
        assert "✅" in msg.content

    @pytest.mark.asyncio
    async def test_send_completion_edit_fails_falls_through(self, sink, mock_feishu_channel):
        """When editing fails on completion, should fall through to send_text."""
        mock_feishu_channel.edit_message = AsyncMock(side_effect=Exception("forbidden"))
        target = NotificationTarget(
            sink_type="feishu", chat_id="oc_123", message_id="om_existing"
        )
        result = await sink.send_completion(target, "short result", success=True)
        assert result.success
        mock_feishu_channel._send_message.assert_called()


# ============== Slack Split Text Tests ==============

class TestSlackSplitText:
    def test_short_text(self):
        assert slack_split_text("hello", SLACK_MAX_LENGTH) == ["hello"]

    def test_exact_limit(self):
        text = "a" * SLACK_MAX_LENGTH
        assert slack_split_text(text, SLACK_MAX_LENGTH) == [text]

    def test_long_text_split(self):
        text = "a" * 6000
        chunks = slack_split_text(text, SLACK_MAX_LENGTH)
        assert len(chunks) >= 2
        reassembled = "".join(chunks)
        assert reassembled == text

    def test_split_at_newline(self):
        text = "line1\n" * 1000
        chunks = slack_split_text(text, 100)
        for chunk in chunks:
            assert len(chunk) <= 100

    def test_empty_text(self):
        assert slack_split_text("", SLACK_MAX_LENGTH) == [""]


# ============== SlackSink Tests ==============

class TestSlackSink:
    @pytest.fixture
    def mock_web_client(self):
        """Mock a Slack AsyncWebClient."""
        client = AsyncMock()
        # chat_postMessage returns a dict-like with ok=True and ts
        client.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "1234567890.123456"})
        client.chat_update = AsyncMock(return_value={"ok": True, "ts": "1234567890.123456"})
        return client

    @pytest.fixture
    def sink(self, mock_web_client):
        s = SlackSink()
        s._get_web_client = MagicMock(return_value=mock_web_client)
        return s

    @pytest.mark.asyncio
    async def test_send_text_success(self, sink, mock_web_client):
        target = NotificationTarget(sink_type="slack", chat_id="C12345")
        result = await sink.send_text(target, "hello slack")
        assert result.success
        assert result.message_id == "1234567890.123456"
        mock_web_client.chat_postMessage.assert_called_once_with(
            channel="C12345", text="hello slack"
        )

    @pytest.mark.asyncio
    async def test_send_text_long_message_splits(self, sink, mock_web_client):
        target = NotificationTarget(sink_type="slack", chat_id="C12345")
        long_text = "x" * 6000
        result = await sink.send_text(target, long_text)
        assert result.success
        assert mock_web_client.chat_postMessage.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_text_no_client(self):
        s = SlackSink()
        s._get_web_client = MagicMock(return_value=None)
        target = NotificationTarget(sink_type="slack", chat_id="C12345")
        result = await s.send_text(target, "test")
        assert not result.success
        assert "not available" in result.error

    @pytest.mark.asyncio
    async def test_send_text_no_chat_id(self, sink):
        target = NotificationTarget(sink_type="slack", chat_id="")
        result = await sink.send_text(target, "test")
        assert not result.success
        assert "No chat_id" in result.error

    @pytest.mark.asyncio
    async def test_send_text_post_fails(self, sink, mock_web_client):
        mock_web_client.chat_postMessage = AsyncMock(return_value={"ok": False, "error": "channel_not_found"})
        target = NotificationTarget(sink_type="slack", chat_id="C12345")
        result = await sink.send_text(target, "test")
        assert not result.success
        assert "Failed to send" in result.error

    @pytest.mark.asyncio
    async def test_send_progress_new_message(self, sink, mock_web_client):
        target = NotificationTarget(sink_type="slack", chat_id="C12345")
        result = await sink.send_progress(target, "⏳ processing…")
        assert result.success
        assert result.message_id == "1234567890.123456"
        mock_web_client.chat_postMessage.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_progress_edit_existing(self, sink, mock_web_client):
        target = NotificationTarget(
            sink_type="slack", chat_id="C12345", message_id="1234567890.111111"
        )
        result = await sink.send_progress(target, "⏳ 50% done")
        assert result.success
        assert result.message_id == "1234567890.111111"
        mock_web_client.chat_update.assert_called_once_with(
            channel="C12345",
            ts="1234567890.111111",
            text="⏳ 50% done",
        )

    @pytest.mark.asyncio
    async def test_send_progress_edit_fails_fallback(self, sink, mock_web_client):
        """When edit fails, should fall back to sending a new message."""
        mock_web_client.chat_update = AsyncMock(side_effect=Exception("not_authed"))
        target = NotificationTarget(
            sink_type="slack", chat_id="C12345", message_id="1234567890.111111"
        )
        result = await sink.send_progress(target, "⏳ retry")
        assert result.success
        assert result.message_id == "1234567890.123456"
        mock_web_client.chat_postMessage.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_progress_edit_not_ok_fallback(self, sink, mock_web_client):
        """When chat.update returns ok=False, should fall back to sending a new message."""
        mock_web_client.chat_update = AsyncMock(return_value={"ok": False, "error": "cant_update_message"})
        target = NotificationTarget(
            sink_type="slack", chat_id="C12345", message_id="1234567890.111111"
        )
        result = await sink.send_progress(target, "⏳ retry")
        assert result.success
        assert result.message_id == "1234567890.123456"
        mock_web_client.chat_postMessage.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_progress_truncates_long_status(self, sink, mock_web_client):
        """Status text should be truncated to SLACK_EDIT_THRESHOLD when editing."""
        target = NotificationTarget(
            sink_type="slack", chat_id="C12345", message_id="1234567890.111111"
        )
        long_status = "x" * 6000
        result = await sink.send_progress(target, long_status)
        assert result.success
        # Verify the text was truncated
        call_kwargs = mock_web_client.chat_update.call_args[1]
        assert len(call_kwargs["text"]) == SLACK_EDIT_THRESHOLD

    @pytest.mark.asyncio
    async def test_send_completion_short_edits_placeholder(self, sink, mock_web_client):
        target = NotificationTarget(
            sink_type="slack", chat_id="C12345", message_id="1234567890.111111"
        )
        result = await sink.send_completion(target, "task done", success=True)
        assert result.success
        assert result.message_id == "1234567890.111111"
        mock_web_client.chat_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_completion_long_sends_new(self, sink, mock_web_client):
        target = NotificationTarget(
            sink_type="slack", chat_id="C12345", message_id="1234567890.111111"
        )
        long_content = "x" * 6000
        result = await sink.send_completion(target, long_content, success=True)
        assert result.success
        # Long content should be sent as new messages (split)
        assert mock_web_client.chat_postMessage.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_completion_failure_prefix(self, sink, mock_web_client):
        target = NotificationTarget(sink_type="slack", chat_id="C12345")
        result = await sink.send_completion(target, "error!", success=False)
        assert result.success
        call_kwargs = mock_web_client.chat_postMessage.call_args[1]
        assert "❌" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_send_completion_success_prefix(self, sink, mock_web_client):
        target = NotificationTarget(sink_type="slack", chat_id="C12345")
        result = await sink.send_completion(target, "done!", success=True)
        assert result.success
        call_kwargs = mock_web_client.chat_postMessage.call_args[1]
        assert "✅" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_send_completion_edit_fails_falls_through(self, sink, mock_web_client):
        """When editing fails on completion, should fall through to send_text."""
        mock_web_client.chat_update = AsyncMock(side_effect=Exception("forbidden"))
        target = NotificationTarget(
            sink_type="slack", chat_id="C12345", message_id="1234567890.111111"
        )
        result = await sink.send_completion(target, "short", success=True)
        assert result.success
        # Should have fallen back to send (new message)
        mock_web_client.chat_postMessage.assert_called()


# ============== Task Model Integration Tests ==============

class TestTaskNotificationTarget:
    def test_task_with_notification_fields(self):
        from src.runtime.models.task_models import Task
        task = Task(
            description="test task",
            notification_sink_type="telegram",
            notification_channel="telegram",
            notification_chat_id="123456",
            notification_message_id="42",
        )
        target = task.get_notification_target()
        assert target is not None
        assert target.sink_type == "telegram"
        assert target.chat_id == "123456"
        assert target.message_id == "42"

    def test_task_with_response_url_legacy(self):
        from src.runtime.models.task_models import Task
        task = Task(
            description="test task",
            response_url="https://example.com/cb",
            callback_msg_id="msg-001",
            callback_user="user1",
        )
        target = task.get_notification_target()
        assert target is not None
        assert target.sink_type == "response_url"
        assert target.response_url == "https://example.com/cb"

    def test_task_without_notification(self):
        from src.runtime.models.task_models import Task
        task = Task(description="no notification")
        target = task.get_notification_target()
        assert target is None

    def test_task_notification_fields_serialization(self):
        from src.runtime.models.task_models import Task
        task = Task(
            description="test",
            notification_sink_type="telegram",
            notification_channel="telegram",
            notification_chat_id="99",
        )
        redis_hash = task.to_redis_hash()
        assert redis_hash["notification_sink_type"] == "telegram"
        assert redis_hash["notification_chat_id"] == "99"

        restored = Task.from_redis_hash(redis_hash)
        assert restored.notification_sink_type == "telegram"
        assert restored.notification_chat_id == "99"
        target = restored.get_notification_target()
        assert target is not None
        assert target.sink_type == "telegram"

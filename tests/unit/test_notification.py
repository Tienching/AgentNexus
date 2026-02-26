# -*- coding: utf-8 -*-
"""Tests for the unified notification system"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.server.services.notification.models import NotificationTarget, NotificationResult
from src.server.services.notification.base import NotificationSink
from src.server.services.notification.http_webhook_sink import HttpWebhookSink
from src.server.services.notification.telegram_sink import TelegramSink, _split_text
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

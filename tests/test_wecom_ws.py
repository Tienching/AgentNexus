"""企微智能机器人 WebSocket 模式测试"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.channels.config import ChannelType, WeComConfig
from src.channels.events import InboundMessage, OutboundMessage
from src.channels.wecom_aibot import WeComChannel
from src.server.services.channel_service import ChannelService
from src.server.services.notification.models import NotificationResult, NotificationTarget
from src.server.services.notification.wecom_sink import WeComSink


class TestWeComConfigModes:
    def test_webhook_mode_basic_creation(self):
        config = WeComConfig(
            token="test_token",
            encoding_aes_key="a" * 43,
        )
        assert config.type == ChannelType.WECOM
        assert config.mode == "webhook"
        assert config.token == "test_token"

    def test_websocket_mode_basic_creation(self):
        config = WeComConfig(
            mode="websocket",
            bot_id="bot_123",
            secret="secret_456",
        )
        assert config.mode == "websocket"
        assert config.bot_id == "bot_123"
        assert config.secret == "secret_456"

    def test_websocket_mode_requires_bot_id(self):
        with pytest.raises(ValueError, match="bot_id"):
            WeComConfig(mode="websocket", secret="secret_456")

    def test_websocket_mode_requires_secret(self):
        with pytest.raises(ValueError, match="secret"):
            WeComConfig(mode="websocket", bot_id="bot_123")


class TestWeComWebSocketProtocol:
    @pytest.mark.asyncio
    async def test_send_via_websocket_wraps_cmd_headers_body(self):
        channel = WeComChannel(
            WeComConfig(mode="websocket", bot_id="bot_123", secret="secret_456")
        )
        channel._ws = SimpleNamespace(send=AsyncMock())

        ok = await channel._send_via_websocket(
            "aibot_subscribe",
            {"bot_id": "bot_123", "secret": "secret_456"},
            req_id="req-1",
        )

        assert ok is True
        payload = json.loads(channel._ws.send.await_args.args[0])
        assert payload == {
            "cmd": "aibot_subscribe",
            "headers": {"req_id": "req-1"},
            "body": {"bot_id": "bot_123", "secret": "secret_456"},
        }

    @pytest.mark.asyncio
    async def test_ws_handle_msg_callback_parses_doc_envelope(self):
        channel = WeComChannel(
            WeComConfig(mode="websocket", bot_id="bot_123", secret="secret_456")
        )
        channel._handle_inbound_message = AsyncMock()

        await channel._ws_handle_msg_callback(
            {
                "cmd": "aibot_msg_callback",
                "headers": {"req_id": "REQUEST_ID"},
                "body": {
                    "msgid": "MSGID",
                    "chatid": "CHATID",
                    "chattype": "group",
                    "from": {"userid": "USERID"},
                    "msgtype": "text",
                    "text": {"content": "@RobotA hello robot"},
                },
            }
        )

        inbound = channel._handle_inbound_message.await_args.args[0]
        assert inbound.chat_id == "CHATID"
        assert inbound.sender_id == "USERID"
        assert inbound.content == "@RobotA hello robot"
        assert inbound.metadata["req_id"] == "REQUEST_ID"
        assert inbound.metadata["ws_mode"] is True

    @pytest.mark.asyncio
    async def test_ws_handle_event_callback_reads_nested_eventtype(self):
        channel = WeComChannel(
            WeComConfig(
                mode="websocket",
                bot_id="bot_123",
                secret="secret_456",
                extra={"welcome_message": "您好，欢迎使用机器人"},
            )
        )
        channel._ws_respond_welcome_msg = AsyncMock(return_value=True)

        await channel._ws_handle_event_callback(
            {
                "cmd": "aibot_event_callback",
                "headers": {"req_id": "REQUEST_ID"},
                "body": {
                    "msgid": "MSGID",
                    "chatid": "CHATID",
                    "from": {"userid": "USERID"},
                    "msgtype": "event",
                    "event": {"eventtype": "enter_chat"},
                },
            }
        )

        channel._ws_respond_welcome_msg.assert_awaited_once_with(
            "REQUEST_ID", "您好，欢迎使用机器人"
        )
        assert channel._latest_req_ids["CHATID"] == "REQUEST_ID"
        assert channel._latest_req_ids["USERID"] == "REQUEST_ID"

    @pytest.mark.asyncio
    async def test_send_ws_stream_update_reuses_original_req_id(self):
        channel = WeComChannel(
            WeComConfig(mode="websocket", bot_id="bot_123", secret="secret_456")
        )
        channel._ws = SimpleNamespace(send=AsyncMock())

        ok = await channel.send_ws_stream_update(
            "REQUEST_ID",
            "stream-1",
            "partial content",
            finish=False,
        )

        assert ok is True
        payload = json.loads(channel._ws.send.await_args.args[0])
        assert payload == {
            "cmd": "aibot_respond_msg",
            "headers": {"req_id": "REQUEST_ID"},
            "body": {
                "msgtype": "stream",
                "stream": {
                    "id": "stream-1",
                    "finish": False,
                    "content": "partial content",
                },
            },
        }

    @pytest.mark.asyncio
    async def test_send_message_uses_ws_active_push_in_websocket_mode(self):
        channel = WeComChannel(
            WeComConfig(mode="websocket", bot_id="bot_123", secret="secret_456")
        )
        channel.send_ws_msg = AsyncMock(return_value=True)

        result = await channel._send_message(
            OutboundMessage(channel="wecom", chat_id="chat-1", content="**hello**")
        )

        assert result is True
        channel.send_ws_msg.assert_awaited_once_with(
            "chat-1", "**hello**", msgtype="markdown"
        )

    @pytest.mark.asyncio
    async def test_websocket_start_enters_standby_when_lock_is_held(self):
        channel = WeComChannel(
            WeComConfig(mode="websocket", bot_id="bot_123", secret="secret_456")
        )
        channel._acquire_ws_process_lock = lambda: False
        channel._ws_connect = AsyncMock()

        await channel._start()

        channel._ws_connect.assert_not_awaited()
        assert channel._http_client is not None
        await channel._stop()


class _FakeWeComWsChannel:
    def __init__(self):
        self.config = SimpleNamespace(ws_stream_interval_ms=0)
        self.updates: list[dict] = []
        self.finishes: list[dict] = []

    async def send_ws_stream_update(self, req_id: str, stream_id: str, content: str, *, finish: bool = False):
        self.updates.append(
            {
                "req_id": req_id,
                "stream_id": stream_id,
                "content": content,
                "finish": finish,
            }
        )
        return True

    async def send_ws_stream_finish(self, req_id: str, stream_id: str, content: str):
        self.finishes.append(
            {
                "req_id": req_id,
                "stream_id": stream_id,
                "content": content,
            }
        )
        return True


class _FakeManager:
    def __init__(self, channel):
        self._channel = channel

    def get_channel(self, name: str):
        if name == "wecom":
            return self._channel
        return None


class _FakeExecResult:
    def __init__(self, final_content: str, *, tool_summaries: list[str] | None = None, is_error: bool = False):
        self.final_content = final_content
        self.is_error = is_error
        self.tool_summaries = tool_summaries or []
        self.tool_call_count = len(self.tool_summaries)


class TestWeComWsStreamProcessing:
    @pytest.mark.asyncio
    async def test_process_wecom_ws_stream_pushes_updates_and_finish(self, monkeypatch):
        service = ChannelService()
        channel = _FakeWeComWsChannel()
        service.manager = _FakeManager(channel)

        async def _fake_build_request(*args, **kwargs):
            return object()

        async def _fake_consume(
            message,
            session_id,
            request,
            *,
            on_text_delta=None,
            on_tool_summary=None,
            on_tool_start=None,
            on_tool_end=None,
        ):
            if on_text_delta:
                await on_text_delta("第一段")
            if on_tool_summary:
                await on_tool_summary("🔧 `Read: /tmp/demo.txt`")
            if on_text_delta:
                await on_text_delta("第二段")
            return _FakeExecResult(
                final_content="第一段\n\n🔧 `Read: /tmp/demo.txt`\n\n第二段\n\n最终答案",
                tool_summaries=["🔧 `Read: /tmp/demo.txt`"],
            )

        monkeypatch.setattr(service, "_build_request", _fake_build_request)
        monkeypatch.setattr(service, "_consume_executor_events", _fake_consume)
        monkeypatch.setattr(service, "_archive_user_message", lambda *args, **kwargs: None)

        message = InboundMessage(
            channel="wecom",
            sender_id="u1",
            chat_id="c1",
            content="hi",
            metadata={"ws_mode": True, "req_id": "req-123"},
        )

        await service._process_wecom_ws_stream(message, "sess-1", "req-123")

        assert channel.updates
        assert channel.updates[0]["req_id"] == "req-123"
        assert channel.updates[0]["finish"] is False
        assert channel.finishes
        assert channel.finishes[0]["req_id"] == "req-123"
        assert "最终答案" in channel.finishes[0]["content"]


class TestWeComSinkProgress:
    @pytest.mark.asyncio
    async def test_send_progress_uses_send_text_in_websocket_mode(self):
        sink = WeComSink()
        target = NotificationTarget(sink_type="wecom", channel_name="wecom", chat_id="chat-1")
        channel = SimpleNamespace(config=SimpleNamespace(mode="websocket"))

        with patch.object(sink, "_get_channel", return_value=channel):
            with patch.object(
                sink,
                "send_text",
                AsyncMock(return_value=NotificationResult(success=True, sink_type="wecom", message_id="ok")),
            ) as mock_send_text:
                result = await sink.send_progress(target, "处理中")

        assert result.success is True
        mock_send_text.assert_awaited_once_with(target, "⏳ 处理中")

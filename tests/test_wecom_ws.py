"""企微智能机器人 WebSocket 模式测试"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.channels.config import ChannelType, WeComConfig
from src.channels.events import InboundMessage, OutboundMessage
from src.channels.wecom_aibot import WECOM_MAX_LENGTH, WeComChannel
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
        assert inbound.content == "hello robot"
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

        async def _send(payload):
            channel._resolve_ws_ack("REQUEST_ID", command="aibot_respond_msg_ack")

        channel._ws = SimpleNamespace(send=AsyncMock(side_effect=_send))

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
    async def test_send_ws_active_message_splits_large_markdown(self):
        channel = WeComChannel(
            WeComConfig(mode="websocket", bot_id="bot_123", secret="secret_456")
        )
        channel.send_ws_msg = AsyncMock(return_value=True)

        result = await channel.send_ws_active_message(
            "chat-1",
            "A" * (WECOM_MAX_LENGTH + 128),
            msgtype="markdown",
            chat_type="group",
        )

        assert result is True
        assert channel.send_ws_msg.await_count == 2
        assert channel.send_ws_msg.await_args_list[0].kwargs["chat_type"] == "group"
        assert channel.send_ws_msg.await_args_list[1].kwargs["chat_type"] == "group"

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
        self.config = SimpleNamespace(
            ws_stream_interval_ms=0,
            ws_stream_soft_limit_seconds=330,
            ws_stream_hard_limit_seconds=350,
        )
        self.updates: list[dict] = []
        self.finishes: list[dict] = []
        self.active_pushes: list[dict] = []

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

    async def send_ws_msg(self, chatid: str, content: str, *, msgtype: str = "markdown", chat_type: int | None = None):
        self.active_pushes.append(
            {
                "chatid": chatid,
                "content": content,
                "msgtype": msgtype,
                "chat_type": chat_type,
            }
        )
        return True

    async def send_ws_active_message(self, chatid: str, content: str, *, msgtype: str = "markdown", chat_type: int | None = None):
        return await self.send_ws_msg(chatid, content, msgtype=msgtype, chat_type=chat_type)


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
            on_tool_display_update=None,
        ):
            if on_text_delta:
                await on_text_delta("第一段")
            if on_tool_summary:
                await on_tool_summary("tool-1", "🔧 `Read: /tmp/demo.txt`")
            if on_text_delta:
                await on_text_delta("\n\n最终答案")
            return _FakeExecResult(
                final_content="第一段\n\n🔧 `Read: /tmp/demo.txt`\n\n第二段\n\n最终答案",
                tool_summaries=["🔧 `Read: /tmp/demo.txt`"],
            )

        monkeypatch.setattr(service, "_build_request", _fake_build_request)
        monkeypatch.setattr(service, "_consume_executor_events", _fake_consume)
        monkeypatch.setattr(service, "_archive_user_message", lambda *args, **kwargs: None)

        # Stop time from progressing so we don't accidentally fall back to active push
        monkeypatch.setattr("src.server.services.channel_service.time.time", lambda: 1000.0)

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


    @pytest.mark.asyncio
    async def test_process_wecom_ws_stream_rolls_over_on_soft_limit(self, monkeypatch):
        service = ChannelService()
        channel = _FakeWeComWsChannel()
        service.manager = _FakeManager(channel)
        fake_now = {"value": 1000.0}

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
            on_tool_display_update=None,
        ):
            if on_text_delta:
                await on_text_delta("第一段。")
            fake_now["value"] += 331  # Exceed soft limit (330s)
            if on_text_delta:
                # This should trigger _maybe_rollover_stream, closing the current stream
                await on_text_delta("第二段。")
            fake_now["value"] += 1
            if on_text_delta:
                # These updates accumulate for the next stream bubble
                await on_text_delta("第三段")
            return _FakeExecResult(final_content="第一段。第二段。第三段")

        monkeypatch.setattr(service, "_build_request", _fake_build_request)
        monkeypatch.setattr(service, "_consume_executor_events", _fake_consume)
        monkeypatch.setattr(service, "_archive_user_message", lambda *args, **kwargs: None)
        monkeypatch.setattr("src.server.services.channel_service.time.time", lambda: fake_now["value"])

        message = InboundMessage(
            channel="wecom",
            sender_id="u1",
            chat_id="c1",
            chat_type="private",
            content="hi",
            metadata={"ws_mode": True, "req_id": "req-123", "chattype": "single"},
        )

        await service._process_wecom_ws_stream(message, "sess-1", "req-123")

        stream_ids = {item["stream_id"] for item in channel.updates + channel.finishes}
        assert len(stream_ids) == 2  # Rolled over once, so two streams
        assert len(channel.finishes) == 2 # Two bubbles should both be finished
        assert "第一段。" in channel.finishes[0]["content"]
        assert "接下文" in channel.finishes[0]["content"]
        assert "第三段" in channel.finishes[1]["content"]

    @pytest.mark.asyncio
    async def test_process_wecom_ws_stream_switches_to_active_send_at_hard_limit(self, monkeypatch):
        service = ChannelService()
        channel = _FakeWeComWsChannel()
        service.manager = _FakeManager(channel)
        fake_now = {"value": 2000.0}

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
            on_tool_display_update=None,
        ):
            if on_text_delta:
                await on_text_delta("前置说明")
            fake_now["value"] += 351  # Exceed hard limit (350s)
            if on_tool_start:
                # Unsafe boundary should stop stream rollover and switch to主动补发
                await on_tool_start("tool-1", "read_file")
            fake_now["value"] += 2
            if on_text_delta:
                await on_text_delta("最终结论")
            return _FakeExecResult(final_content="前置说明最终结论")

        monkeypatch.setattr(service, "_build_request", _fake_build_request)
        monkeypatch.setattr(service, "_consume_executor_events", _fake_consume)
        monkeypatch.setattr(service, "_archive_user_message", lambda *args, **kwargs: None)
        monkeypatch.setattr("src.server.services.channel_service.time.time", lambda: fake_now["value"])

        message = InboundMessage(
            channel="wecom",
            sender_id="u1",
            chat_id="c1",
            chat_type="group",
            content="hi",
            metadata={"ws_mode": True, "req_id": "req-456", "chattype": "group"},
        )

        await service._process_wecom_ws_stream(message, "sess-2", "req-456")

        assert len(channel.finishes) == 1
        assert "完成后将主动发送后续结果" in channel.finishes[0]["content"]
        assert len(channel.active_pushes) == 1
        assert channel.active_pushes[0]["chatid"] == "c1"
        assert channel.active_pushes[0]["chat_type"] == "group"
        assert channel.active_pushes[0]["content"] == "最终结论"


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


class TestWeComWsPendingToolPlaceholder:
    @pytest.mark.asyncio
    async def test_process_wecom_ws_stream_finalizes_unclosed_tool_placeholder(self, monkeypatch):
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
            on_tool_display_update=None,
        ):
            if on_text_delta:
                await on_text_delta("先看一下。")
            if on_tool_start:
                await on_tool_start("tool-1", "read_file")
            if on_text_delta:
                await on_text_delta("最终结论")
            return _FakeExecResult(final_content="先看一下。\n\n🔧 `Read`\n\n最终结论")

        monkeypatch.setattr(service, "_build_request", _fake_build_request)
        monkeypatch.setattr(service, "_consume_executor_events", _fake_consume)
        monkeypatch.setattr(service, "_archive_user_message", lambda *args, **kwargs: None)

        message = InboundMessage(
            channel="wecom",
            sender_id="u1",
            chat_id="c1",
            content="hi",
            metadata={"ws_mode": True, "req_id": "req-789"},
        )

        await service._process_wecom_ws_stream(message, "sess-3", "req-789")

        assert channel.finishes
        final_text = channel.finishes[-1]["content"]
        assert "⏳ `Read: 读取文件`" not in final_text
        assert "🔧 `Read: 读取文件`" in final_text
        assert "最终结论" in final_text


class TestWeComWsSlashNotification:
    """Tests verifying that WS-mode slash commands propagate notification metadata to tasks."""

    @pytest.mark.asyncio
    async def test_ws_mode_request_gets_notification_metadata(self, monkeypatch):
        """After _build_request, the request object should have notification fields set."""
        from src.server.models.legacy import RequestModel

        service = ChannelService()
        channel = _FakeWeComWsChannel()
        service.manager = _FakeManager(channel)

        # Track the request object that was built
        captured = {}

        async def _fake_build_request(msg, sess_id):
            req = RequestModel(content=msg.content, user="test_user")
            captured["request"] = req
            return req

        async def _fake_consume(message, session_id, request, **kwargs):
            return _FakeExecResult(final_content="done")

        monkeypatch.setattr(service, "_build_request", _fake_build_request)
        monkeypatch.setattr(service, "_consume_executor_events", _fake_consume)
        monkeypatch.setattr(service, "_archive_user_message", lambda *a, **kw: None)

        message = InboundMessage(
            channel="wecom",
            sender_id="u1",
            chat_id="test-chat-id",
            content="hello",
            metadata={"ws_mode": True, "req_id": "req-001"},
        )

        await service._process_wecom_ws_stream(message, "sess-test", "req-001")

        req = captured.get("request")
        assert req is not None
        assert getattr(req, "notification_sink_type", None) == "wecom"
        assert getattr(req, "notification_channel", None) == "wecom"
        assert getattr(req, "notification_chat_id", None) == "test-chat-id"

    def test_task_create_with_notification_sink_stores_on_task(self):
        """SlashCommandHandler._handle_task_create stores notification fields on the task."""
        from unittest.mock import MagicMock, patch
        from src.runtime.commands.slash.handler import SlashCommandHandler
        from src.runtime.models.task_models import Task, TaskPriority, TaskStatus

        captured_add_task_kwargs = {}

        def _fake_add_task(**kwargs):
            captured_add_task_kwargs.update(kwargs)
            return Task(
                id="abc123",
                description=kwargs.get("description", ""),
                status=TaskStatus.TODO,
                priority=TaskPriority.THOUGHT,
                notification_sink_type=kwargs.get("notification_sink_type"),
                notification_channel=kwargs.get("notification_channel"),
                notification_chat_id=kwargs.get("notification_chat_id"),
            )

        mock_config = MagicMock()
        mock_config.default_provider = "claude"
        mock_config.default_alias = ""
        mock_config.default_exec_user = ""

        handler = SlashCommandHandler.__new__(SlashCommandHandler)
        handler.config = mock_config

        # Mock user_config_store
        mock_ucs = MagicMock()
        mock_ucs.get_all.return_value = {}
        handler._user_config_store = mock_ucs

        # Patch task_queue.add_task via the handler's underlying attribute if accessible
        mock_tq = MagicMock()
        mock_tq.add_task.side_effect = _fake_add_task
        with patch.object(type(handler), "task_queue", new_callable=lambda: property(lambda self: mock_tq), create=True):
            handler._handle_task_create(
                description="do something",
                notification_sink_type="wecom",
                notification_channel="wecom",
                notification_chat_id="chat-42",
            )

        assert captured_add_task_kwargs.get("notification_sink_type") == "wecom"
        assert captured_add_task_kwargs.get("notification_channel") == "wecom"
        assert captured_add_task_kwargs.get("notification_chat_id") == "chat-42"

    def test_handle_command_forwards_notification_fields_to_task_create(self):
        """handle_command() passes notification_* fields through to _handle_task_create."""
        from unittest.mock import MagicMock, patch as mock_patch
        from src.runtime.commands.slash.handler import SlashCommandHandler

        handler = SlashCommandHandler.__new__(SlashCommandHandler)
        handler.exec_user = "ubuntu"
        handler.config = MagicMock()
        handler.config.default_provider = "claude"
        handler.config.default_alias = ""
        handler.config.default_exec_user = ""
        handler._user_config_store = MagicMock()
        handler._user_config_store.get_all.return_value = {}

        captured_kwargs = {}

        def _fake_create(**kwargs):
            captured_kwargs.update(kwargs)
            return "## task created"

        handler._handle_task_create = _fake_create

        handler.handle_command(
            "/task create -- write tests",
            notification_sink_type="wecom",
            notification_channel="wecom",
            notification_chat_id="chat-99",
        )

        assert captured_kwargs.get("notification_sink_type") == "wecom"
        assert captured_kwargs.get("notification_channel") == "wecom"
        assert captured_kwargs.get("notification_chat_id") == "chat-99"

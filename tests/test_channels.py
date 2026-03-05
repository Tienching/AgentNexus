"""Channels 模块测试"""

import pytest
from datetime import datetime

from src.channels import (
    ChannelManager,
    ChannelRegistry,
    InboundMessage,
    OutboundMessage,
    MessageType,
    MediaAttachment,
    ChannelConfig,
    ChannelType,
    SignalConfig,
)
from src.channels.base import BaseChannel, ChannelState
from src.channels.events import InboundMessage, OutboundMessage
from src.server.services.channel_service import ChannelService
from src.server.config import settings


class MockChannel(BaseChannel):
    """测试用的 Mock Channel"""

    def __init__(self, config):
        super().__init__(config)
        self.sent_messages = []
        self.started = False

    @property
    def channel_type(self) -> str:
        return "mock"

    async def _start(self):
        self.started = True

    async def _stop(self):
        self.started = False

    async def _send_message(self, message):
        self.sent_messages.append(message)
        return {"message_id": "test-123"}





# ============== 事件类测试 ==============

class TestInboundMessage:
    def test_basic_creation(self):
        msg = InboundMessage(
            channel="telegram",
            sender_id="12345",
            content="Hello",
        )
        assert msg.channel == "telegram"
        assert msg.sender_id == "12345"
        assert msg.content == "Hello"
        assert msg.message_type == MessageType.TEXT
        assert msg.chat_id == "12345"  # 默认使用 sender_id

    def test_to_dict(self):
        msg = InboundMessage(
            channel="telegram",
            sender_id="12345",
            sender_name="Test User",
            chat_id="67890",
            content="Hello",
        )
        data = msg.to_dict()
        assert data["channel"] == "telegram"
        assert data["sender_id"] == "12345"
        assert data["sender_name"] == "Test User"
        assert "internal_id" in data
        assert "timestamp" in data

    def test_is_group(self):
        private_msg = InboundMessage(
            channel="telegram",
            sender_id="123",
            chat_type="private",
        )
        assert not private_msg.is_group

        group_msg = InboundMessage(
            channel="telegram",
            sender_id="123",
            chat_type="group",
        )
        assert group_msg.is_group


class TestOutboundMessage:
    def test_creation(self):
        msg = OutboundMessage(
            channel="telegram",
            chat_id="12345",
            content="Hello",
            reply_to="msg-123",
        )
        assert msg.channel == "telegram"
        assert msg.chat_id == "12345"
        assert msg.reply_to == "msg-123"


class TestMediaAttachment:
    def test_to_dict(self):
        att = MediaAttachment(
            url="https://example.com/image.png",
            mime_type="image/png",
            width=100,
            height=100,
        )
        data = att.to_dict()
        assert data["url"] == "https://example.com/image.png"
        assert data["mime_type"] == "image/png"
        assert data["width"] == 100
        assert "file_path" not in data  # None 值被过滤


class _CaptureStorage:
    def __init__(self):
        self.records = []

    def add_session_message(self, session_id, msg):
        self.records.append((session_id, msg))


class TestArchiveUserMessage:
    def test_fallback_to_media_url_tags_when_local_paths_missing(self, monkeypatch):
        service = ChannelService()
        storage = _CaptureStorage()
        monkeypatch.setattr("src.server.services.channel_service.get_session_storage", lambda: storage)

        class _Req:
            content_parts = None
            image_paths = []
            file_paths = []

        message = InboundMessage(
            channel="wecom",
            sender_id="u1",
            chat_id="c1",
            content="介绍一下这个图",
            media=[MediaAttachment(url="https://example.com/a.jpg", mime_type=None)],
        )

        service._archive_user_message(message, "sess1", _Req())

        assert storage.records
        _, saved = storage.records[0]
        assert "{image: https://example.com/a.jpg}" in saved.content
        assert "介绍一下这个图" in saved.content


# ============== 配置类测试 ==============

class TestChannelConfig:
    def test_basic_config(self):
        config = ChannelConfig(
            type=ChannelType.TELEGRAM,
            name="test-bot",
            allowed_users=["user1", "user2"],
        )
        assert config.type == ChannelType.TELEGRAM
        assert config.name == "test-bot"
        assert "user1" in config.allowed_users

    def test_string_type_conversion(self):
        config = ChannelConfig(type="slack")
        assert config.type == ChannelType.SLACK


# ============== Channel 基类测试 ==============

class TestBaseChannel:
    @pytest.fixture
    def channel(self):
        config = ChannelConfig(type="telegram", name="test")  # 使用 telegram 作为测试类型
        return MockChannel(config)

    @pytest.mark.asyncio
    async def test_start_stop(self, channel):
        assert channel.state == ChannelState.IDLE

        await channel.start()
        assert channel.state == ChannelState.RUNNING
        assert channel.started

        await channel.stop()
        assert channel.state == ChannelState.IDLE
        assert not channel.started

    @pytest.mark.asyncio
    async def test_send_message(self, channel):
        await channel.start()

        msg = OutboundMessage(
            channel="mock",
            chat_id="123",
            content="Test",
        )
        result = await channel.send(msg)

        assert len(channel.sent_messages) == 1
        assert result["message_id"] == "test-123"

        await channel.stop()

    def test_is_allowed(self):
        config = ChannelConfig(
            type="telegram",
            allowed_users=["user1"],
            blocked_users=["blocked"],
        )
        channel = MockChannel(config)

        # 白名单模式
        assert channel.is_allowed("user1")
        assert not channel.is_allowed("user2")

        # 黑名单
        assert not channel.is_allowed("blocked")

        # 空白名单 = 允许所有
        config2 = ChannelConfig(type="telegram", blocked_users=[])
        channel2 = MockChannel(config2)
        assert channel2.is_allowed("any_user")

    @pytest.mark.asyncio
    async def test_message_handler(self, channel):
        messages = []

        async def handler(msg):
            messages.append(msg)

        channel.set_message_handler(handler)
        await channel.start()

        inbound = InboundMessage(
            channel="mock",
            sender_id="123",
            content="Test",
        )
        await channel._handle_inbound_message(inbound)

        assert len(messages) == 1
        assert messages[0].content == "Test"

        await channel.stop()

    @pytest.mark.asyncio
    async def test_error_handler_receives_channel(self, channel):
        captured = {}

        async def handler(msg):
            raise RuntimeError("boom")

        async def error_handler(err, channel_name):
            captured["error"] = err
            captured["channel"] = channel_name

        channel.set_message_handler(handler)
        channel.set_error_handler(error_handler)
        await channel.start()

        inbound = InboundMessage(
            channel="mock",
            sender_id="123",
            content="Test",
        )
        await channel._handle_inbound_message(inbound)

        assert captured["channel"] == "mock"
        assert isinstance(captured["error"], RuntimeError)

        await channel.stop()


# ============== Registry 测试 ==============

class TestChannelRegistry:
    @pytest.fixture
    def registry(self):
        return ChannelRegistry()

    def test_register_and_get(self, registry):
        registry.register("mock", MockChannel)

        channel_class = registry.get("mock")
        assert channel_class == MockChannel

    def test_create_channel(self, registry):
        registry.register("mock", MockChannel)

        config = ChannelConfig(type="telegram")
        channel = registry.create("mock", config)

        assert isinstance(channel, MockChannel)
        assert channel.config == config

    def test_list_available(self, registry):
        # 默认应该列出内置通道（如果依赖可用）
        available = registry.list_available()
        assert isinstance(available, list)


# ============== Manager 测试 ==============

class TestChannelManager:
    @pytest.fixture
    def manager(self):
        return ChannelManager()

    @pytest.mark.asyncio
    async def test_initialize(self, manager):
        # 使用 mock 类型直接创建 channel，跳过 registry 创建
        config = ChannelConfig(type="telegram")
        channel = MockChannel(config)
        channel.set_message_handler(manager._handle_message)
        channel.set_error_handler(manager._handle_error)

        manager.channels = {"mock": channel}
        manager.configs = {"mock": config}

        assert "mock" in manager.channels
        assert isinstance(manager.channels["mock"], MockChannel)

    @pytest.mark.asyncio
    async def test_start_stop(self, manager):
        config = ChannelConfig(type="telegram")
        channel = MockChannel(config)
        manager.channels = {"mock": channel}

        await manager.start()
        assert channel.is_running

        await manager.stop()
        assert not channel.is_running

    @pytest.mark.asyncio
    async def test_send(self, manager):
        config = ChannelConfig(type="telegram")
        channel = MockChannel(config)
        await channel.start()

        manager.channels = {"mock": channel}

        msg = OutboundMessage(channel="mock", chat_id="123", content="Test")
        await manager.send("mock", msg)

        assert len(channel.sent_messages) == 1

    @pytest.mark.asyncio
    async def test_broadcast(self, manager):
        config = ChannelConfig(type="telegram")

        channel1 = MockChannel(config)
        channel2 = MockChannel(config)
        await channel1.start()
        await channel2.start()

        manager.channels = {"mock1": channel1, "mock2": channel2}

        msg = OutboundMessage(channel="mock", chat_id="123", content="Broadcast")
        results = await manager.broadcast(msg)

        assert len(results) == 2
        assert results["mock1"]["success"]
        assert results["mock2"]["success"]

    def test_get_channel_info(self, manager):
        config = ChannelConfig(type="telegram")
        channel = MockChannel(config)
        manager.channels = {"mock": channel}

        info = manager.get_channel_info()
        assert len(info) == 1
        assert info[0]["type"] == "mock"


# ============== ChannelService 测试 ==============

class TestChannelService:
    def test_truncate_response_by_channel(self):
        service = ChannelService()
        suffix = "\n\n... (响应被截断)"
        content = "a" * 2000

        truncated = service._truncate_response(content, "discord")
        assert truncated.endswith(suffix)
        assert len(truncated) == 1900 + len(suffix)
        assert service._truncate_response("hi", "discord") == "hi"

    @pytest.mark.asyncio
    async def test_channel_service_includes_whatsapp_signal(self, monkeypatch):
        monkeypatch.setattr(settings, "telegram_bot_token", None)
        monkeypatch.setattr(settings, "slack_bot_token", None)
        monkeypatch.setattr(settings, "slack_app_token", None)
        monkeypatch.setattr(settings, "discord_bot_token", None)
        monkeypatch.setattr(settings, "whatsapp_bridge_url", "ws://localhost:3000")
        monkeypatch.setattr(settings, "whatsapp_bridge_auth_token", "token")
        monkeypatch.setattr(settings, "whatsapp_session_name", "test")
        monkeypatch.setattr(settings, "signal_phone_number", "+123")
        monkeypatch.setattr(settings, "signal_api_url", "http://localhost:8081")

        service = ChannelService()
        ok = await service.initialize()

        assert ok is True
        assert service.manager is not None
        assert "whatsapp" in service.manager.configs
        assert "signal" in service.manager.configs

    def test_signal_requires_httpx(self, monkeypatch):
        import src.channels.signal_ as signal_module

        monkeypatch.setattr(signal_module, "HTTPX_AVAILABLE", False)
        monkeypatch.setattr(signal_module, "httpx", None)

        with pytest.raises(ImportError):
            signal_module.SignalChannel(SignalConfig(phone_number="+123"))

    # ---------- _get_tool_display_name ----------

    def test_tool_display_name_read(self):
        name = ChannelService._get_tool_display_name("Read", {"filePath": "/home/ubuntu/app.py"})
        assert name == "Read: /home/ubuntu/app.py"

    def test_tool_display_name_write(self):
        name = ChannelService._get_tool_display_name("Write", {"file_path": "/src/index.ts"})
        assert name == "Write: /src/index.ts"

    def test_tool_display_name_edit(self):
        name = ChannelService._get_tool_display_name("Edit", {"filePath": "/config.yaml"})
        assert name == "Edit: /config.yaml"

    def test_tool_display_name_bash(self):
        name = ChannelService._get_tool_display_name("Bash", {"explanation": "安装依赖包"})
        assert name == "Bash: 安装依赖包"

    def test_tool_display_name_grep(self):
        name = ChannelService._get_tool_display_name("Grep", {"directory": "/home/ubuntu/project"})
        assert name == "Grep: /home/ubuntu/project"

    def test_tool_display_name_glob(self):
        name = ChannelService._get_tool_display_name("Glob", {"pattern": "*.ts", "target_directory": "/src"})
        assert name == "Glob: *.ts in /src"

    def test_tool_display_name_task(self):
        name = ChannelService._get_tool_display_name("Task", {"subagent_name": "codebuddy", "description": "修复API"})
        assert name == "Task: codebuddy - 修复API"

    def test_tool_display_name_search(self):
        name = ChannelService._get_tool_display_name("WebSearch", {"searchTerm": "GLM-5"})
        assert name == "Search: GLM-5"

    def test_tool_display_name_todos(self):
        import json as _json
        todos = _json.dumps([{"id": "1", "status": "in_progress", "content": "修复登录页"}, {"id": "2", "status": "pending", "content": "优化首页"}])
        name = ChannelService._get_tool_display_name("TodoWrite", {"todos": todos})
        assert name == "Todos: 1/2 - 修复登录页"

    def test_tool_display_name_fallback(self):
        name = ChannelService._get_tool_display_name("mcp__custom_tool", {"foo": "bar"})
        assert name == "mcp__custom_tool"

    def test_tool_display_name_non_dict(self):
        assert ChannelService._get_tool_display_name("Read", "not a dict") == "Read"
        assert ChannelService._get_tool_display_name("Read", None) == "Read"


class _FakeWeComStreamBuffer:
    def __init__(self, full_content: str = ""):
        self.full_content = full_content
        self.finished = False
        self.set_final_calls = 0

    def append(self, text: str) -> None:
        if text:
            self.full_content += text

    def set_final(self, text: str) -> None:
        self.set_final_calls += 1
        self.full_content = text

    def mark_finished(self) -> None:
        self.finished = True


class _FakeWeComChannel:
    def __init__(self, buf: _FakeWeComStreamBuffer):
        self._buf = buf

    def get_stream_buffer_by_id(self, stream_id: str):
        return self._buf


class _FakeManager:
    def __init__(self, channel: _FakeWeComChannel):
        self._channel = channel

    def get_channel(self, name: str):
        if name == "wecom":
            return self._channel
        return None


class _FakeExecResult:
    def __init__(self, final_content: str, is_error: bool = False):
        self.final_content = final_content
        self.is_error = is_error
        self.tool_call_count = 0
        self.tool_summaries = []


class TestWeComStreamFinalization:
    @pytest.mark.asyncio
    async def test_keep_streamed_content_when_final_is_inconsistent(self, monkeypatch):
        service = ChannelService()
        initial = "我看到你想继续工作。让我先看一下是否有之前的记忆文件。"
        buf = _FakeWeComStreamBuffer(full_content=initial)
        service.manager = _FakeManager(_FakeWeComChannel(buf))

        async def _fake_build_request(*args, **kwargs):
            return object()

        async def _fake_consume(*args, **kwargs):
            return _FakeExecResult(final_content="我是新会话，没有之前的记忆。")

        monkeypatch.setattr(service, "_build_request", _fake_build_request)
        monkeypatch.setattr(service, "_consume_executor_events", _fake_consume)
        monkeypatch.setattr(service, "_archive_user_message", lambda *args, **kwargs: None)

        message = InboundMessage(channel="wecom", sender_id="u1", chat_id="c1", content="hi")
        await service._process_wecom_stream(message, "sess1", "stream1")

        assert buf.full_content == initial
        assert buf.set_final_calls == 0
        assert buf.finished is True

    @pytest.mark.asyncio
    async def test_allow_safe_extension_of_streamed_content(self, monkeypatch):
        service = ChannelService()
        initial = "前文"
        buf = _FakeWeComStreamBuffer(full_content=initial)
        service.manager = _FakeManager(_FakeWeComChannel(buf))

        async def _fake_build_request(*args, **kwargs):
            return object()

        async def _fake_consume(*args, **kwargs):
            return _FakeExecResult(final_content="前文后续")

        monkeypatch.setattr(service, "_build_request", _fake_build_request)
        monkeypatch.setattr(service, "_consume_executor_events", _fake_consume)
        monkeypatch.setattr(service, "_archive_user_message", lambda *args, **kwargs: None)

        message = InboundMessage(channel="wecom", sender_id="u1", chat_id="c1", content="hi")
        await service._process_wecom_stream(message, "sess1", "stream1")

        assert buf.full_content == "前文后续"
        assert buf.set_final_calls == 1
        assert buf.finished is True

    @pytest.mark.asyncio
    async def test_tool_summary_has_trailing_blank_line_before_following_text(self, monkeypatch):
        service = ChannelService()
        buf = _FakeWeComStreamBuffer()
        service.manager = _FakeManager(_FakeWeComChannel(buf))

        async def _fake_build_request(*args, **kwargs):
            return object()

        async def _fake_consume(message, session_id, request, *, on_text_delta=None, on_tool_summary=None):
            if on_tool_summary:
                await on_tool_summary("🔧 `Bash: List current directory files`")
            if on_text_delta:
                await on_text_delta("后续正文")
            return _FakeExecResult(final_content="")

        monkeypatch.setattr(service, "_build_request", _fake_build_request)
        monkeypatch.setattr(service, "_consume_executor_events", _fake_consume)
        monkeypatch.setattr(service, "_archive_user_message", lambda *args, **kwargs: None)

        message = InboundMessage(channel="wecom", sender_id="u1", chat_id="c1", content="hi")
        await service._process_wecom_stream(message, "sess1", "stream1")

        assert "🔧 `Bash: List current directory files`\n\n后续正文" in buf.full_content
        assert buf.finished is True

    @pytest.mark.asyncio
    async def test_normalize_final_when_streamed_is_substring(self, monkeypatch):
        service = ChannelService()
        streamed = "工具调用结果：\nCPU: ok"
        final_body = "工具调用结果：\nCPU: ok"
        expected = "🔧 `Bash: Show CPU model`\n\n---\n\n工具调用结果：\nCPU: ok"
        buf = _FakeWeComStreamBuffer(full_content=streamed)
        service.manager = _FakeManager(_FakeWeComChannel(buf))

        async def _fake_build_request(*args, **kwargs):
            return object()

        async def _fake_consume(*args, **kwargs):
            r = _FakeExecResult(final_content=final_body)
            r.tool_call_count = 1
            r.tool_summaries = ["🔧 `Bash: Show CPU model`"]
            return r

        monkeypatch.setattr(service, "_build_request", _fake_build_request)
        monkeypatch.setattr(service, "_consume_executor_events", _fake_consume)
        monkeypatch.setattr(service, "_archive_user_message", lambda *args, **kwargs: None)

        message = InboundMessage(channel="wecom", sender_id="u1", chat_id="c1", content="hi")
        await service._process_wecom_stream(message, "sess1", "stream1")

        assert buf.full_content == expected
        assert buf.set_final_calls == 1

    @pytest.mark.asyncio
    async def test_append_missing_tool_summaries_when_skip_unsafe_override(self, monkeypatch):
        service = ChannelService()
        streamed = "好，先检查系统状态。\n\n🔧 `Bash: Show CPU model`"
        final = "🔧 `Bash: Show CPU model`\n🔧 `Bash: Show system uptime`\n\n---\n\n系统运行正常"
        buf = _FakeWeComStreamBuffer(full_content=streamed)
        service.manager = _FakeManager(_FakeWeComChannel(buf))

        async def _fake_build_request(*args, **kwargs):
            return object()

        async def _fake_consume(*args, **kwargs):
            r = _FakeExecResult(final_content=final)
            r.tool_call_count = 2
            r.tool_summaries = [
                "🔧 `Bash: Show CPU model`",
                "🔧 `Bash: Show system uptime`",
            ]
            return r

        monkeypatch.setattr(service, "_build_request", _fake_build_request)
        monkeypatch.setattr(service, "_consume_executor_events", _fake_consume)
        monkeypatch.setattr(service, "_archive_user_message", lambda *args, **kwargs: None)

        message = InboundMessage(channel="wecom", sender_id="u1", chat_id="c1", content="hi")
        await service._process_wecom_stream(message, "sess1", "stream1")

        assert "🔧 `Bash: Show system uptime`" in buf.full_content
        assert buf.set_final_calls == 0
        assert buf.finished is True


# ============== _process_with_ai Tool Call Tests ==============

import json
from unittest.mock import AsyncMock, MagicMock, patch

from src.server.services.notification.models import NotificationTarget


def _make_stream_event(event: dict) -> str:
    """Helper: wrap an inner event dict into a stream_event JSON line."""
    return json.dumps({"type": "stream_event", "event": event})


async def _fake_executor_factory(events):
    """Create a mock CLIExecutor whose execute() yields the given event strings."""
    mock_executor = MagicMock()

    async def fake_execute(*args, **kwargs):
        for ev in events:
            yield ev

    mock_executor.execute = fake_execute
    return mock_executor


class TestProcessWithAiToolCalls:
    """Tests for tool-call event handling inside _process_with_ai."""

    @pytest.fixture
    def service(self):
        return ChannelService()

    @pytest.fixture
    def inbound(self):
        return InboundMessage(
            channel="telegram",
            sender_id="123",
            content="hello",
        )

    @pytest.fixture
    def target(self):
        return NotificationTarget(sink_type="telegram", chat_id="123")

    @pytest.fixture
    def handler(self):
        h = AsyncMock()
        h.notify_progress = AsyncMock()
        return h

    # --- AG-UI format ---

    @pytest.mark.asyncio
    async def test_agui_tool_call_start_appears_in_response(
        self, service, inbound, target, handler, monkeypatch
    ):
        """TOOL_CALL_START events should produce 🔧 tool name in the response."""
        events = [
            _make_stream_event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Let me check."}}),
            _make_stream_event({"type": "TOOL_CALL_START", "toolCallId": "tc1", "toolCallName": "read_file"}),
            _make_stream_event({"type": "TOOL_CALL_ARGS", "toolCallId": "tc1", "delta": '{"filePath": "/app.py"}'}),
            _make_stream_event({"type": "TOOL_CALL_END", "toolCallId": "tc1"}),
            _make_stream_event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": " Done."}}),
        ]
        mock_exec = await _fake_executor_factory(events)

        with patch("src.server.services.CLIExecutor", return_value=mock_exec):
            monkeypatch.setattr(settings, "cli_timeout", 30)
            monkeypatch.setattr(settings, "exec_user", "ubuntu")
            result = await service._process_with_ai(inbound, "sess1", target, handler)

        assert "🔧" in result
        assert "`Read: /app.py`" in result
        assert "Let me check." in result
        assert "Done." in result

    @pytest.mark.asyncio
    async def test_agui_tool_call_params_brief(
        self, service, inbound, target, handler, monkeypatch
    ):
        """TOOL_CALL_END should append brief params extracted from accumulated args."""
        events = [
            _make_stream_event({"type": "TOOL_CALL_START", "toolCallId": "tc1", "toolCallName": "replace_in_file"}),
            _make_stream_event({"type": "TOOL_CALL_ARGS", "toolCallId": "tc1", "delta": '{"filePath": "/a.py"'}),
            _make_stream_event({"type": "TOOL_CALL_ARGS", "toolCallId": "tc1", "delta": ', "old_str": "x"}'}),
            _make_stream_event({"type": "TOOL_CALL_END", "toolCallId": "tc1"}),
        ]
        mock_exec = await _fake_executor_factory(events)

        with patch("src.server.services.CLIExecutor", return_value=mock_exec):
            monkeypatch.setattr(settings, "cli_timeout", 30)
            monkeypatch.setattr(settings, "exec_user", "ubuntu")
            result = await service._process_with_ai(inbound, "sess1", target, handler)

        assert "`Edit: /a.py`" in result

    @pytest.mark.asyncio
    async def test_agui_multiple_tool_calls(
        self, service, inbound, target, handler, monkeypatch
    ):
        """Multiple TOOL_CALL_START events should all appear."""
        events = [
            _make_stream_event({"type": "TOOL_CALL_START", "toolCallId": "tc1", "toolCallName": "read_file"}),
            _make_stream_event({"type": "TOOL_CALL_END", "toolCallId": "tc1"}),
            _make_stream_event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "middle"}}),
            _make_stream_event({"type": "TOOL_CALL_START", "toolCallId": "tc2", "toolCallName": "write_to_file"}),
            _make_stream_event({"type": "TOOL_CALL_END", "toolCallId": "tc2"}),
        ]
        mock_exec = await _fake_executor_factory(events)

        with patch("src.server.services.CLIExecutor", return_value=mock_exec):
            monkeypatch.setattr(settings, "cli_timeout", 30)
            monkeypatch.setattr(settings, "exec_user", "ubuntu")
            result = await service._process_with_ai(inbound, "sess1", target, handler)

        assert "`read_file`" in result
        assert "`write_to_file`" in result
        assert "middle" in result

    # --- Legacy Claude format ---

    @pytest.mark.asyncio
    async def test_legacy_content_block_start_tool_use(
        self, service, inbound, target, handler, monkeypatch
    ):
        """Legacy content_block_start with tool_use should produce 🔧 in response."""
        events = [
            _make_stream_event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Checking..."}}),
            _make_stream_event({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "name": "execute_command"}}),
            _make_stream_event({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"command": "ls -la"}'}}),
            _make_stream_event({"type": "content_block_stop", "index": 1}),
            _make_stream_event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": " All done."}}),
        ]
        mock_exec = await _fake_executor_factory(events)

        with patch("src.server.services.CLIExecutor", return_value=mock_exec):
            monkeypatch.setattr(settings, "cli_timeout", 30)
            monkeypatch.setattr(settings, "exec_user", "ubuntu")
            result = await service._process_with_ai(inbound, "sess1", target, handler)

        assert "🔧" in result
        assert "`Bash: ls -la`" in result
        assert "Checking..." in result
        assert "All done." in result

    @pytest.mark.asyncio
    async def test_legacy_tool_params_accumulated_across_deltas(
        self, service, inbound, target, handler, monkeypatch
    ):
        """input_json_delta chunks should be accumulated and parsed on content_block_stop."""
        events = [
            _make_stream_event({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "name": "search_content"}}),
            _make_stream_event({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"pattern"'}}),
            _make_stream_event({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": ': "TODO", "directory": "/src"}'}}),
            _make_stream_event({"type": "content_block_stop", "index": 1}),
        ]
        mock_exec = await _fake_executor_factory(events)

        with patch("src.server.services.CLIExecutor", return_value=mock_exec):
            monkeypatch.setattr(settings, "cli_timeout", 30)
            monkeypatch.setattr(settings, "exec_user", "ubuntu")
            result = await service._process_with_ai(inbound, "sess1", target, handler)

        assert "`Grep: /src`" in result

    # --- result event takes precedence ---

    @pytest.mark.asyncio
    async def test_result_event_returns_content_directly(
        self, service, inbound, target, handler, monkeypatch
    ):
        """A 'result' event should return its content immediately, ignoring accumulated parts."""
        events = [
            _make_stream_event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "partial"}}),
            json.dumps({"type": "result", "content": "Final answer from result event."}),
        ]
        mock_exec = await _fake_executor_factory(events)

        with patch("src.server.services.CLIExecutor", return_value=mock_exec):
            monkeypatch.setattr(settings, "cli_timeout", 30)
            monkeypatch.setattr(settings, "exec_user", "ubuntu")
            result = await service._process_with_ai(inbound, "sess1", target, handler)

        assert result == "Final answer from result event."

    @pytest.mark.asyncio
    async def test_result_event_prepends_tool_info(
        self, service, inbound, target, handler, monkeypatch
    ):
        """When tool calls precede a result event, tool info is prepended to the final answer."""
        events = [
            _make_stream_event({"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "name": "WebSearch"}}),
            _make_stream_event({"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": '{"searchTerm": "GLM-5"}'}}),
            _make_stream_event({"type": "content_block_stop", "index": 2}),
            json.dumps({"type": "result", "content": "GLM-5 is a large language model."}),
        ]
        mock_exec = await _fake_executor_factory(events)

        with patch("src.server.services.CLIExecutor", return_value=mock_exec):
            monkeypatch.setattr(settings, "cli_timeout", 30)
            monkeypatch.setattr(settings, "exec_user", "ubuntu")
            result = await service._process_with_ai(inbound, "sess1", target, handler)

        assert "🔧" in result
        assert "`Search: GLM-5`" in result
        assert "GLM-5 is a large language model." in result
        # Tool section should come before the result
        tool_pos = result.index("🔧")
        answer_pos = result.index("GLM-5 is a large language model.")
        assert tool_pos < answer_pos

    # --- text only (no tool calls) still works ---

    @pytest.mark.asyncio
    async def test_text_only_no_tool_calls(
        self, service, inbound, target, handler, monkeypatch
    ):
        """When there are no tool-call events, only text is returned."""
        events = [
            _make_stream_event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello "}}),
            _make_stream_event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "world"}}),
        ]
        mock_exec = await _fake_executor_factory(events)

        with patch("src.server.services.CLIExecutor", return_value=mock_exec):
            monkeypatch.setattr(settings, "cli_timeout", 30)
            monkeypatch.setattr(settings, "exec_user", "ubuntu")
            result = await service._process_with_ai(inbound, "sess1", target, handler)

        assert result == "Hello world"
        assert "🔧" not in result

    # --- empty stream ---

    @pytest.mark.asyncio
    async def test_empty_stream_returns_none(
        self, service, inbound, target, handler, monkeypatch
    ):
        """An empty stream should return None."""
        events = []
        mock_exec = await _fake_executor_factory(events)

        with patch("src.server.services.CLIExecutor", return_value=mock_exec):
            monkeypatch.setattr(settings, "cli_timeout", 30)
            monkeypatch.setattr(settings, "exec_user", "ubuntu")
            result = await service._process_with_ai(inbound, "sess1", target, handler)

        assert result is None

    # --- mixed AG-UI and legacy (unlikely but defensive) ---

    @pytest.mark.asyncio
    async def test_mixed_agui_and_legacy_tool_calls(
        self, service, inbound, target, handler, monkeypatch
    ):
        """Both AG-UI and legacy tool call formats in the same stream."""
        events = [
            # AG-UI tool call
            _make_stream_event({"type": "TOOL_CALL_START", "toolCallId": "tc1", "toolCallName": "read_file"}),
            _make_stream_event({"type": "TOOL_CALL_END", "toolCallId": "tc1"}),
            # Legacy tool call
            _make_stream_event({"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "name": "write_to_file"}}),
            _make_stream_event({"type": "content_block_stop", "index": 2}),
            # Text
            _make_stream_event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "done"}}),
        ]
        mock_exec = await _fake_executor_factory(events)

        with patch("src.server.services.CLIExecutor", return_value=mock_exec):
            monkeypatch.setattr(settings, "cli_timeout", 30)
            monkeypatch.setattr(settings, "exec_user", "ubuntu")
            result = await service._process_with_ai(inbound, "sess1", target, handler)

        assert "`read_file`" in result
        assert "`write_to_file`" in result
        assert "done" in result

    # --- malformed JSON in tool args is silently skipped ---

    @pytest.mark.asyncio
    async def test_malformed_tool_args_skipped(
        self, service, inbound, target, handler, monkeypatch
    ):
        """Invalid JSON in tool args should not crash; params brief is just omitted."""
        events = [
            _make_stream_event({"type": "TOOL_CALL_START", "toolCallId": "tc1", "toolCallName": "some_tool"}),
            _make_stream_event({"type": "TOOL_CALL_ARGS", "toolCallId": "tc1", "delta": "NOT VALID JSON{{{"}),
            _make_stream_event({"type": "TOOL_CALL_END", "toolCallId": "tc1"}),
            _make_stream_event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}}),
        ]
        mock_exec = await _fake_executor_factory(events)

        with patch("src.server.services.CLIExecutor", return_value=mock_exec):
            monkeypatch.setattr(settings, "cli_timeout", 30)
            monkeypatch.setattr(settings, "exec_user", "ubuntu")
            result = await service._process_with_ai(inbound, "sess1", target, handler)

        assert "`some_tool`" in result
        assert "ok" in result


# ============== 集成测试 ==============

@pytest.mark.asyncio
async def test_full_flow():
    """测试完整的消息收发流程"""
    received_messages = []

    async def on_message(msg: InboundMessage):
        received_messages.append(msg)

    # 创建管理器
    config = ChannelConfig(type="telegram", name="test")
    manager = ChannelManager({"test": config})
    manager.on_message = on_message

    # 直接创建并添加 mock channel
    channel = MockChannel(config)
    channel.set_message_handler(manager._handle_message)
    channel.set_error_handler(manager._handle_error)
    manager.channels = {"test": channel}

    await manager.start()

    # 模拟收到消息
    test_msg = InboundMessage(
        channel="mock",
        sender_id="user123",
        content="Hello Bot!",
    )
    await manager.channels["test"]._handle_inbound_message(test_msg)

    # 验证消息被处理
    assert len(received_messages) == 1
    assert received_messages[0].content == "Hello Bot!"

    # 发送回复
    reply = OutboundMessage(
        channel="mock",
        chat_id="user123",
        content="Hello User!",
    )
    await manager.send("test", reply)

    # 验证发送
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0].content == "Hello User!"

    await manager.stop()

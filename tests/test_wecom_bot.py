"""企业微信普通机器人 (WeCom Bot) Channel 测试"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.channels.config import ChannelType, WeComBotConfig
from src.channels.wecom_aibot import WeComCrypto, sanitize_wecom_markdown_content
from src.channels.wecom_bot import (
    WeComBotChannel,
    StreamSimulator,
    WECOM_BOT_MAX_LENGTH,
    WECOM_BOT_TEXT_MAX_BYTES,
    WECOM_BOT_MARKDOWN_MAX_BYTES,
    WECOM_WEBHOOK_MIN_INTERVAL,
)

from src.channels.events import InboundMessage, OutboundMessage, MessageType


# ============== WeComBotConfig 测试 ==============


class TestWeComBotConfig:
    def test_basic_creation_minimal(self):
        """只配置必填项：token + encoding_aes_key + webhook_key"""
        config = WeComBotConfig(
            token="test_token",
            encoding_aes_key="a" * 43,
            webhook_key="test_key",
        )
        assert config.type == ChannelType.WECOM_BOT
        assert config.token == "test_token"
        assert config.webhook_key == "test_key"

    def test_missing_token(self):
        with pytest.raises(ValueError, match="token is required"):
            WeComBotConfig(
                encoding_aes_key="a" * 43,
                webhook_key="key",
            )

    def test_missing_encoding_aes_key(self):
        with pytest.raises(ValueError, match="encoding_aes_key is required"):
            WeComBotConfig(
                token="token",
                webhook_key="key",
            )

    def test_missing_webhook_key(self):
        with pytest.raises(ValueError, match="webhook_key is required"):
            WeComBotConfig(
                token="token",
                encoding_aes_key="a" * 43,
            )

    def test_default_stream_config(self):
        config = WeComBotConfig(
            token="token",
            encoding_aes_key="a" * 43,
            webhook_key="key",
        )
        assert config.stream_chunk_size == 50
        assert config.stream_interval_ms == 200


# ============== StreamSimulator 测试 ==============


class TestStreamSimulator:
    def test_basic_creation(self):
        sim = StreamSimulator(chat_id="test_chat")
        assert sim.chat_id == "test_chat"
        assert sim.full_content == ""
        assert sim.finished is False

    def test_append(self):
        sim = StreamSimulator(chat_id="test")
        sim.append("Hello ")
        sim.append("World")
        assert sim.full_content == "Hello World"

    def test_set_final(self):
        sim = StreamSimulator(chat_id="test")
        sim.append("partial")
        sim.set_final("complete content")
        assert sim.full_content == "complete content"

    def test_mark_finished(self):
        sim = StreamSimulator(chat_id="test")
        assert sim.finished is False
        sim.mark_finished()
        assert sim.finished is True

    def test_get_unsent_content(self):
        sim = StreamSimulator(chat_id="test")
        sim.append("Hello World")
        unsent = sim.get_unsent_content()
        assert unsent == "Hello World"

        sim.mark_sent(5)
        unsent = sim.get_unsent_content()
        assert unsent == " World"

    def test_has_unsent_content(self):
        sim = StreamSimulator(chat_id="test")
        assert sim.has_unsent_content is False
        sim.append("text")
        assert sim.has_unsent_content is True
        sim.mark_sent(4)
        assert sim.has_unsent_content is False

    @pytest.mark.asyncio
    async def test_wait_for_content_immediate(self):
        sim = StreamSimulator(chat_id="test")
        sim.append("text")
        result = await sim.wait_for_content(timeout=0.1)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_content_timeout(self):
        sim = StreamSimulator(chat_id="test")
        result = await sim.wait_for_content(timeout=0.1)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_content_finished(self):
        sim = StreamSimulator(chat_id="test")
        sim.mark_finished()
        result = await sim.wait_for_content(timeout=0.1)
        assert result is True


# ============== WeComBotChannel 测试 ==============


def _make_config(**kwargs):
    """创建测试配置（最小必填：token + encoding_aes_key + webhook_key）"""
    defaults = dict(
        token="test_token_123",
        encoding_aes_key="a" * 43,
        webhook_key="test_webhook_key",
    )
    defaults.update(kwargs)
    return WeComBotConfig(**defaults)


class TestWeComBotChannel:
    def test_channel_type(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        assert channel.channel_type == "wecom_bot"

    @pytest.mark.asyncio
    async def test_start_stop(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()
        assert channel._http_client is not None
        assert channel._crypto is not None

        await channel._stop()
        assert channel._http_client is None
        assert channel._crypto is None

    @pytest.mark.asyncio
    async def test_verify_url(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        # 创建一个有效的加密 echostr
        crypto = channel._crypto
        encrypted_echo = crypto.encrypt("test_echo_string")
        timestamp = "1234567890"
        nonce = "test_nonce"
        signature = crypto._generate_signature(timestamp, nonce, encrypted_echo)

        result = channel.verify_url(signature, timestamp, nonce, encrypted_echo)
        assert result == "test_echo_string"

        await channel._stop()

    @pytest.mark.asyncio
    async def test_verify_url_bad_signature(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        result = channel.verify_url("bad_sig", "123", "nonce", "encrypted")
        assert result is None

        await channel._stop()

    @pytest.mark.asyncio
    async def test_handle_webhook_text_message(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        # Mock the inbound handler
        handler = AsyncMock()
        channel.set_message_handler(handler)

        crypto = channel._crypto
        payload = {
            "msgtype": "text",
            "msgid": "msg_001",
            "chattype": "group",
            "chatid": "group_test",
            "from": {"userid": "user_123"},
            "text": {"content": "Hello Bot"},
        }
        encrypted = crypto.encrypt(json.dumps(payload))
        timestamp = "1234567890"
        nonce = "test_nonce"
        signature = crypto._generate_signature(timestamp, nonce, encrypted)

        body = json.dumps({"encrypt": encrypted}).encode("utf-8")
        query_params = {
            "msg_signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
        }

        result = await channel.handle_webhook(body, {}, query_params)
        # 普通机器人不返回被动回复
        assert result is None

        # 验证消息处理器被调用
        assert handler.called
        inbound: InboundMessage = handler.call_args[0][0]
        assert inbound.channel == "wecom_bot"
        assert inbound.sender_id == "user_123"
        assert inbound.content == "Hello Bot"
        assert inbound.message_type == MessageType.TEXT
        assert "simulator_id" in inbound.metadata

        await channel._stop()

    @pytest.mark.asyncio
    async def test_handle_webhook_image_message(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        handler = AsyncMock()
        channel.set_message_handler(handler)

        crypto = channel._crypto
        payload = {
            "msgtype": "image",
            "msgid": "msg_002",
            "chattype": "group",
            "chatid": "group_1",
            "from": {"userid": "user_456"},
            "image": {"url": "https://example.com/image.jpg"},
        }
        encrypted = crypto.encrypt(json.dumps(payload))
        timestamp = "1234567890"
        nonce = "test_nonce"
        signature = crypto._generate_signature(timestamp, nonce, encrypted)

        body = json.dumps({"encrypt": encrypted}).encode("utf-8")
        query_params = {
            "msg_signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
        }

        await channel.handle_webhook(body, {}, query_params)
        assert handler.called
        inbound: InboundMessage = handler.call_args[0][0]
        assert inbound.message_type == MessageType.IMAGE
        assert len(inbound.media) == 1
        assert inbound.media[0].url == "https://example.com/image.jpg"

        await channel._stop()

    @pytest.mark.asyncio
    async def test_send_via_webhook(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        # Mock httpx response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        channel._http_client.post = AsyncMock(return_value=mock_response)

        result = await channel._send_via_webhook("test message")
        assert result is not None
        assert result["errcode"] == 0

        # Verify URL contains key
        call_args = channel._http_client.post.call_args
        assert "key=test_webhook_key" in call_args[0][0]

        await channel._stop()

    @pytest.mark.asyncio
    async def test_send_message_webhook_mode(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"errcode": 0}
        channel._http_client.post = AsyncMock(return_value=mock_response)

        msg = OutboundMessage(
            channel="wecom_bot",
            chat_id="chat_1",
            content="Hello from bot",
        )
        result = await channel._send_message(msg)
        assert result is not None

        await channel._stop()

    @pytest.mark.asyncio
    async def test_stream_simulator_lifecycle(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        handler = AsyncMock()
        channel.set_message_handler(handler)

        crypto = channel._crypto
        payload = {
            "msgtype": "text",
            "msgid": "msg_003",
            "chattype": "group",
            "chatid": "group_test",
            "from": {"userid": "user_789"},
            "text": {"content": "test"},
        }
        encrypted = crypto.encrypt(json.dumps(payload))
        timestamp = "123"
        nonce = "nonce"
        signature = crypto._generate_signature(timestamp, nonce, encrypted)
        body = json.dumps({"encrypt": encrypted}).encode("utf-8")
        query_params = {
            "msg_signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
        }

        await channel.handle_webhook(body, {}, query_params)

        # Verify simulator was created
        inbound = handler.call_args[0][0]
        simulator_id = inbound.metadata["simulator_id"]
        sim = channel.get_stream_simulator_by_id(simulator_id)
        assert sim is not None
        assert sim.chat_id == "group_test"

        # Also accessible by chat_id
        sim2 = channel.get_stream_simulator("group_test")
        assert sim2 is sim

        await channel._stop()

    @pytest.mark.asyncio
    async def test_edit_message_unsupported(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        result = await channel.edit_message("msg_1", "new content")
        assert result is False


# ============== Registry 测试 ==============


class TestWeComBotRegistry:
    def test_registry_includes_wecom_bot(self):
        from src.channels.registry import ChannelRegistry
        registry = ChannelRegistry()
        channel_class = registry.get("wecom_bot")
        assert channel_class is not None
        assert channel_class.__name__ == "WeComBotChannel"

    def test_config_map_includes_wecom_bot(self):
        from src.channels.config import CONFIG_MAP, ChannelType
        assert ChannelType.WECOM_BOT in CONFIG_MAP
        assert CONFIG_MAP[ChannelType.WECOM_BOT] == WeComBotConfig


# ============== 字节截断辅助方法测试 ==============


class TestTruncateToBytes:
    def test_short_ascii(self):
        result = WeComBotChannel._truncate_to_bytes("hello", 100)
        assert result == "hello"

    def test_exact_limit(self):
        text = "a" * 2048
        result = WeComBotChannel._truncate_to_bytes(text, 2048)
        assert result == text

    def test_truncate_ascii(self):
        text = "a" * 3000
        result = WeComBotChannel._truncate_to_bytes(text, 2048)
        assert len(result.encode("utf-8")) <= 2048
        assert len(result) == 2048

    def test_truncate_multibyte_chinese(self):
        # 每个中文字符 3 字节 UTF-8
        text = "测" * 1000  # 3000 bytes
        result = WeComBotChannel._truncate_to_bytes(text, 2048)
        encoded = result.encode("utf-8")
        assert len(encoded) <= 2048
        # 确保不截断半个字符
        assert encoded.decode("utf-8")  # should not raise

    def test_empty_string(self):
        assert WeComBotChannel._truncate_to_bytes("", 100) == ""


# ============== Webhook 消息类型测试 ==============


class TestWebhookMessageTypes:
    @pytest.mark.asyncio
    async def test_send_text_with_mentioned_list(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        channel._http_client.post = AsyncMock(return_value=mock_response)

        result = await channel._send_via_webhook(
            "Hello @all",
            msgtype="text",
            mentioned_list=["user1", "@all"],
            mentioned_mobile_list=["13800001111"],
            chatid="group_chat_001",
        )
        assert result is not None
        assert result["errcode"] == 0

        # Verify body contains mentioned_list and chatid
        call_kwargs = channel._http_client.post.call_args
        body = call_kwargs[1]["json"]
        assert body["msgtype"] == "text"
        assert body["chatid"] == "group_chat_001"
        assert body["text"]["mentioned_list"] == ["user1", "@all"]
        assert body["text"]["mentioned_mobile_list"] == ["13800001111"]

        await channel._stop()

    @pytest.mark.asyncio
    async def test_send_markdown_includes_chatid(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        channel._http_client.post = AsyncMock(return_value=mock_response)

        result = await channel._send_via_webhook("**test**", chatid="group_chat_002")
        assert result is not None

        call_kwargs = channel._http_client.post.call_args
        body = call_kwargs[1]["json"]
        assert body["msgtype"] == "markdown"
        assert body["chatid"] == "group_chat_002"

        await channel._stop()


    @pytest.mark.asyncio
    async def test_send_markdown_v2(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        channel._http_client.post = AsyncMock(return_value=mock_response)

        result = await channel._send_via_webhook(
            "# Title\n\n**bold** *italic*",
            msgtype="markdown_v2",
        )
        assert result is not None

        call_kwargs = channel._http_client.post.call_args
        body = call_kwargs[1]["json"]
        assert body["msgtype"] == "markdown_v2"
        assert "markdown_v2" in body

        await channel._stop()

    @pytest.mark.asyncio
    async def test_send_default_markdown(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"errcode": 0}
        channel._http_client.post = AsyncMock(return_value=mock_response)

        result = await channel._send_via_webhook("**test**")
        assert result is not None

        call_kwargs = channel._http_client.post.call_args
        body = call_kwargs[1]["json"]
        assert body["msgtype"] == "markdown"

        await channel._stop()

    @pytest.mark.asyncio
    async def test_send_markdown_preserves_original_syntax(self):
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        channel._http_client.post = AsyncMock(return_value=mock_response)

        content = "文件 1: `/tmp/demo.py`\n\n```\n# 标题\n```\n"
        result = await channel._send_via_webhook(content)
        assert result is not None

        call_kwargs = channel._http_client.post.call_args
        body = call_kwargs[1]["json"]
        sent = body["markdown"]["content"]
        assert sent == content
        assert "`/tmp/demo.py`" in sent

        assert "# 标题" in sent
        assert "```" in sent

        await channel._stop()


# ============== 常量测试 ==============





class TestConstants:
    def test_text_max_bytes(self):
        assert WECOM_BOT_TEXT_MAX_BYTES == 2048

    def test_markdown_max_bytes(self):
        assert WECOM_BOT_MARKDOWN_MAX_BYTES == 4096

    def test_webhook_min_interval(self):
        assert WECOM_WEBHOOK_MIN_INTERVAL == 3.0

    def test_legacy_max_length(self):
        assert WECOM_BOT_MAX_LENGTH == 20480


# ============== 单聊/群聊 chat_type 区分测试 ==============


class TestChatTypeDispatch:
    """测试 _handle_message 根据 chattype 正确设置 chat_type"""

    @pytest.mark.asyncio
    async def test_single_chat_sets_private(self):
        """单聊消息 chattype=single → 返回被动回复提示（不走 AI 处理）"""
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        handler = AsyncMock()
        channel.set_message_handler(handler)

        crypto = channel._crypto
        payload = {
            "msgtype": "text",
            "msgid": "msg_single_001",
            "chattype": "single",
            "chatid": "",
            "from": {"userid": "user_single"},
            "text": {"content": "hello"},
        }
        encrypted = crypto.encrypt(json.dumps(payload))
        timestamp = "123"
        nonce = "nonce"
        signature = crypto._generate_signature(timestamp, nonce, encrypted)
        body = json.dumps({"encrypt": encrypted}).encode("utf-8")
        query_params = {
            "msg_signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
        }

        result = await channel.handle_webhook(body, {}, query_params)

        # Single chat returns a passive reply (encrypted), handler NOT called
        assert result is not None
        assert "encrypt" in result
        assert not handler.called

        await channel._stop()

    @pytest.mark.asyncio
    async def test_group_chat_sets_group(self):
        """群聊消息 chattype=group → chat_type='group'"""
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        handler = AsyncMock()
        channel.set_message_handler(handler)

        crypto = channel._crypto
        payload = {
            "msgtype": "text",
            "msgid": "msg_group_001",
            "chattype": "group",
            "chatid": "group_chat_123",
            "from": {"userid": "user_group"},
            "text": {"content": "hello group"},
        }
        encrypted = crypto.encrypt(json.dumps(payload))
        timestamp = "123"
        nonce = "nonce"
        signature = crypto._generate_signature(timestamp, nonce, encrypted)
        body = json.dumps({"encrypt": encrypted}).encode("utf-8")
        query_params = {
            "msg_signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
        }

        await channel.handle_webhook(body, {}, query_params)

        inbound = handler.call_args[0][0]
        assert inbound.chat_type == "group"
        assert inbound.chat_id == "group_chat_123"

        await channel._stop()

    @pytest.mark.asyncio
    async def test_single_chat_uses_userid_as_chatid(self):
        """单聊时 chatid 为空，被动回复路径仍返回加密响应"""
        config = _make_config()
        channel = WeComBotChannel(config)
        await channel._start()

        handler = AsyncMock()
        channel.set_message_handler(handler)

        crypto = channel._crypto
        payload = {
            "msgtype": "text",
            "msgid": "msg_004",
            "chattype": "single",
            "chatid": "",  # 单聊 chatid 为空
            "from": {"userid": "user_fallback"},
            "text": {"content": "test"},
        }
        encrypted = crypto.encrypt(json.dumps(payload))
        timestamp = "123"
        nonce = "nonce"
        signature = crypto._generate_signature(timestamp, nonce, encrypted)
        body = json.dumps({"encrypt": encrypted}).encode("utf-8")
        query_params = {
            "msg_signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
        }

        result = await channel.handle_webhook(body, {}, query_params)

        # Single chat returns passive reply, handler NOT called
        assert result is not None
        assert "encrypt" in result
        assert not handler.called

        await channel._stop()

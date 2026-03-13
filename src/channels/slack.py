"""Slack Channel 实现

基于 slack-sdk 库，支持 Socket Mode 和 HTTP Webhook 两种模式。
参考 openclaw 的 slack 实现。
"""

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any, Optional

from .base import BaseChannel
from .events import InboundMessage, MediaAttachment, MessageType, OutboundMessage

logger = logging.getLogger(__name__)

# 延迟导入 slack 库
try:
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.socket_mode.aiohttp import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse
    SLACK_AVAILABLE = True
except ImportError:
    SLACK_AVAILABLE = False

if TYPE_CHECKING:
    from .config import SlackConfig


class SlackChannel(BaseChannel):
    """Slack 消息通道"""

    def __init__(self, config: "SlackConfig"):
        if not SLACK_AVAILABLE:
            raise ImportError(
                "Slack support requires 'slack-sdk'. "
                "Install with: pip install 'agent-nexus[slack]'"
            )
        super().__init__(config)
        self.config: "SlackConfig" = config
        self._web_client: Optional[Any] = None
        self._socket_client: Optional[Any] = None
        self._bot_user_id: Optional[str] = None

    @property
    def channel_type(self) -> str:
        return "slack"

    async def _start(self) -> None:
        """启动 Slack 连接"""
        self._web_client = AsyncWebClient(token=self.config.bot_token)

        # 获取 bot 用户信息
        try:
            auth_info = await self._web_client.auth_test()
            self._bot_user_id = auth_info.get("user_id")
            logger.info(f"[{self.name}] Authenticated as {auth_info.get('user')}")
        except Exception as e:
            logger.error(f"[{self.name}] Auth test failed: {e}")
            raise

        if self.config.socket_mode:
            await self._start_socket_mode()
        else:
            logger.info(f"[{self.name}] HTTP mode - webhook endpoint ready")

    async def _start_socket_mode(self) -> None:
        """启动 Socket Mode"""
        self._socket_client = SocketModeClient(
            app_token=self.config.app_token,
            web_client=self._web_client,
        )

        # 注册事件处理器
        self._socket_client.socket_mode_request_listeners.append(self._on_socket_request)

        # 启动连接
        await self._socket_client.connect()
        logger.info(f"[{self.name}] Socket Mode connected")

    async def _stop(self) -> None:
        """停止 Slack 连接"""
        if self._socket_client:
            await self._socket_client.close()
            self._socket_client = None

        self._web_client = None

    async def _send_message(self, message: OutboundMessage) -> Optional[Any]:
        """发送消息到 Slack"""
        if not self._web_client:
            return None

        # 构建消息块
        blocks = []
        if message.content:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message.content,
                }
            })

        kwargs = {
            "channel": message.chat_id,
            "text": message.content or "",
            "blocks": blocks if blocks else None,
            "unfurl_links": True,
        }

        if message.reply_to:
            kwargs["thread_ts"] = message.reply_to

        if message.silent:
            kwargs["unfurl_links"] = False

        # 移除 None 值
        kwargs = {k: v for k, v in kwargs.items() if v is not None}

        return await self._web_client.chat_postMessage(**kwargs)

    async def _on_socket_request(self, client: Any, req: Any) -> None:
        """处理 Socket Mode 请求"""
        if req.type == "events_api":
            # 确认收到事件
            response = SocketModeResponse(envelope_id=req.envelope_id)
            await client.send_socket_mode_response(response)

            # 处理事件
            await self._handle_event(req.payload)

        elif req.type == "slash_commands":
            # 处理斜杠命令
            response = SocketModeResponse(envelope_id=req.envelope_id)
            await client.send_socket_mode_response(response)
            await self._handle_slash_command(req.payload)

        elif req.type == "interactive":
            # 处理交互事件
            response = SocketModeResponse(envelope_id=req.envelope_id)
            await client.send_socket_mode_response(response)

    async def _handle_event(self, payload: dict) -> None:
        """处理事件 API 事件"""
        event = payload.get("event", {})
        event_type = event.get("type")

        if event_type == "message":
            # 忽略 bot 自己的消息
            if event.get("user") == self._bot_user_id:
                return

            # 忽略子类型消息（如编辑、删除）
            if event.get("subtype"):
                return

            message = self._convert_message_event(event)
            if message:
                await self._handle_inbound_message(message)

        elif event_type == "app_mention":
            # 被提及
            message = self._convert_message_event(event)
            if message:
                await self._handle_inbound_message(message)

    async def _handle_slash_command(self, payload: dict) -> None:
        """处理斜杠命令"""
        command = payload.get("command", "")
        text = payload.get("text", "")
        user_id = payload.get("user_id", "")
        channel_id = payload.get("channel_id", "")

        logger.debug(f"[{self.name}] Slash command: {command} {text}")

        # 转换为消息格式
        message = InboundMessage(
            channel=self.channel_type,
            sender_id=user_id,
            chat_id=channel_id,
            chat_type="channel" if channel_id.startswith("C") else "private",
            content=f"{command} {text}".strip(),
            message_type=MessageType.TEXT,
            metadata={
                "command": command,
                "is_slash_command": True,
                "response_url": payload.get("response_url"),
            },
        )

        await self._handle_inbound_message(message)

    def _convert_message_event(self, event: dict) -> Optional[InboundMessage]:
        """转换 Slack 事件为内部格式"""
        text = event.get("text", "")

        # 移除 @bot 提及
        if self._bot_user_id:
            mention = f"<@{self._bot_user_id}>"
            text = text.replace(mention, "").strip()

        # 确定聊天类型
        channel = event.get("channel", "")
        chat_type = "private"
        if channel.startswith("C"):
            chat_type = "channel"
        elif channel.startswith("G"):
            chat_type = "group"

        # 提取文件
        media = []
        files = event.get("files", [])
        for f in files:
            media.append(MediaAttachment(
                url=f.get("url_private"),
                file_name=f.get("name"),
                mime_type=f.get("mimetype"),
                file_size=f.get("size"),
            ))

        # 提取提及
        mentions_set = set(re.findall(r"<@([A-Z0-9]+)>", text or ""))

        def _walk_blocks(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("type") == "user" and node.get("user_id"):
                    mentions_set.add(node.get("user_id"))
                for value in node.values():
                    _walk_blocks(value)
            elif isinstance(node, list):
                for item in node:
                    _walk_blocks(item)

        _walk_blocks(event.get("blocks", []))
        mentions = [m for m in mentions_set if m]

        return InboundMessage(
            channel=self.channel_type,
            sender_id=event.get("user", ""),
            chat_id=channel,
            chat_type=chat_type,
            message_id=event.get("ts", ""),
            content=text,
            message_type=MessageType.IMAGE if media else MessageType.TEXT,
            media=media,
            reply_to=event.get("thread_ts"),
            mentions=mentions,
            metadata={
                "team": event.get("team"),
                "channel_type": event.get("channel_type"),
                "event_time": event.get("event_ts"),
            },
        )

    # ============== HTTP Webhook 处理器（供外部服务器调用） ==============

    async def handle_webhook(self, body: bytes, headers: dict) -> bool:
        """
        处理 HTTP Webhook 请求

        Returns:
            是否成功处理
        """
        if self.config.socket_mode:
            return False

        # 验证签名
        if not self._verify_signature(body, headers.get("X-Slack-Signature", ""), headers.get("X-Slack-Request-Timestamp", "")):
            logger.warning(f"[{self.name}] Invalid webhook signature")
            return False

        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            logger.error(f"[{self.name}] Invalid JSON in webhook body")
            return False

        # 处理 URL 验证挑战
        if payload.get("type") == "url_verification":
            return True  # 返回 challenge

        # 处理事件回调
        if payload.get("type") == "event_callback":
            await self._handle_event(payload)
            return True

        return False

    def _verify_signature(self, body: bytes, signature: str, timestamp: str) -> bool:
        """验证 Slack 签名"""
        import hmac
        import hashlib
        import time

        if not self.config.signing_secret or not signature or not timestamp:
            return False

        try:
            ts = int(timestamp)
        except (TypeError, ValueError):
            return False

        # 防止重放攻击（默认 5 分钟窗口）
        if abs(time.time() - ts) > 60 * 5:
            return False

        basestring = f"v0:{timestamp}:".encode() + body
        my_signature = "v0=" + hmac.new(
            self.config.signing_secret.encode(),
            basestring,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(my_signature, signature)

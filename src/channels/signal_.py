"""Signal Channel 实现

通过 HTTP REST API 连接到 signal-cli daemon，使用 SSE 接收消息。
参考 openclaw 的 signal 实现。
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, AsyncGenerator, Optional

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None

from .base import BaseChannel
from .events import InboundMessage, MediaAttachment, MessageType, OutboundMessage

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .config import SignalConfig


class SignalChannel(BaseChannel):
    """Signal 消息通道

    通过 HTTP REST API 连接到 signal-cli。
    signal-cli 项目: https://github.com/AsamK/signal-cli
    """

    def __init__(self, config: "SignalConfig"):
        if not HTTPX_AVAILABLE:
            raise ImportError(
                "Signal support requires 'httpx'. "
                "Install with: pip install 'virtual-human-sdk[signal]'"
            )
        super().__init__(config)
        self.config: "SignalConfig" = config
        self._client: Optional[httpx.AsyncClient] = None
        self._receive_task: Optional[asyncio.Task] = None

    @property
    def channel_type(self) -> str:
        return "signal"

    async def _start(self) -> None:
        """启动 Signal 连接"""
        self._client = httpx.AsyncClient(
            base_url=self.config.api_url,
            timeout=30.0,
        )

        # 验证连接
        try:
            response = await self._client.get("/v1/about")
            response.raise_for_status()
            info = response.json()
            logger.info(f"[{self.name}] Connected to signal-cli: {info.get('version', 'unknown')}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to signal-cli: {e}")

        # 启动接收任务
        if self.config.auto_receive:
            self._receive_task = asyncio.create_task(self._receive_loop())

    async def _stop(self) -> None:
        """停止 Signal 连接"""
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._client:
            await self._client.aclose()
            self._client = None

    async def _send_message(self, message: OutboundMessage) -> Optional[Any]:
        """发送消息到 Signal"""
        if not self._client:
            return None

        # 构建请求
        url = f"/v2/send"
        payload = {
            "account": self.config.phone_number,
            "recipients": [message.chat_id],
            "message": message.content,
        }

        # 处理附件
        if message.media_paths:
            # Signal 需要 base64 编码的附件
            import base64

            attachments = []
            for path in message.media_paths:
                with open(path, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                attachments.append({
                    "filename": path.split("/")[-1],
                    "data": data,
                })
            payload["attachments"] = attachments

        try:
            response = await self._client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"[{self.name}] Failed to send message: {e}")
            raise

    async def _receive_loop(self) -> None:
        """接收消息循环（SSE）"""
        while not self._stop_event.is_set():
            try:
                async for event in self._listen_sse():
                    if self._stop_event.is_set():
                        break

                    try:
                        data = json.loads(event)
                        await self._handle_event(data)
                    except json.JSONDecodeError:
                        logger.warning(f"[{self.name}] Invalid JSON in SSE: {event[:200]}")
                    except Exception as e:
                        logger.error(f"[{self.name}] Error handling event: {e}")

            except Exception as e:
                logger.error(f"[{self.name}] SSE connection error: {e}")

            if not self._stop_event.is_set():
                await asyncio.sleep(self.config.receive_interval)

    async def _listen_sse(self) -> AsyncGenerator[str, None]:
        """监听 SSE 流"""
        if not self._client:
            return

        # signal-cli 的接收端点
        url = f"/v1/receive/{self.config.phone_number}"

        try:
            async with self._client.stream("GET", url, timeout=None) as response:
                response.raise_for_status()

                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk

                    # 处理 SSE 格式
                    while "\n\n" in buffer:
                        event, buffer = buffer.split("\n\n", 1)
                        data_line = None

                        for line in event.split("\n"):
                            if line.startswith("data: "):
                                data_line = line[6:]
                                break

                        if data_line:
                            yield data_line

        except httpx.HTTPError as e:
            logger.error(f"[{self.name}] SSE request failed: {e}")
            raise

    async def _handle_event(self, data: dict) -> None:
        """处理 Signal 事件"""
        envelope = data.get("envelope", {})

        # 忽略自己发送的消息
        if envelope.get("source") == self.config.phone_number:
            return

        # 处理数据消息
        if "dataMessage" in envelope:
            message = self._convert_data_message(envelope)
            if message:
                await self._handle_inbound_message(message)

        # 处理同步消息
        elif "syncMessage" in envelope:
            pass  # 忽略同步消息

    def _convert_data_message(self, envelope: dict) -> Optional[InboundMessage]:
        """转换 Signal 数据消息为内部格式"""
        data_msg = envelope.get("dataMessage", {})

        # 提取内容
        content = data_msg.get("message", "")
        msg_type = MessageType.TEXT
        media = []

        # 处理附件
        attachments = data_msg.get("attachments", [])
        for att in attachments:
            content_type = att.get("contentType", "")
            att_type = MessageType.DOCUMENT

            if content_type.startswith("image/"):
                att_type = MessageType.IMAGE
            elif content_type.startswith("video/"):
                att_type = MessageType.VIDEO
            elif content_type.startswith("audio/"):
                att_type = MessageType.AUDIO

            media.append(MediaAttachment(
                file_name=att.get("filename"),
                mime_type=content_type,
                file_size=att.get("size"),
            ))

            if att_type != MessageType.DOCUMENT:
                msg_type = att_type

        # 确定聊天类型
        chat_type = "private"
        group_info = data_msg.get("groupInfo")
        if group_info:
            chat_type = "group"

        # 提取引用（回复）
        quote = data_msg.get("quote", {})
        reply_to = quote.get("id") if quote else None

        # 提取提及
        mentions = []
        for mention in data_msg.get("mentions", []):
            mentions.append(mention.get("number", ""))

        # 构建聊天 ID
        if group_info:
            chat_id = group_info.get("groupId", "")
        else:
            chat_id = envelope.get("source", "")

        return InboundMessage(
            channel=self.channel_type,
            sender_id=envelope.get("source", ""),
            chat_id=chat_id,
            chat_type=chat_type,
            message_id=str(data_msg.get("timestamp", "")),
            content=content,
            message_type=msg_type,
            media=media,
            reply_to=str(reply_to) if reply_to else None,
            mentions=mentions,
            metadata={
                "source_device": envelope.get("sourceDevice"),
                "timestamp": data_msg.get("timestamp"),
                "expires_in_seconds": data_msg.get("expiresInSeconds"),
                "view_once": data_msg.get("viewOnce", False),
            },
        )

    async def get_groups(self) -> list:
        """获取群组列表"""
        if not self._client:
            return []

        try:
            response = await self._client.get(f"/v1/groups/{self.config.phone_number}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"[{self.name}] Failed to get groups: {e}")
            return []

    async def get_contacts(self) -> list:
        """获取联系人列表"""
        if not self._client:
            return []

        try:
            response = await self._client.get(f"/v1/contacts/{self.config.phone_number}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"[{self.name}] Failed to get contacts: {e}")
            return []

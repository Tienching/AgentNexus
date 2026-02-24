"""WhatsApp Channel 实现

通过 WebSocket 连接到 Node.js Bridge（基于 Baileys 库）。
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Optional

from .base import BaseChannel
from .events import InboundMessage, MediaAttachment, MessageType, OutboundMessage

logger = logging.getLogger(__name__)

# 延迟导入 websockets
try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

if TYPE_CHECKING:
    from .config import WhatsAppConfig


class WhatsAppChannel(BaseChannel):
    """WhatsApp 消息通道

    通过 WebSocket 连接到 Node.js Bridge。
    Bridge 项目: https://github.com/WhiskeySockets/Baileys
    """

    def __init__(self, config: "WhatsAppConfig"):
        super().__init__(config)
        self.config: "WhatsAppConfig" = config
        self._ws: Optional[Any] = None
        self._reconnect_attempts = 0
        self._receive_task: Optional[asyncio.Task] = None

    @property
    def channel_type(self) -> str:
        return "whatsapp"

    async def _start(self) -> None:
        """启动 WhatsApp 连接"""
        if not WEBSOCKETS_AVAILABLE:
            raise ImportError(
                "WhatsApp support requires 'websockets'. "
                "Install with: pip install websockets"
            )

        self._reconnect_attempts = 0
        await self._connect()

    async def _connect(self) -> None:
        """建立 WebSocket 连接"""
        import websockets

        headers = {}
        if self.config.bridge_auth_token:
            headers["Authorization"] = f"Bearer {self.config.bridge_auth_token}"

        try:
            self._ws = await websockets.connect(
                self.config.bridge_url,
                extra_headers=headers,
            )
            logger.info(f"[{self.name}] Connected to WhatsApp Bridge")

            # 发送初始化消息
            await self._ws.send(json.dumps({
                "action": "init",
                "session": self.config.session_name,
            }))

            # 启动接收任务
            self._receive_task = asyncio.create_task(self._receive_loop())

            self._reconnect_attempts = 0

        except Exception as e:
            logger.error(f"[{self.name}] Connection failed: {e}")
            await self._handle_reconnect()

    async def _stop(self) -> None:
        """停止 WhatsApp 连接"""
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _send_message(self, message: OutboundMessage) -> Optional[Any]:
        """发送消息到 WhatsApp"""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")

        # 构建消息
        payload = {
            "action": "send",
            "to": message.chat_id,
            "text": message.content,
        }

        # 处理媒体
        if message.media_paths:
            # 发送媒体文件
            import base64
            import os

            path = message.media_paths[0]
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode()

            ext = os.path.splitext(path)[1].lower()
            media_type = "document"
            if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                media_type = "image"
            elif ext in (".mp4", ".mov", ".avi"):
                media_type = "video"
            elif ext in (".mp3", ".ogg", ".wav"):
                media_type = "audio"

            payload = {
                "action": "sendMedia",
                "to": message.chat_id,
                "type": media_type,
                "data": data,
                "filename": os.path.basename(path),
                "caption": message.content,
            }

        await self._ws.send(json.dumps(payload))

        # 等待确认（简化处理）
        return {"sent": True}

    async def _receive_loop(self) -> None:
        """接收消息循环"""
        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"[{self.name}] Invalid JSON received: {message[:200]}")
                except Exception as e:
                    logger.error(f"[{self.name}] Error handling message: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.warning(f"[{self.name}] WebSocket connection closed")
            if not self._stop_event.is_set():
                await self._handle_reconnect()

        except asyncio.CancelledError:
            raise

        except Exception as e:
            logger.error(f"[{self.name}] Receive loop error: {e}")
            if not self._stop_event.is_set():
                await self._handle_reconnect()

    async def _handle_message(self, data: dict) -> None:
        """处理收到的消息"""
        msg_type = data.get("type")

        if msg_type == "message":
            message = self._convert_message(data)
            if message:
                await self._handle_inbound_message(message)

        elif msg_type == "connection":
            status = data.get("status")
            logger.info(f"[{self.name}] Connection status: {status}")

        elif msg_type == "qr":
            # 需要扫描二维码登录
            qr_code = data.get("qr")
            logger.info(f"[{self.name}] QR Code received (scan to login)")
            # 可以在这里触发事件通知用户

        elif msg_type == "error":
            error_msg = data.get("error", "Unknown error")
            logger.error(f"[{self.name}] Bridge error: {error_msg}")

    async def _handle_reconnect(self) -> None:
        """处理重连"""
        if not self.config.auto_reconnect:
            return

        self._reconnect_attempts += 1
        if self._reconnect_attempts > self.config.max_reconnect_attempts:
            logger.error(f"[{self.name}] Max reconnect attempts reached")
            await self._handle_error(RuntimeError("Max reconnect attempts reached"))
            return

        delay = self.config.reconnect_interval * self._reconnect_attempts
        logger.info(f"[{self.name}] Reconnecting in {delay}s (attempt {self._reconnect_attempts})")

        await asyncio.sleep(delay)

        if not self._stop_event.is_set():
            await self._connect()

    def _convert_message(self, data: dict) -> Optional[InboundMessage]:
        """转换 WhatsApp 消息为内部格式"""
        message_data = data.get("message", {})
        key = message_data.get("key", {})
        message = message_data.get("message", {})

        # 忽略自己发送的消息
        if key.get("fromMe"):
            return None

        remote_jid = key.get("remoteJid", "")
        sender = key.get("participant") or remote_jid

        # 提取文本内容
        content = ""
        msg_type = MessageType.TEXT
        media = []

        if "conversation" in message:
            content = message["conversation"]
        elif "extendedTextMessage" in message:
            content = message["extendedTextMessage"].get("text", "")
        elif "imageMessage" in message:
            img = message["imageMessage"]
            content = img.get("caption", "")
            msg_type = MessageType.IMAGE
            media.append(MediaAttachment(
                url=img.get("url"),
                mime_type=img.get("mimetype"),
                file_name=img.get("fileName"),
            ))
        elif "videoMessage" in message:
            vid = message["videoMessage"]
            content = vid.get("caption", "")
            msg_type = MessageType.VIDEO
            media.append(MediaAttachment(
                mime_type=vid.get("mimetype"),
                duration=vid.get("seconds"),
            ))
        elif "audioMessage" in message:
            aud = message["audioMessage"]
            msg_type = MessageType.VOICE if aud.get("ptt") else MessageType.AUDIO
            media.append(MediaAttachment(
                mime_type=aud.get("mimetype"),
                duration=aud.get("seconds"),
            ))
        elif "documentMessage" in message:
            doc = message["documentMessage"]
            msg_type = MessageType.DOCUMENT
            media.append(MediaAttachment(
                file_name=doc.get("fileName"),
                mime_type=doc.get("mimetype"),
                file_size=doc.get("fileLength"),
            ))

        # 确定聊天类型
        chat_type = "private"
        if "@g.us" in remote_jid:
            chat_type = "group"
        elif "@broadcast" in remote_jid:
            chat_type = "broadcast"

        return InboundMessage(
            channel=self.channel_type,
            sender_id=sender.split("@")[0] if "@" in sender else sender,
            chat_id=remote_jid.split("@")[0] if "@" in remote_jid else remote_jid,
            chat_type=chat_type,
            message_id=key.get("id", ""),
            content=content,
            message_type=msg_type,
            media=media,
            reply_to=message.get("extendedTextMessage", {}).get("contextInfo", {}).get("stanzaId"),
            metadata={
                "remote_jid": remote_jid,
                "message_timestamp": message_data.get("messageTimestamp"),
                "push_name": message_data.get("pushName"),
            },
        )

"""飞书 (Feishu/Lark) Channel 实现

基于飞书 Open API，支持 Webhook 接收消息和 HTTP API 发送消息。
参考 openclaw 的 feishu 实现。

飞书 Bot 通过事件订阅（HTTP 回调）接收消息，通过 REST API 发送消息。
支持私聊和群聊，支持文本和富文本消息。
"""

import asyncio
import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from .base import BaseChannel
from .events import InboundMessage, MediaAttachment, MessageType, OutboundMessage

logger = logging.getLogger(__name__)

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None

if TYPE_CHECKING:
    from .config import FeishuConfig

# Feishu API base URLs
FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
LARK_API_BASE = "https://open.larksuite.com/open-apis"

# Message length limit for feishu text messages
FEISHU_MAX_LENGTH = 4000


class FeishuChannel(BaseChannel):
    """飞书消息通道

    使用 Webhook 接收消息，通过 REST API 发送消息。
    需要在飞书开放平台创建应用并配置事件订阅。
    """

    def __init__(self, config: "FeishuConfig"):
        if not HTTPX_AVAILABLE:
            raise ImportError(
                "Feishu support requires 'httpx'. "
                "Install with: pip install httpx"
            )
        super().__init__(config)
        self.config: "FeishuConfig" = config
        self._http_client: Optional[Any] = None
        self._tenant_access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._api_base: str = (
            LARK_API_BASE if config.domain == "lark" else FEISHU_API_BASE
        )

    @property
    def channel_type(self) -> str:
        return "feishu"

    async def _start(self) -> None:
        """启动飞书通道 — 初始化 HTTP 客户端并获取 token"""
        self._http_client = httpx.AsyncClient(timeout=30.0)
        # Pre-fetch the tenant access token
        await self._refresh_token()
        logger.info(
            f"[{self.name}] Feishu channel started "
            f"(domain={self.config.domain}, app_id={self.config.app_id[:8]}...)"
        )

    async def _stop(self) -> None:
        """停止飞书通道"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._tenant_access_token = None
        self._token_expires_at = 0

    # ============== Token 管理 ==============

    async def _refresh_token(self) -> None:
        """获取 / 刷新 tenant_access_token"""
        if not self._http_client:
            return

        url = f"{self._api_base}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.config.app_id,
            "app_secret": self.config.app_secret,
        }
        try:
            resp = await self._http_client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 0:
                self._tenant_access_token = data["tenant_access_token"]
                # Expire 5 minutes early to be safe
                expire = data.get("expire", 7200)
                self._token_expires_at = time.time() + expire - 300
                logger.debug(f"[{self.name}] Token refreshed, expires in {expire}s")
            else:
                logger.error(f"[{self.name}] Failed to get token: {data}")
        except Exception as e:
            logger.error(f"[{self.name}] Token refresh error: {e}")

    async def _get_token(self) -> Optional[str]:
        """获取有效的 tenant_access_token，必要时自动刷新"""
        if not self._tenant_access_token or time.time() >= self._token_expires_at:
            await self._refresh_token()
        return self._tenant_access_token

    async def _get_headers(self) -> Dict[str, str]:
        """获取带认证的 HTTP 请求头"""
        token = await self._get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    # ============== 消息发送 ==============

    async def _send_message(self, message: OutboundMessage) -> Optional[Any]:
        """发送消息到飞书"""
        if not self._http_client:
            return None

        headers = await self._get_headers()

        # 确定接收者类型和 ID
        receive_id_type = self._detect_id_type(message.chat_id)
        receive_id = message.chat_id

        # 构建消息内容
        content = message.content or ""

        # 处理回复
        if message.reply_to:
            url = f"{self._api_base}/im/v1/messages/{message.reply_to}/reply"
            body = {
                "msg_type": "text",
                "content": json.dumps({"text": content}),
            }
        else:
            url = f"{self._api_base}/im/v1/messages"
            body = {
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": content}),
            }

        params = {"receive_id_type": receive_id_type} if not message.reply_to else {}

        try:
            resp = await self._http_client.post(
                url, json=body, headers=headers, params=params
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("message_id")
            else:
                logger.error(
                    f"[{self.name}] Send message failed: code={data.get('code')}, "
                    f"msg={data.get('msg')}"
                )
                return None
        except Exception as e:
            logger.error(f"[{self.name}] Failed to send message: {e}")
            return None

    async def send_typing(self, chat_id: str) -> None:
        """发送输入中指示

        飞书没有原生的 typing 指示 API，这里不做任何操作。
        """
        pass

    # ============== Webhook 事件处理 ==============

    async def handle_webhook(self, body: bytes, headers: Dict[str, str]) -> bool:
        """处理飞书 Webhook 事件回调

        Args:
            body: 原始请求体
            headers: 请求头

        Returns:
            是否成功处理
        """
        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning(f"[{self.name}] Invalid webhook payload")
            return False

        # 处理 URL 验证 challenge
        if payload.get("type") == "url_verification":
            return True  # Router 层处理 challenge 返回

        # 处理加密事件
        if "encrypt" in payload:
            payload = self._decrypt_event(payload)
            if not payload:
                return False

        # 验证签名（如果配置了 verification_token）
        if self.config.verification_token:
            token = payload.get("token", "")
            if token != self.config.verification_token:
                logger.warning(f"[{self.name}] Invalid verification token")
                return False

        # 处理事件 v2.0 格式
        schema = payload.get("schema")
        if schema == "2.0":
            return await self._handle_event_v2(payload)

        # 处理事件 v1.0 格式
        event = payload.get("event")
        if event:
            return await self._handle_event_v1(payload)

        logger.debug(f"[{self.name}] Unrecognized event format")
        return False

    async def _handle_event_v2(self, payload: dict) -> bool:
        """处理 v2.0 格式事件"""
        header = payload.get("header", {})
        event_type = header.get("event_type", "")
        event = payload.get("event", {})

        if event_type == "im.message.receive_v1":
            return await self._handle_message_event(event)

        logger.debug(f"[{self.name}] Unhandled event type: {event_type}")
        return True

    async def _handle_event_v1(self, payload: dict) -> bool:
        """处理 v1.0 格式事件"""
        event = payload.get("event", {})
        event_type = event.get("type", "")

        if event_type == "message":
            return await self._handle_message_event_v1(event)

        logger.debug(f"[{self.name}] Unhandled v1 event type: {event_type}")
        return True

    async def _handle_message_event(self, event: dict) -> bool:
        """处理 v2.0 消息事件"""
        message = event.get("message", {})
        sender = event.get("sender", {})

        # 忽略 bot 自己的消息
        sender_type = sender.get("sender_type", "")
        if sender_type == "app":
            return True

        msg_type = message.get("message_type", "text")
        chat_id = message.get("chat_id", "")
        message_id = message.get("message_id", "")
        chat_type = message.get("chat_type", "p2p")  # p2p / group

        # 解析发送者
        sender_id_obj = sender.get("sender_id", {})
        sender_open_id = sender_id_obj.get("open_id", "")

        # 解析消息内容
        content_str = message.get("content", "{}")
        try:
            content_data = json.loads(content_str)
        except json.JSONDecodeError:
            content_data = {}

        text_content = ""
        media_list = []
        inbound_msg_type = MessageType.TEXT

        if msg_type == "text":
            text_content = content_data.get("text", "")
        elif msg_type == "post":
            # 富文本消息，提取纯文本
            text_content = self._extract_post_text(content_data)
        elif msg_type == "image":
            inbound_msg_type = MessageType.IMAGE
            image_key = content_data.get("image_key", "")
            if image_key:
                media_list.append(MediaAttachment(
                    file_id=image_key,
                    mime_type="image/png",
                ))
        elif msg_type == "file":
            inbound_msg_type = MessageType.DOCUMENT
            file_key = content_data.get("file_key", "")
            file_name = content_data.get("file_name", "")
            if file_key:
                media_list.append(MediaAttachment(
                    file_id=file_key,
                    file_name=file_name,
                ))
        elif msg_type == "audio":
            inbound_msg_type = MessageType.AUDIO
            file_key = content_data.get("file_key", "")
            if file_key:
                media_list.append(MediaAttachment(
                    file_id=file_key,
                    mime_type="audio/opus",
                ))
        else:
            # 其他类型（合并转发、分享等）转为文本
            text_content = f"[{msg_type} message]"

        # 提取提及
        mentions = []
        for mention in message.get("mentions", []):
            mention_id = mention.get("id", {})
            if isinstance(mention_id, dict):
                mentions.append(mention_id.get("open_id", ""))
            else:
                mentions.append(str(mention_id))

        # 移除 @bot 的文本 (格式: @_user_1)
        if mentions and text_content:
            import re
            text_content = re.sub(r'@_user_\d+', '', text_content).strip()

        # 获取引用消息
        parent_id = message.get("parent_id") or message.get("root_id")
        reply_to = parent_id if parent_id else None

        # 构建入站消息
        inbound = InboundMessage(
            channel="feishu",
            sender_id=sender_open_id,
            sender_name="",  # 需要额外 API 调用获取
            chat_id=chat_id,
            chat_type="private" if chat_type == "p2p" else "group",
            message_id=message_id,
            content=text_content,
            message_type=inbound_msg_type,
            media=media_list,
            reply_to=reply_to,
            mentions=mentions,
            metadata={
                "chat_type": chat_type,
                "sender_type": sender_type,
                "sender_open_id": sender_open_id,
                "msg_type": msg_type,
            },
        )

        await self._handle_inbound_message(inbound)
        return True

    async def _handle_message_event_v1(self, event: dict) -> bool:
        """处理 v1.0 消息事件"""
        msg_type = event.get("msg_type", "text")
        open_id = event.get("open_id", "")
        chat_type = "group" if event.get("open_chat_id") else "private"
        chat_id = event.get("open_chat_id") or open_id
        text_content = event.get("text_without_at_bot") or event.get("text", "")

        inbound = InboundMessage(
            channel="feishu",
            sender_id=open_id,
            sender_name="",
            chat_id=chat_id,
            chat_type=chat_type,
            message_id=event.get("open_message_id", ""),
            content=text_content,
            message_type=MessageType.TEXT,
            metadata={
                "msg_type": msg_type,
                "open_id": open_id,
            },
        )

        await self._handle_inbound_message(inbound)
        return True

    # ============== 消息编辑 ==============

    async def edit_message(self, message_id: str, content: str) -> bool:
        """编辑已发送的消息

        飞书支持在 24 小时内编辑 bot 发送的消息。

        Args:
            message_id: 飞书消息 ID
            content: 新的文本内容

        Returns:
            是否编辑成功
        """
        if not self._http_client:
            return False

        headers = await self._get_headers()
        url = f"{self._api_base}/im/v1/messages/{message_id}"
        body = {
            "msg_type": "text",
            "content": json.dumps({"text": content}),
        }

        try:
            resp = await self._http_client.patch(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("code") == 0
        except Exception as e:
            logger.error(f"[{self.name}] Failed to edit message: {e}")
            return False

    # ============== 辅助方法 ==============

    def _detect_id_type(self, id_str: str) -> str:
        """检测飞书 ID 类型"""
        if id_str.startswith("oc_"):
            return "chat_id"
        elif id_str.startswith("ou_"):
            return "open_id"
        elif id_str.startswith("on_"):
            return "union_id"
        elif id_str.startswith("cli_"):
            return "app_id"
        else:
            # 默认当作 open_id
            return "open_id"

    def _extract_post_text(self, content: dict) -> str:
        """从富文本(post)消息中提取纯文本"""
        parts = []

        # post 格式: {"title": "...", "content": [[{tag, text, ...}, ...]]}
        title = content.get("title", "")
        if title:
            parts.append(title)

        post_content = content.get("content", [])
        for line in post_content:
            line_parts = []
            for element in line:
                tag = element.get("tag", "")
                if tag == "text":
                    line_parts.append(element.get("text", ""))
                elif tag == "a":
                    text = element.get("text", "")
                    href = element.get("href", "")
                    line_parts.append(f"{text}({href})" if href else text)
                elif tag == "at":
                    line_parts.append(f"@{element.get('user_name', 'user')}")
                elif tag == "img":
                    line_parts.append("[image]")
            parts.append("".join(line_parts))

        return "\n".join(parts)

    def _decrypt_event(self, payload: dict) -> Optional[dict]:
        """解密加密的事件（需要 encrypt_key）"""
        if not self.config.encrypt_key:
            logger.warning(f"[{self.name}] Received encrypted event but no encrypt_key configured")
            return None

        try:
            from base64 import b64decode
            from hashlib import sha256
            import struct

            encrypt = payload["encrypt"]
            key = sha256(self.config.encrypt_key.encode("utf-8")).digest()

            # AES-256-CBC 解密
            try:
                from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
                from cryptography.hazmat.primitives import padding as aes_padding

                encrypted_data = b64decode(encrypt)
                iv = encrypted_data[:16]
                cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
                decryptor = cipher.decryptor()
                decrypted = decryptor.update(encrypted_data[16:]) + decryptor.finalize()

                # Remove PKCS7 padding
                unpadder = aes_padding.PKCS7(128).unpadder()
                decrypted = unpadder.update(decrypted) + unpadder.finalize()

                return json.loads(decrypted.decode("utf-8"))
            except ImportError:
                logger.error(
                    f"[{self.name}] 'cryptography' package required for encrypted events. "
                    "Install with: pip install cryptography"
                )
                return None
        except Exception as e:
            logger.error(f"[{self.name}] Failed to decrypt event: {e}")
            return None

    def get_challenge_response(self, payload: dict) -> Optional[dict]:
        """处理 URL 验证 challenge，返回响应体

        Args:
            payload: 原始 webhook payload

        Returns:
            Challenge 响应字典或 None
        """
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}

        # v2.0 加密 challenge
        if "encrypt" in payload and self.config.encrypt_key:
            decrypted = self._decrypt_event(payload)
            if decrypted and decrypted.get("type") == "url_verification":
                return {"challenge": decrypted.get("challenge", "")}

        return None

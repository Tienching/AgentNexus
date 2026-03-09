"""企业微信智能机器人 (WeCom AI Bot) Channel 实现

基于企业微信智能机器人 API 模式，通过 Webhook 回调接收消息，
支持被动回复（加密 JSON）和主动回复（response_url）两种方式。

参考文档：
- 概述: https://developer.work.weixin.qq.com/document/path/101039
- 接收消息: https://developer.work.weixin.qq.com/document/path/100719
- 接收事件: https://developer.work.weixin.qq.com/document/path/101148
- 被动回复: https://developer.work.weixin.qq.com/document/path/101031
- 主动回复: https://developer.work.weixin.qq.com/document/path/101138
- 加解密方案: https://developer.work.weixin.qq.com/document/path/101033
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import socket
import struct
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import unquote

from .base import BaseChannel
from .events import InboundMessage, MediaAttachment, MessageType, OutboundMessage

logger = logging.getLogger(__name__)


def sanitize_wecom_markdown_content(content: str) -> str:
    """Neutralize markdown syntax that WeCom renders with red-highlighted styles."""
    text = str(content or "")
    if not text:
        return text

    text = text.replace("```", "")
    text = text.replace("`", "")
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Maximum stream duration before falling back to response_url (seconds)
STREAM_MAX_DURATION = 360  # 6 minutes


@dataclass
class StreamBuffer:
    """流式回复缓冲区（全量模式）

    企微流式回复的 content 是全量内容（每次替换），不是增量追加。
    例如：第一次返回 "1"，第二次返回 "123"，客户端显示 "123"。

    所以 full_content 始终保存完整的累积文本，
    每次刷新回调直接返回 full_content 即可。
    """

    stream_id: str
    chat_id: str
    # 完整的累积内容（每次刷新回调都返回这个）
    full_content: str = ""
    # 上次刷新回调时的内容长度（用于判断是否有新内容）
    _last_sent_len: int = 0
    # AI 是否已完成处理
    finished: bool = False
    # 创建时间
    created_at: float = field(default_factory=time.time)
    # 用于同步的事件：当有新内容或完成时通知
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    # 关联的 response_url（超时兜底用）
    response_url: str = ""

    def append(self, text: str) -> None:
        """追加增量内容（由 AI 处理协程调用）"""
        if text:
            self.full_content += text
            self._event.set()

    def set_final(self, text: str) -> None:
        """设置最终完整内容（替换之前的流式增量）"""
        self.full_content = text
        self._event.set()

    def mark_finished(self) -> None:
        """标记 AI 处理完成"""
        self.finished = True
        self._event.set()

    def get_content(self) -> str:
        """获取当前全量内容（由流式刷新回调调用）

        企微流式回复需要全量内容，每次覆盖显示。
        """
        content = self.full_content
        self._last_sent_len = len(content)
        self._event.clear()
        return content

    @property
    def has_new_content(self) -> bool:
        """是否有新内容（相比上次 get_content）"""
        return len(self.full_content) > self._last_sent_len

    async def wait_for_content(self, timeout: float = 4.0) -> bool:
        """等待新内容或完成信号，最多等 timeout 秒

        Returns True if there is content or finished, False on timeout.
        """
        if self.has_new_content or self.finished:
            return True
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    @property
    def is_expired(self) -> bool:
        """流是否已超过最大持续时间"""
        return (time.time() - self.created_at) > STREAM_MAX_DURATION

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None

try:
    import websockets

    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    websockets = None

try:
    import fcntl

    FCNTL_AVAILABLE = True
except ImportError:
    FCNTL_AVAILABLE = False
    fcntl = None

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

if TYPE_CHECKING:
    from .config import WeComConfig

# WeCom AI Bot message length limit (bytes, UTF-8)
WECOM_MAX_LENGTH = 20480


class WeComCrypto:
    """企业微信消息加解密工具

    实现企业微信智能机器人回调的加解密方案：
    - AES-256-CBC 加密/解密，PKCS#7 填充到 32 字节
    - SHA1 签名验证

    参考: https://developer.work.weixin.qq.com/document/path/101033
    """

    def __init__(self, token: str, encoding_aes_key: str):
        self.token = token
        self.aes_key = base64.b64decode(encoding_aes_key + "=")
        self.iv = self.aes_key[:16]

    @staticmethod
    def _require_crypto() -> None:
        if not CRYPTO_AVAILABLE:
            raise ImportError(
                "WeCom encryption requires 'cryptography'. "
                "Install with: pip install cryptography"
            )

    @staticmethod
    def _strip_pkcs7(data: bytes) -> bytes:
        """去除 PKCS#7 填充（block_size=32）。"""
        pad_len = data[-1]
        return data[:-pad_len] if isinstance(pad_len, int) else data[:-ord(pad_len)]

    def verify_signature(
        self, msg_signature: str, timestamp: str, nonce: str, encrypt: str
    ) -> bool:
        """验证消息签名: SHA1(Sort(Token, Timestamp, Nonce, Encrypt))"""
        return self._generate_signature(timestamp, nonce, encrypt) == msg_signature

    def _generate_signature(self, timestamp: str, nonce: str, encrypt: str) -> str:
        sort_list = sorted([self.token, timestamp, nonce, encrypt])
        return hashlib.sha1("".join(sort_list).encode("utf-8")).hexdigest()

    def _aes_decrypt(self, encrypted_data: bytes) -> bytes:
        """AES-256-CBC 解密并去除 PKCS#7 填充。"""
        self._require_crypto()
        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(self.iv))
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(encrypted_data) + decryptor.finalize()
        return self._strip_pkcs7(decrypted)

    def decrypt(self, encrypt: str) -> str:
        """解密消息。

        解密后格式: random(16B) + msg_len(4B, network order) + msg + receiveid
        """
        decrypted = self._aes_decrypt(base64.b64decode(encrypt))
        msg_len = socket.ntohl(struct.unpack("I", decrypted[16:20])[0])
        return decrypted[20 : 20 + msg_len].decode("utf-8")

    def decrypt_file(self, encrypted_data: bytes) -> bytes:
        """解密文件附件。

        与 decrypt 不同，文件加密没有 random+msg_len+msg+receiveid 包装格式。
        """
        return self._aes_decrypt(encrypted_data)

    def encrypt(self, reply_msg: str) -> str:
        """加密回复消息。

        加密前格式: random(16B) + msg_len(4B, network order) + msg + receiveid("")
        """
        self._require_crypto()

        msg_bytes = reply_msg.encode("utf-8")
        # random(16) + msg_len(4) + msg + receiveid("")
        random_bytes = uuid.uuid4().bytes
        msg_len = struct.pack("I", socket.htonl(len(msg_bytes)))
        plaintext = random_bytes + msg_len + msg_bytes

        # PKCS#7 padding to block size 32
        block_size = 32
        pad_amount = block_size - (len(plaintext) % block_size)
        if pad_amount == 0:
            pad_amount = block_size
        plaintext += bytes([pad_amount] * pad_amount)

        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(self.iv))
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(plaintext) + encryptor.finalize()

        return base64.b64encode(encrypted).decode("utf-8")

    def encrypt_reply(self, reply_msg: str, nonce: str) -> Dict[str, Any]:
        """加密并签名回复消息，返回完整的响应 JSON

        Args:
            reply_msg: 明文 JSON 字符串
            nonce: 回调请求中的 nonce（文档要求被动回复时必须使用回调 URL 中的 nonce）

        Returns:
            加密的响应字典，包含 encrypt, msgsignature, timestamp, nonce
        """
        encrypt = self.encrypt(reply_msg)
        timestamp = str(int(time.time()))
        signature = self._generate_signature(timestamp, nonce, encrypt)
        return {
            "encrypt": encrypt,
            "msgsignature": signature,
            "timestamp": int(timestamp),
            "nonce": nonce,
        }


class WeComChannel(BaseChannel):
    """企业微信智能机器人消息通道

    通过 Webhook 回调接收消息，支持：
    - URL 有效性验证（GET 请求签名验证 + 解密 echostr）
    - 接收加密消息（POST 请求解密）
    - 接收事件（进入会话事件 enter_chat 等）
    - 被动回复（加密 JSON 响应，在回调中直接返回）
    - 主动回复（通过 response_url 发送 markdown/模板卡片消息）
    - 流式消息回复

    与飞书的区别：
    1. 企微使用 JSON 加密（不是 XML），POST body 为 {"encrypt": "..."} 格式
    2. URL 验证是 GET 请求（不是 POST challenge）
    3. 被动回复直接在 HTTP 响应中返回加密 JSON（不是异步 API 调用）
    4. response_url 只能使用一次，有效期 1 小时
    5. 流式消息通过持续的 stream 回调事件实现
    """

    def __init__(self, config: "WeComConfig"):
        if not HTTPX_AVAILABLE:
            raise ImportError(
                "WeCom support requires 'httpx'. "
                "Install with: pip install httpx"
            )
        if config.mode == "webhook" and not CRYPTO_AVAILABLE:
            raise ImportError(
                "WeCom webhook mode requires 'cryptography'. "
                "Install with: pip install cryptography"
            )
        if config.mode == "websocket" and not WEBSOCKETS_AVAILABLE:
            raise ImportError(
                "WeCom websocket mode requires 'websockets'. "
                "Install with: pip install websockets"
            )
        super().__init__(config)
        self.config: "WeComConfig" = config
        self._http_client: Optional[Any] = None
        self._crypto: Optional[WeComCrypto] = None
        self._ws: Optional[Any] = None
        self._ws_receive_task: Optional[asyncio.Task] = None
        self._ws_heartbeat_task: Optional[asyncio.Task] = None
        self._ws_send_lock = asyncio.Lock()
        self._ws_reconnect_attempts = 0
        self._ws_reconnecting = False
        self._ws_lock_fd: Optional[Any] = None
        self._ws_lock_path = self._build_ws_lock_path()
        self._ws_has_process_lock = False
        # 存储 response_url 映射: message_id -> response_url
        # response_url 一次性使用，每条消息对应一个
        self._response_urls: Dict[str, str] = {}
        # chat_id -> latest_message_id 映射，方便通过 chat_id 查找最新的 response_url
        self._latest_msg_ids: Dict[str, str] = {}
        # chat_id -> latest req_id 映射，便于 WebSocket 模式下回复关联
        self._latest_req_ids: Dict[str, str] = {}
        # 流式回复缓冲区: stream_id -> StreamBuffer
        self._stream_buffers: Dict[str, StreamBuffer] = {}
        # chat_id -> active stream_id 映射
        self._chat_stream_ids: Dict[str, str] = {}

    @property
    def channel_type(self) -> str:
        return "wecom"

    def _build_ws_lock_path(self) -> str:
        """Build a stable per-bot lock file path for websocket singletons."""
        bot_key = (self.config.bot_id or self.config.aibot_id or self.name or "default").strip() or "default"
        safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", bot_key)
        return os.path.join(tempfile.gettempdir(), f"virtual-human-sdk-wecom-{safe_key}.lock")

    def _acquire_ws_process_lock(self) -> bool:
        """Acquire a process-level singleton lock for WeCom websocket mode."""
        if self._ws_has_process_lock and self._ws_lock_fd:
            return True

        if not FCNTL_AVAILABLE:
            logger.warning(
                f"[{self.name}] fcntl unavailable, skipping websocket singleton lock"
            )
            return True

        lock_fd = open(self._ws_lock_path, "a+", encoding="utf-8")
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            owner = ""
            try:
                lock_fd.seek(0)
                owner = lock_fd.read().strip()
            except Exception:
                owner = ""
            lock_fd.close()
            owner_hint = f", owner={owner}" if owner else ""
            logger.warning(
                f"[{self.name}] WeCom websocket already owned by another process; "
                f"entering standby mode (lock={self._ws_lock_path}{owner_hint})"
            )
            return False

        owner = f"pid={os.getpid()} channel={self.name}"
        lock_fd.seek(0)
        lock_fd.truncate()
        lock_fd.write(owner)
        lock_fd.flush()
        self._ws_lock_fd = lock_fd
        self._ws_has_process_lock = True
        logger.info(
            f"[{self.name}] Acquired WeCom websocket singleton lock: {self._ws_lock_path} ({owner})"
        )
        return True

    def _release_ws_process_lock(self) -> None:
        """Release the process-level singleton lock for WeCom websocket mode."""
        lock_fd = self._ws_lock_fd
        self._ws_lock_fd = None
        self._ws_has_process_lock = False
        if not lock_fd or not FCNTL_AVAILABLE:
            return

        try:
            lock_fd.seek(0)
            lock_fd.truncate()
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        finally:
            try:
                lock_fd.close()
            except Exception:
                pass

    async def _start(self) -> None:
        """启动企微通道。"""
        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._ws_reconnect_attempts = 0

        if self.config.mode == "websocket":
            if not self._acquire_ws_process_lock():
                logger.info(
                    f"[{self.name}] WeCom AI Bot channel started in standby mode "
                    f"(mode=websocket, bot_id={self.config.bot_id or self.config.aibot_id or 'auto'})"
                )
                return
            try:
                await self._ws_connect()
            except Exception:
                self._release_ws_process_lock()
                raise
            logger.info(
                f"[{self.name}] WeCom AI Bot channel started "
                f"(mode=websocket, bot_id={self.config.bot_id or self.config.aibot_id or 'auto'})"
            )
            return

        self._crypto = WeComCrypto(
            token=self.config.token,
            encoding_aes_key=self.config.encoding_aes_key,
        )
        logger.info(
            f"[{self.name}] WeCom AI Bot channel started "
            f"(mode=webhook, aibot_id={self.config.aibot_id or 'auto'})"
        )

    async def _stop(self) -> None:
        """停止企微通道"""
        await self._ws_disconnect()
        self._release_ws_process_lock()
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._crypto = None
        self._response_urls.clear()
        self._latest_msg_ids.clear()
        self._latest_req_ids.clear()
        self._stream_buffers.clear()
        self._chat_stream_ids.clear()

    # ============== URL 验证 ==============

    def verify_url(
        self,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        echostr: str,
    ) -> Optional[str]:
        """验证 URL 有效性（仅 Webhook 模式使用）。"""
        if self.config.mode != "webhook":
            logger.warning(f"[{self.name}] verify_url ignored in websocket mode")
            return None

        if not self._crypto:
            logger.error(f"[{self.name}] Crypto not initialized")
            return None

        # URL decode
        echostr = unquote(echostr)

        # 验证签名
        if not self._crypto.verify_signature(msg_signature, timestamp, nonce, echostr):
            logger.warning(f"[{self.name}] URL verification: signature mismatch")
            return None

        # 解密 echostr
        try:
            decrypted = self._crypto.decrypt(echostr)
            return decrypted
        except Exception as e:
            logger.error(f"[{self.name}] URL verification: decrypt failed: {e}")
            return None

    # ============== Webhook 事件处理 ==============

    async def handle_webhook(
        self,
        body: bytes,
        headers: Dict[str, str],
        query_params: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """处理企微 Webhook 回调。"""
        if self.config.mode != "webhook":
            logger.warning(f"[{self.name}] Webhook callback ignored in websocket mode")
            return None

        if not self._crypto:
            logger.error(f"[{self.name}] Crypto not initialized")
            return None

        query_params = query_params or {}
        msg_signature = query_params.get("msg_signature", "")
        timestamp = query_params.get("timestamp", "")
        nonce = query_params.get("nonce", "")

        # 解析加密的 JSON
        try:
            encrypted_payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning(f"[{self.name}] Invalid webhook payload")
            return None

        encrypt = encrypted_payload.get("encrypt", "")
        if not encrypt:
            logger.warning(f"[{self.name}] Missing 'encrypt' field")
            return None

        # 验证签名
        if msg_signature and not self._crypto.verify_signature(
            msg_signature, timestamp, nonce, encrypt
        ):
            logger.warning(f"[{self.name}] Webhook signature verification failed")
            return None

        # 解密消息
        try:
            decrypted_str = self._crypto.decrypt(encrypt)
            payload = json.loads(decrypted_str)
        except Exception as e:
            logger.error(f"[{self.name}] Failed to decrypt webhook message: {e}")
            return None

        logger.debug(
            f"[{self.name}] Decrypted payload: "
            f"{json.dumps(payload, ensure_ascii=False)[:500]}"
        )

        # 根据消息类型分发处理
        msgtype = payload.get("msgtype", "")

        if msgtype == "stream":
            # 流式消息刷新事件 — 企微要求继续返回流式内容
            return await self._handle_stream_refresh(payload, nonce)

        # 检查是否是事件（如进入会话事件）
        event_type = payload.get("event_type", "")
        if event_type:
            return await self._handle_event(payload, nonce)

        # 普通消息处理
        if msgtype:
            # 启动 AI 处理并返回流式首包
            stream_id = f"stream_{uuid.uuid4().hex[:12]}"
            result = await self._handle_message(payload, stream_id=stream_id)
            if result and self._crypto:
                # 返回流式首包：开始流式回复
                first_reply = json.dumps(
                    {
                        "msgtype": "stream",
                        "stream": {
                            "id": stream_id,
                            "finish": False,
                            "content": "",
                        },
                    }
                )
                return self._crypto.encrypt_reply(first_reply, nonce)

        return None

    @staticmethod
    def _get_ws_command(data: Dict[str, Any]) -> str:
        """提取 WebSocket 消息的命令名。"""
        for key in ("cmd", "command", "type", "action", "event"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return ""

    @staticmethod
    def _get_ws_headers(data: Dict[str, Any]) -> Dict[str, Any]:
        """提取 WebSocket 消息头。"""
        headers = data.get("headers")
        return headers if isinstance(headers, dict) else {}

    @classmethod
    def _extract_ws_payload(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """提取 WebSocket 消息中的业务负载。"""
        body = data.get("body")
        if isinstance(body, dict):
            return body
        for key in ("data", "payload", "message", "msg", "event_data"):
            value = data.get(key)
            if isinstance(value, dict):
                return value
        return data

    @classmethod
    def _get_ws_req_id(cls, data: Dict[str, Any], payload: Optional[Dict[str, Any]] = None) -> str:
        """提取 WebSocket 消息的 req_id。"""
        headers = cls._get_ws_headers(data)
        payload = payload or cls._extract_ws_payload(data)
        for candidate in (
            headers.get("req_id"),
            data.get("req_id"),
            payload.get("req_id"),
            headers.get("request_id"),
            data.get("request_id"),
            payload.get("request_id"),
        ):
            if isinstance(candidate, str) and candidate:
                return candidate
        return ""

    @staticmethod
    def _get_ws_event_type(payload: Dict[str, Any], data: Optional[Dict[str, Any]] = None) -> str:
        """提取 WebSocket 事件类型。"""
        # Check nested event dict in both payload and data
        for source in (payload, data) if data else (payload,):
            if not source:
                continue
            event = source.get("event")
            if isinstance(event, dict):
                for key in ("eventtype", "type", "event_type"):
                    val = event.get(key)
                    if isinstance(val, str) and val:
                        return val
        # Fallback to top-level event_type fields
        for source in (payload, data) if data else (payload,):
            if not source:
                continue
            for key in ("event_type", "eventtype"):
                val = source.get(key)
                if isinstance(val, str) and val:
                    return val
        return ""

    def _cache_ws_req_id(self, chat_id: str, sender_id: str, req_id: str) -> None:
        """缓存最近一次可回复的 req_id。"""
        if not req_id:
            return
        if chat_id:
            self._latest_req_ids[chat_id] = req_id
        if sender_id and sender_id != chat_id:
            self._latest_req_ids[sender_id] = req_id

    def _parse_message_payload(
        self,
        payload: dict,
        *,
        stream_id: Optional[str] = None,
        req_id: str = "",
        ws_mode: bool = False,
    ) -> InboundMessage:
        """将企微消息负载解析为统一的 InboundMessage。"""
        msgtype = payload.get("msgtype", "")
        msgid = payload.get("msgid", "") or req_id or f"ws_{uuid.uuid4().hex[:12]}"
        aibot_id = payload.get("aibotid", "")
        chattype = payload.get("chattype", "single")
        chatid = payload.get("chatid", "")
        from_info = payload.get("from", {})
        userid = from_info.get("userid", "")
        response_url = payload.get("response_url", "")

        if not chatid:
            chatid = userid

        text_content = ""
        media_list: List[MediaAttachment] = []
        content_parts: list[dict] = []
        inbound_msg_type = MessageType.TEXT

        if msgtype == "text":
            text_obj = payload.get("text", {})
            text_content = text_obj.get("content", "")
        elif msgtype == "image":
            inbound_msg_type = MessageType.IMAGE
            image_obj = payload.get("image", {})
            image_url = image_obj.get("url", "")
            if image_url:
                media_list.append(MediaAttachment(url=image_url, mime_type=None))
        elif msgtype == "voice":
            inbound_msg_type = MessageType.VOICE
            voice_obj = payload.get("voice", {})
            text_content = voice_obj.get("content", "")
        elif msgtype == "file":
            inbound_msg_type = MessageType.DOCUMENT
            file_obj = payload.get("file", {})
            file_url = file_obj.get("url", "")
            file_name = file_obj.get("file_name", "") or file_obj.get("filename", "")
            if file_url:
                media_list.append(
                    MediaAttachment(
                        url=file_url,
                        file_name=file_name or None,
                        mime_type="application/octet-stream",
                    )
                )
        elif msgtype == "mixed":
            mixed_obj = payload.get("mixed", {})
            msg_items = mixed_obj.get("msg_item", [])
            for item in msg_items:
                item_type = item.get("msgtype", "")
                if item_type == "text":
                    t = item.get("text", {}).get("content", "")
                    if t:
                        text_content += t
                        content_parts.append({"type": "text", "content": t})
                elif item_type == "image":
                    img_url = item.get("image", {}).get("url", "")
                    if img_url:
                        media_list.append(MediaAttachment(url=img_url, mime_type=None))
                        content_parts.append({"type": "image", "url": img_url})
            if media_list:
                inbound_msg_type = MessageType.IMAGE
        else:
            text_content = f"[{msgtype} message]"

        quote = payload.get("quote")
        if quote:
            quote_type = quote.get("msgtype", "")
            quote_content = ""
            if quote_type == "text":
                quote_content = quote.get("text", {}).get("content", "")
            elif quote_type == "voice":
                quote_content = quote.get("voice", {}).get("content", "")
            if quote_content:
                text_content = f"[引用: {quote_content[:100]}]\n{text_content}"

        # 去掉群聊消息中的 @机器人名 前缀
        # 企微群聊 @机器人时，消息格式为 "@机器人名 实际内容"
        if text_content and text_content.startswith("@"):
            space_idx = text_content.find(" ")
            if space_idx != -1:
                text_content = text_content[space_idx + 1:]

        return InboundMessage(
            channel="wecom",
            sender_id=userid,
            sender_name="",
            chat_id=chatid,
            chat_type="private" if chattype == "single" else "group",
            message_id=msgid,
            content=text_content.strip(),
            message_type=inbound_msg_type,
            media=media_list,
            content_parts=content_parts,
            metadata={
                "chattype": chattype,
                "aibotid": aibot_id,
                "response_url": response_url,
                "msgtype": msgtype,
                "stream_id": stream_id or "",
                "req_id": req_id,
                "ws_mode": ws_mode,
            },
        )

    async def _ws_handle_msg_callback(self, data: Dict[str, Any]) -> None:
        """处理 WebSocket 模式的消息回调。"""
        payload = self._extract_ws_payload(data)
        req_id = self._get_ws_req_id(data, payload)
        inbound = self._parse_message_payload(payload, req_id=req_id, ws_mode=True)
        self._cache_ws_req_id(inbound.chat_id, inbound.sender_id, req_id)
        logger.info(
            f"[{self.name}] WS message received: type={payload.get('msgtype', '')}, "
            f"chat={inbound.chat_id}, req_id={req_id}"
        )
        await self._handle_inbound_message(inbound)

    async def _ws_handle_event_callback(self, data: Dict[str, Any]) -> None:
        """处理 WebSocket 模式的事件回调。"""
        payload = self._extract_ws_payload(data)
        event_type = self._get_ws_event_type(payload, data)
        req_id = self._get_ws_req_id(data, payload)
        from_info = payload.get("from", {})
        userid = from_info.get("userid", "")
        chatid = payload.get("chatid", "") or userid
        self._cache_ws_req_id(chatid, userid, req_id)

        logger.info(
            f"[{self.name}] WS event received: event={event_type}, chat={chatid}, req_id={req_id}"
        )

        if event_type == "enter_chat":
            welcome_text = str(self.config.extra.get("welcome_message", "")).strip()
            if welcome_text and req_id:
                await self._ws_respond_welcome_msg(req_id, welcome_text)
            return

        if event_type == "feedback_event":
            logger.info(
                f"[{self.name}] Feedback from {userid}: "
                f"type={payload.get('feedback_type', '')}, "
                f"content={payload.get('feedback_content', '')}"
            )
            return

        if event_type == "template_card_event":
            logger.info(f"[{self.name}] Template card event received: req_id={req_id}")
            return

        if event_type == "disconnected_event":
            logger.warning(f"[{self.name}] WS disconnected_event received")
            if not self._stop_event.is_set():
                await self._ws_handle_reconnect()
            return

    async def _ws_connect(self) -> None:
        """建立智能机器人 WebSocket 长连接并完成订阅。"""
        self._ws = await websockets.connect(
            self.config.ws_url,
            ping_interval=None,
            ping_timeout=None,
            close_timeout=10,
        )
        self._ws_receive_task = asyncio.create_task(self._ws_receive_loop())
        await self._send_via_websocket(
            "aibot_subscribe",
            {
                "bot_id": self.config.bot_id,
                "secret": self.config.secret,
            },
        )
        self._ws_heartbeat_task = asyncio.create_task(self._ws_heartbeat_loop())
        self._ws_reconnect_attempts = 0
        logger.info(f"[{self.name}] Connected to WeCom openws")

    async def _ws_disconnect(self) -> None:
        """断开 WebSocket 连接并清理后台任务。"""
        current_task = asyncio.current_task()
        for attr in ("_ws_receive_task", "_ws_heartbeat_task"):
            task = getattr(self, attr)
            if task and task is not current_task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            setattr(self, attr, None)

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _ws_receive_loop(self) -> None:
        """消费 WebSocket 下行消息。"""
        try:
            async for raw_message in self._ws:
                if raw_message == "pong":
                    continue
                try:
                    data = json.loads(raw_message)
                except json.JSONDecodeError:
                    logger.warning(f"[{self.name}] Invalid WS message: {raw_message[:200]}")
                    continue

                command = self._get_ws_command(data)
                payload = self._extract_ws_payload(data)
                req_id = self._get_ws_req_id(data, payload)
                event_type = self._get_ws_event_type(payload, data)

                # 检查订阅确认/错误响应
                if command in {"aibot_subscribe_ack", "subscribed", "subscribe"} or (
                    not command and "errcode" in data
                ):
                    errcode = data.get("errcode") or payload.get("errcode") or 0
                    if errcode:
                        errmsg = data.get("errmsg") or payload.get("errmsg") or ""
                        logger.error(
                            f"[{self.name}] WS subscribe failed: "
                            f"errcode={errcode}, errmsg={errmsg}"
                        )
                    else:
                        logger.info(
                            f"[{self.name}] WS subscribe confirmed: command={command or 'ack'}, req_id={req_id}"
                        )
                    continue

                if command in {"pong", "ping"}:
                    logger.debug(f"[{self.name}] WS control message: {command}")
                    continue

                if command == "aibot_msg_callback" or (
                    payload.get("msgtype") and req_id and payload.get("msgtype") != "event"
                ):
                    await self._ws_handle_msg_callback(data)
                    continue

                if command == "aibot_event_callback" or event_type:
                    should_exit_receive_loop = await self._ws_handle_event_callback(data)
                    if should_exit_receive_loop:
                        return
                    continue

                if command == "disconnected_event":
                    logger.warning(f"[{self.name}] WS disconnected by server")
                    if not self._stop_event.is_set():
                        await self._ws_handle_reconnect()
                    return

                logger.debug(
                    f"[{self.name}] Unhandled WS message: "
                    f"{json.dumps(data, ensure_ascii=False)[:500]}"
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[{self.name}] WS receive loop error: {e}", exc_info=True)
            if not self._stop_event.is_set():
                await self._ws_handle_reconnect()

    async def _ws_heartbeat_loop(self) -> None:
        """定时发送心跳，保持 WebSocket 活跃。"""
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(max(self.config.heartbeat_interval, 5))
                if self._stop_event.is_set():
                    break
                await self._send_via_websocket("ping")
                logger.debug(f"[{self.name}] WS heartbeat sent")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[{self.name}] WS heartbeat error: {e}", exc_info=True)
            if not self._stop_event.is_set():
                await self._ws_handle_reconnect()

    async def _ws_handle_reconnect(self) -> None:
        """指数退避重连。"""
        if self._stop_event.is_set() or self._ws_reconnecting:
            return

        self._ws_reconnecting = True
        try:
            await self._ws_disconnect()
            self._ws_reconnect_attempts += 1
            if self._ws_reconnect_attempts > self.config.reconnect_max_attempts:
                await self._handle_error(RuntimeError("WeCom websocket max reconnect attempts reached"))
                return

            delay = min(
                self.config.reconnect_base_delay * (2 ** (self._ws_reconnect_attempts - 1)),
                self.config.reconnect_max_delay,
            )
            logger.info(
                f"[{self.name}] Reconnecting WeCom websocket in {delay:.1f}s "
                f"(attempt {self._ws_reconnect_attempts})"
            )
            await asyncio.sleep(delay)
            if not self._stop_event.is_set():
                await self._ws_connect()
        finally:
            self._ws_reconnecting = False

    async def _send_via_websocket(
        self,
        command: str,
        body: Optional[Dict[str, Any]] = None,
        *,
        req_id: Optional[str] = None,
    ) -> bool:
        """通过 WebSocket 发送 JSON 命令。"""
        if not self._ws:
            logger.warning(f"[{self.name}] WebSocket is not connected")
            return False

        effective_req_id = req_id or f"wecom-{uuid.uuid4().hex[:16]}"
        message: Dict[str, Any] = {
            "cmd": command,
            "headers": {
                "req_id": effective_req_id,
            },
        }
        if body is not None:
            message["body"] = body

        async with self._ws_send_lock:
            await self._ws.send(json.dumps(message, ensure_ascii=False))
        return True

    async def _handle_event(
        self, payload: dict, nonce: str
    ) -> Optional[Dict[str, Any]]:
        """处理企微智能机器人事件

        目前支持的事件类型：
        - enter_chat: 用户进入会话事件（可被动回复欢迎语）
        - feedback: 用户反馈事件

        Args:
            payload: 解密后的事件 JSON
            nonce: 回调请求中的 nonce

        Returns:
            被动回复的加密 JSON，或 None
        """
        event_type = payload.get("event_type", "")
        response_url = payload.get("response_url", "")
        from_info = payload.get("from", {})
        userid = from_info.get("userid", "")
        chatid = payload.get("chatid", "")

        if not chatid:
            chatid = userid

        logger.info(
            f"[{self.name}] Event: {event_type}, user={userid}, chat={chatid}"
        )

        if event_type == "enter_chat":
            # 进入会话事件 — 可以保存 response_url 用于后续欢迎语
            msgid = payload.get("msgid", str(uuid.uuid4()))
            if response_url:
                self._response_urls[msgid] = response_url
                self._latest_msg_ids[chatid] = msgid
                if userid != chatid:
                    self._latest_msg_ids[userid] = msgid

            # 可以在此返回被动回复的欢迎语
            # 目前不做被动回复，让上层应用通过 response_url 处理
            return None

        if event_type == "feedback":
            # 用户反馈事件 — 记录日志即可
            feedback_type = payload.get("feedback_type", "")
            feedback_content = payload.get("feedback_content", "")
            logger.info(
                f"[{self.name}] Feedback from {userid}: "
                f"type={feedback_type}, content={feedback_content}"
            )
            return None

        logger.debug(f"[{self.name}] Unhandled event type: {event_type}")
        return None

    async def _handle_message(self, payload: dict, stream_id: Optional[str] = None) -> Optional[str]:
        """处理 webhook 模式下接收到的消息。"""
        msgid = payload.get("msgid", "")
        chatid = payload.get("chatid", "")
        from_info = payload.get("from", {})
        userid = from_info.get("userid", "")
        response_url = payload.get("response_url", "")

        if not chatid:
            chatid = userid

        if response_url and msgid:
            self._response_urls[msgid] = response_url
            self._latest_msg_ids[chatid] = msgid
            if userid != chatid:
                self._latest_msg_ids[userid] = msgid

        inbound = self._parse_message_payload(payload, stream_id=stream_id)

        if stream_id:
            buf = StreamBuffer(
                stream_id=stream_id,
                chat_id=chatid,
                response_url=response_url,
            )
            self._stream_buffers[stream_id] = buf
            self._chat_stream_ids[chatid] = stream_id
            logger.info(
                f"[{self.name}] Stream buffer created: stream_id={stream_id}, "
                f"chat_id={chatid}"
            )

        await self._handle_inbound_message(inbound)
        return stream_id

    async def _handle_stream_refresh(
        self, payload: dict, nonce: str
    ) -> Optional[Dict[str, Any]]:
        """处理流式消息刷新事件

        当之前回复了流式消息后，企微会持续回调此事件（最长 6 分钟），
        要求开发者继续返回流式内容。

        从 StreamBuffer 中取出全量内容返回给企微。
        企微流式回复的 content 是全量替换模式，不是增量追加。
        如果 AI 已完成或流超时，返回 finish=True 结束流。
        """
        stream_obj = payload.get("stream", {})
        stream_id = stream_obj.get("id", "")
        chatid = payload.get("chatid", "")
        from_info = payload.get("from", {})
        userid = from_info.get("userid", "")

        if not chatid:
            chatid = userid

        buf = self._stream_buffers.get(stream_id)
        if not buf:
            logger.debug(
                f"[{self.name}] Stream refresh for unknown stream_id={stream_id}, "
                f"finishing immediately"
            )
            return self._build_stream_reply(stream_id, "", True, nonce)

        # 等待新内容到达（最多等 4 秒，给 1 秒余量确保在 5 秒超时内返回）
        await buf.wait_for_content(timeout=4.0)

        # 获取全量内容（企微每次覆盖显示）
        content = buf.get_content()

        # 判断是否结束
        finish = False
        if buf.finished:
            finish = True
            self._cleanup_stream(stream_id, chatid)
            logger.info(
                f"[{self.name}] Stream completed: stream_id={stream_id}, "
                f"total_sent={len(content)} chars"
            )
        elif buf.is_expired:
            # 流超过 6 分钟，结束流式回复
            finish = True
            self._cleanup_stream(stream_id, chatid)
            if not buf.finished:
                logger.info(
                    f"[{self.name}] Stream expired, will send full content "
                    f"via response_url"
                )
                asyncio.create_task(
                    self._send_remaining_via_response_url(buf)
                )

        logger.debug(
            f"[{self.name}] Stream refresh: id={stream_id}, "
            f"content_len={len(content)}, finish={finish}"
        )

        return self._build_stream_reply(stream_id, content, finish, nonce)

    def _build_stream_reply(
        self,
        stream_id: str,
        content: str,
        finish: bool,
        nonce: str,
    ) -> Optional[Dict[str, Any]]:
        """构建流式回复的加密响应"""
        if not self._crypto:
            return None
        reply_obj = {
            "msgtype": "stream",
            "stream": {
                "id": stream_id,
                "finish": finish,
                "content": content[:WECOM_MAX_LENGTH] if content else "",
            },
        }
        reply = json.dumps(reply_obj, ensure_ascii=False)
        logger.debug(f"[{self.name}] Stream reply: len={len(reply)}, finish={finish}")
        return self._crypto.encrypt_reply(reply, nonce)

    def _cleanup_stream(self, stream_id: str, chat_id: str) -> None:
        """清理流式缓冲区"""
        self._stream_buffers.pop(stream_id, None)
        if self._chat_stream_ids.get(chat_id) == stream_id:
            self._chat_stream_ids.pop(chat_id, None)

    async def _send_remaining_via_response_url(
        self, buf: StreamBuffer
    ) -> None:
        """流超时后，通过 response_url 发送完整内容"""
        if not buf.response_url or not self._http_client:
            logger.warning(
                f"[{self.name}] Cannot send remaining content: "
                f"no response_url or http client"
            )
            return

        # 等待 AI 处理完成（最多再等 60 秒）
        for _ in range(60):
            if buf.finished:
                break
            await asyncio.sleep(1)

        full_content = sanitize_wecom_markdown_content(buf.full_content)
        body = {
            "msgtype": "markdown",
            "markdown": {
                "content": full_content[:WECOM_MAX_LENGTH],
            },
        }
        try:
            resp = await self._http_client.post(
                buf.response_url,
                json=body,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            errcode = data.get("errcode", 0)
            if errcode == 0:
                logger.info(
                    f"[{self.name}] Remaining content sent via response_url "
                    f"({len(full_content)} chars)"
                )
            else:
                logger.error(
                    f"[{self.name}] Failed to send remaining: errcode={errcode}"
                )
        except Exception as e:
            logger.error(f"[{self.name}] Failed to send remaining: {e}")

    # ============== 消息发送 ==============

    async def _send_message(self, message: OutboundMessage) -> Optional[Any]:
        """发送消息到企微。"""
        content = sanitize_wecom_markdown_content(message.content or "")
        chat_id = message.chat_id

        if self.config.mode == "websocket":
            return await self.send_ws_msg(chat_id, content, msgtype="markdown")

        if not self._http_client:
            return None

        # 查找可用的 response_url
        response_url = self._find_response_url(chat_id)

        if not response_url:
            logger.warning(
                f"[{self.name}] No response_url available for chat_id={chat_id}. "
                f"Cannot send message."
            )
            return None

        # 使用主动回复接口发送 markdown 消息
        body = {
            "msgtype": "markdown",
            "markdown": {
                "content": content[:WECOM_MAX_LENGTH],
            },
        }

        try:
            resp = await self._http_client.post(
                response_url,
                json=body,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            errcode = data.get("errcode", 0)
            if errcode == 0:
                logger.debug(
                    f"[{self.name}] Message sent via response_url to {chat_id}"
                )
                return True
            else:
                logger.error(
                    f"[{self.name}] Send message failed: errcode={errcode}, "
                    f"errmsg={data.get('errmsg', '')}"
                )
                return None
        except Exception as e:
            logger.error(f"[{self.name}] Failed to send message: {e}")
            return None

    def _find_response_url(self, chat_id: str) -> Optional[str]:
        """查找并消费指定 chat_id 的 response_url

        response_url 只能使用一次，使用后自动清除。

        Returns:
            找到的 response_url，或 None
        """
        msg_id = self._latest_msg_ids.get(chat_id)
        if msg_id and msg_id in self._response_urls:
            url = self._response_urls.pop(msg_id)
            self._latest_msg_ids.pop(chat_id, None)
            return url
        return None

    @staticmethod
    def _build_ws_msg_body(content: str, msgtype: str = "markdown", **extra: Any) -> Dict[str, Any]:
        """Build a WS message body with the given msgtype and content."""
        key = "text" if msgtype == "text" else "markdown"
        body: Dict[str, Any] = {"msgtype": msgtype, key: {"content": content[:WECOM_MAX_LENGTH]}}
        body.update(extra)
        return body

    async def _ws_respond_msg(self, req_id: str, content: str, *, msgtype: str = "markdown") -> bool:
        """通过 WebSocket 回复收到的消息。"""
        if not req_id:
            return False
        return await self._send_via_websocket(
            "aibot_respond_msg", self._build_ws_msg_body(content, msgtype), req_id=req_id
        )

    async def _ws_respond_welcome_msg(self, req_id: str, content: str) -> bool:
        """通过 WebSocket 回复进入会话欢迎语。"""
        if not req_id:
            return False
        return await self._send_via_websocket(
            "aibot_respond_welcome_msg",
            {
                "msgtype": "text",
                "text": {"content": content[:WECOM_MAX_LENGTH]},
            },
            req_id=req_id,
        )

    async def send_ws_stream_update(
        self,
        req_id: str,
        stream_id: str,
        content: str,
        *,
        finish: bool = False,
    ) -> bool:
        """通过 WebSocket 发送流式消息更新。"""
        if not req_id or not stream_id:
            return False
        return await self._send_via_websocket(
            "aibot_respond_msg",
            {
                "msgtype": "stream",
                "stream": {
                    "id": stream_id,
                    "finish": finish,
                    "content": content[:WECOM_MAX_LENGTH],
                },
            },
            req_id=req_id,
        )

    async def send_ws_stream_finish(self, req_id: str, stream_id: str, content: str) -> bool:
        """结束 WebSocket 流式消息。"""
        return await self.send_ws_stream_update(req_id, stream_id, content, finish=True)

    async def send_ws_msg(self, chatid: str, content: str, *, msgtype: str = "markdown") -> bool:
        """通过 WebSocket 主动推送消息。"""
        if not chatid:
            return False
        return await self._send_via_websocket(
            "aibot_send_msg", self._build_ws_msg_body(content, msgtype, chatid=chatid)
        )

    async def send_passive_reply(
        self,
        content: str,
        nonce: str,
        stream_id: Optional[str] = None,
        finish: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """构建被动回复的加密响应

        用于在 webhook 回调中直接返回回复消息（需在 5 秒内返回）。

        Args:
            content: 回复内容（text 或 markdown）
            nonce: 回调请求中的 nonce（文档要求必须使用回调的 nonce）
            stream_id: 流式消息 ID（用于流式回复）
            finish: 流式消息是否结束

        Returns:
            加密后的响应 JSON
        """
        if not self._crypto:
            return None

        if stream_id:
            # 流式消息回复
            reply = {
                "msgtype": "stream",
                "stream": {
                    "id": stream_id,
                    "finish": finish,
                    "content": content[:WECOM_MAX_LENGTH],
                },
            }
        else:
            # 普通文本回复（仅支持在进入会话事件中）
            reply = {
                "msgtype": "text",
                "text": {
                    "content": content[:WECOM_MAX_LENGTH],
                },
            }

        return self._crypto.encrypt_reply(json.dumps(reply), nonce)

    async def send_typing(self, chat_id: str) -> None:
        """企微没有 typing 指示 API"""
        pass

    # ============== 消息编辑 ==============

    async def edit_message(self, message_id: str, content: str) -> bool:
        """企微智能机器人不支持编辑已发送的消息

        Returns:
            始终返回 False
        """
        logger.debug(
            f"[{self.name}] WeCom AI Bot does not support message editing"
        )
        return False

    # ============== 辅助方法 ==============

    def get_response_url(self, chat_id: str) -> Optional[str]:
        """获取指定会话的 response_url（不消费，仅查看）"""
        msg_id = self._latest_msg_ids.get(chat_id)
        if msg_id:
            return self._response_urls.get(msg_id)
        return None

    def set_response_url(self, chat_id: str, url: str, msg_id: Optional[str] = None) -> None:
        """手动设置指定会话的 response_url"""
        if not msg_id:
            msg_id = str(uuid.uuid4())
        self._response_urls[msg_id] = url
        self._latest_msg_ids[chat_id] = msg_id

    def get_stream_buffer(self, chat_id: str) -> Optional[StreamBuffer]:
        """获取指定会话的活跃流式缓冲区"""
        stream_id = self._chat_stream_ids.get(chat_id)
        if stream_id:
            return self._stream_buffers.get(stream_id)
        return None

    def get_stream_buffer_by_id(self, stream_id: str) -> Optional[StreamBuffer]:
        """通过 stream_id 获取流式缓冲区"""
        return self._stream_buffers.get(stream_id)

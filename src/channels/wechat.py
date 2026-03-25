"""WeChat Channel 实现

通过 iLink Bot API 接入微信个人号。
使用 HTTP JSON + Long-Polling 模式收发消息。

协议参考: openclaw-weixin 插件 (https://github.com/nicepkg/openclaw-weixin)
API Base: https://ilinkai.weixin.qq.com
"""

import asyncio
import json
import logging
import os
import struct
import time
import uuid
from base64 import b64encode
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .base import BaseChannel
from .events import InboundMessage, MediaAttachment, MessageType, OutboundMessage

logger = logging.getLogger(__name__)

# 延迟导入 httpx
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

if TYPE_CHECKING:
    from .config import WeChatConfig

# ── iLink Bot API 常量 ──────────────────────────────────────────────────────

# 消息类型 (item_list[].type)
ITEM_TYPE_TEXT = 1
ITEM_TYPE_IMAGE = 2
ITEM_TYPE_VOICE = 3
ITEM_TYPE_FILE = 4
ITEM_TYPE_VIDEO = 5

# 消息发送者类型 (message_type)
MSG_TYPE_USER = 1
MSG_TYPE_BOT = 2

# Session expired error code
SESSION_EXPIRED_ERRCODE = -14

# 单条文本消息最大字符数
MAX_TEXT_CHUNK = 4000

# Channel 版本标识
CHANNEL_VERSION = "1.0.0"

# 默认 sync buf 持久化路径
DEFAULT_SYNC_BUF_DIR = os.path.expanduser("~/.agent-nexus")
DEFAULT_SYNC_BUF_FILE = "wechat_sync_buf.json"

# 连续失败后的退避参数
MAX_CONSECUTIVE_FAILURES = 10
BACKOFF_SLEEP_SECONDS = 30


class WeChatChannel(BaseChannel):
    """微信个人号消息通道

    通过 iLink Bot API 长轮询接收消息、HTTP POST 发送消息。

    API 端点:
    - POST /ilink/bot/getupdates   — 长轮询获取新消息
    - POST /ilink/bot/sendmessage  — 发送消息
    - POST /ilink/bot/sendtyping   — 发送输入中指示
    - POST /ilink/bot/getconfig    — 获取机器人配置（typing_ticket 等）
    """

    def __init__(self, config: "WeChatConfig"):
        super().__init__(config)
        self.config: "WeChatConfig" = config
        self._http_client: Optional[httpx.AsyncClient] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._get_updates_buf: str = ""
        self._context_tokens: Dict[str, str] = {}  # from_user_id -> context_token
        self._consecutive_failures: int = 0

    @property
    def channel_type(self) -> str:
        return "wechat"

    # ── 生命周期 ────────────────────────────────────────────────────────────

    async def _start(self) -> None:
        """启动 WeChat 长轮询"""
        if not HTTPX_AVAILABLE:
            raise ImportError(
                "WeChat support requires 'httpx'. "
                "Install with: pip install httpx"
            )

        # 加载持久化的 sync cursor
        self._load_sync_buf()

        # 创建 HTTP 客户端
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=self.config.poll_timeout_ms / 1000.0 + 10.0,  # 给长轮询留余量
                write=10.0,
                pool=10.0,
            ),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

        # 启动长轮询任务
        self._consecutive_failures = 0
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"[{self.name}] WeChat long-poll loop started")

    async def _stop(self) -> None:
        """停止 WeChat 长轮询"""
        # 取消轮询任务
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        # 持久化 sync cursor
        self._save_sync_buf()

        # 关闭 HTTP 客户端
        if self._http_client:
            try:
                await self._http_client.aclose()
            except Exception:
                pass
            self._http_client = None

        logger.info(f"[{self.name}] WeChat channel stopped")

    # ── HTTP 请求工具 ───────────────────────────────────────────────────────

    def _build_headers(self) -> Dict[str, str]:
        """构建 iLink Bot API 请求头"""
        # X-WECHAT-UIN: random uint32 -> decimal string -> base64
        rand_uint32 = struct.unpack(">I", os.urandom(4))[0]
        wechat_uin = b64encode(str(rand_uint32).encode()).decode()

        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": wechat_uin,
        }
        if self.config.bot_token:
            headers["Authorization"] = f"Bearer {self.config.bot_token}"
        return headers

    @staticmethod
    def _build_base_info() -> Dict[str, str]:
        """构建 base_info 元数据"""
        return {"channel_version": CHANNEL_VERSION}

    def _api_url(self, endpoint: str) -> str:
        """构建完整 API URL"""
        base = self.config.base_url.rstrip("/")
        return f"{base}/{endpoint}"

    async def _api_post(
        self,
        endpoint: str,
        body: dict,
        timeout_ms: Optional[int] = None,
    ) -> dict:
        """通用 API POST 请求"""
        if not self._http_client:
            raise RuntimeError("HTTP client not initialized")

        url = self._api_url(endpoint)
        headers = self._build_headers()
        body["base_info"] = self._build_base_info()
        payload = json.dumps(body)

        timeout_s = (timeout_ms or self.config.api_timeout_ms) / 1000.0
        try:
            resp = await self._http_client.post(
                url,
                content=payload,
                headers=headers,
                timeout=timeout_s,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            # 长轮询超时是正常的
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"[{self.name}] API {endpoint} HTTP error: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"[{self.name}] API {endpoint} error: {e}")
            raise

    # ── 长轮询循环 ──────────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        """getUpdates 长轮询主循环"""
        logger.info(f"[{self.name}] Entering poll loop")
        while not self._stop_event.is_set():
            try:
                resp = await self._get_updates()

                # 检查错误
                ret = resp.get("ret", 0)
                errcode = resp.get("errcode")

                if ret != 0 or (errcode and errcode != 0):
                    # Session 过期
                    if errcode == SESSION_EXPIRED_ERRCODE:
                        logger.error(
                            f"[{self.name}] Session expired (errcode={errcode}), "
                            "bot_token may need refresh. Stopping channel."
                        )
                        self.state = self.state.__class__("error")
                        return

                    # 其他错误
                    self._consecutive_failures += 1
                    logger.warning(
                        f"[{self.name}] getUpdates failed: ret={ret} errcode={errcode} "
                        f"errmsg={resp.get('errmsg', '')} "
                        f"({self._consecutive_failures}/{MAX_CONSECUTIVE_FAILURES})"
                    )
                    if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        logger.error(
                            f"[{self.name}] {MAX_CONSECUTIVE_FAILURES} consecutive failures, "
                            f"backing off {BACKOFF_SLEEP_SECONDS}s"
                        )
                        await asyncio.sleep(BACKOFF_SLEEP_SECONDS)
                        self._consecutive_failures = 0
                    continue

                # 成功 — 重置失败计数
                self._consecutive_failures = 0

                # 更新 sync cursor
                new_buf = resp.get("get_updates_buf")
                if new_buf is not None:
                    self._get_updates_buf = new_buf
                    # 每次成功都持久化（频率可根据需要降低）
                    self._save_sync_buf()

                # 处理消息
                msgs = resp.get("msgs") or []
                for msg in msgs:
                    try:
                        await self._handle_message(msg)
                    except Exception as e:
                        logger.error(f"[{self.name}] Error handling message: {e}", exc_info=True)

            except asyncio.CancelledError:
                raise

            except httpx.TimeoutException:
                # 长轮询超时是正常的，直接重试
                logger.debug(f"[{self.name}] getUpdates long-poll timeout, retrying")
                continue

            except Exception as e:
                self._consecutive_failures += 1
                logger.error(
                    f"[{self.name}] Poll loop error ({self._consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}): {e}",
                    exc_info=True,
                )
                if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.error(
                        f"[{self.name}] {MAX_CONSECUTIVE_FAILURES} consecutive failures, "
                        f"backing off {BACKOFF_SLEEP_SECONDS}s"
                    )
                    await asyncio.sleep(BACKOFF_SLEEP_SECONDS)
                    self._consecutive_failures = 0
                else:
                    # 短暂等待后重试
                    await asyncio.sleep(min(
                        self.config.reconnect_base_delay * self._consecutive_failures,
                        self.config.reconnect_max_delay,
                    ))

        logger.info(f"[{self.name}] Poll loop exited")

    async def _get_updates(self) -> dict:
        """调用 getUpdates API（长轮询）"""
        body = {
            "get_updates_buf": self._get_updates_buf,
        }
        return await self._api_post(
            "ilink/bot/getupdates",
            body,
            timeout_ms=self.config.poll_timeout_ms + 5000,  # 给客户端留 5s 余量
        )

    # ── 消息接收处理 ────────────────────────────────────────────────────────

    async def _handle_message(self, msg: dict) -> None:
        """处理单条 WeixinMessage"""
        # 只处理用户消息 (message_type == 1)
        message_type = msg.get("message_type", 0)
        if message_type != MSG_TYPE_USER:
            logger.debug(f"[{self.name}] Ignoring non-user message (message_type={message_type})")
            return

        from_user_id = msg.get("from_user_id", "")
        if not from_user_id:
            return

        # 缓存 context_token（回复时需要）
        context_token = msg.get("context_token")
        if context_token:
            self._context_tokens[from_user_id] = context_token

        # 解析 item_list
        item_list = msg.get("item_list") or []
        content_parts: List[str] = []
        msg_type = MessageType.TEXT
        media_list: List[MediaAttachment] = []

        for item in item_list:
            item_type = item.get("type", 0)
            if item_type == ITEM_TYPE_TEXT:
                text_item = item.get("text_item", {})
                text = text_item.get("text", "")
                if text:
                    content_parts.append(text)
            elif item_type == ITEM_TYPE_IMAGE:
                msg_type = MessageType.IMAGE
                image_item = item.get("image_item", {})
                media_list.append(MediaAttachment(
                    url=image_item.get("url"),
                    mime_type="image/jpeg",
                    width=image_item.get("thumb_width"),
                    height=image_item.get("thumb_height"),
                ))
            elif item_type == ITEM_TYPE_VOICE:
                msg_type = MessageType.VOICE
                voice_item = item.get("voice_item", {})
                media_list.append(MediaAttachment(
                    mime_type="audio/silk",
                    duration=voice_item.get("playtime"),
                ))
                # 语音转文字
                voice_text = voice_item.get("text")
                if voice_text:
                    content_parts.append(f"[语音转文字] {voice_text}")
            elif item_type == ITEM_TYPE_FILE:
                msg_type = MessageType.DOCUMENT
                file_item = item.get("file_item", {})
                media_list.append(MediaAttachment(
                    file_name=file_item.get("file_name"),
                    file_size=int(file_item.get("len", 0)) if file_item.get("len") else None,
                ))
            elif item_type == ITEM_TYPE_VIDEO:
                msg_type = MessageType.VIDEO
                video_item = item.get("video_item", {})
                media_list.append(MediaAttachment(
                    mime_type="video/mp4",
                    duration=video_item.get("play_length"),
                    width=video_item.get("thumb_width"),
                    height=video_item.get("thumb_height"),
                ))
            else:
                logger.debug(f"[{self.name}] Unknown item type: {item_type}")

        content = "\n".join(content_parts)

        # 如果只有媒体没有文字，设置占位内容
        if not content and media_list:
            type_names = {
                MessageType.IMAGE: "[图片]",
                MessageType.VOICE: "[语音]",
                MessageType.VIDEO: "[视频]",
                MessageType.DOCUMENT: "[文件]",
            }
            content = type_names.get(msg_type, "[媒体]")

        # 忽略空消息
        if not content and not media_list:
            return

        # 确定聊天类型
        group_id = msg.get("group_id")
        chat_type = "group" if group_id else "private"
        chat_id = group_id or msg.get("session_id") or from_user_id

        # 消息时间戳
        create_time_ms = msg.get("create_time_ms")
        if create_time_ms:
            timestamp = datetime.fromtimestamp(create_time_ms / 1000.0, tz=timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        # 构建 InboundMessage
        inbound = InboundMessage(
            channel=self.channel_type,
            sender_id=from_user_id,
            sender_name=from_user_id,  # WeChat API 不提供昵称
            chat_id=chat_id,
            chat_type=chat_type,
            message_id=str(msg.get("message_id", "")),
            content=content,
            message_type=msg_type if not media_list or content_parts else msg_type,
            media=media_list,
            metadata={
                "context_token": context_token,
                "session_id": msg.get("session_id"),
                "seq": msg.get("seq"),
                "client_id": msg.get("client_id"),
            },
            timestamp=timestamp,
        )

        await self._handle_inbound_message(inbound)

    # ── 消息发送 ────────────────────────────────────────────────────────────

    async def _send_message(self, message: OutboundMessage) -> Optional[Any]:
        """发送消息到 WeChat"""
        if not self._http_client:
            raise RuntimeError("HTTP client not initialized")

        content = message.content or ""
        if not content:
            logger.debug(f"[{self.name}] Skipping empty outbound message")
            return None

        # 获取对方的 context_token
        context_token = self._context_tokens.get(message.chat_id)

        # 分段发送（每段最多 4000 字符）
        chunks = self._split_text(content, MAX_TEXT_CHUNK)
        results = []

        for chunk in chunks:
            result = await self._send_text_chunk(message.chat_id, chunk, context_token)
            results.append(result)

        return results

    async def _send_text_chunk(
        self,
        to_user_id: str,
        text: str,
        context_token: Optional[str] = None,
    ) -> dict:
        """发送单段文本消息"""
        msg_payload: Dict[str, Any] = {
            "to_user_id": to_user_id,
            "message_type": MSG_TYPE_BOT,
            "client_id": str(uuid.uuid4()),
            "item_list": [
                {
                    "type": ITEM_TYPE_TEXT,
                    "text_item": {"text": text},
                }
            ],
        }
        if context_token:
            msg_payload["context_token"] = context_token

        body = {"msg": msg_payload}
        return await self._api_post("ilink/bot/sendmessage", body)

    async def send_typing(self, chat_id: str) -> None:
        """发送「输入中」指示"""
        try:
            # 先获取 typing_ticket
            context_token = self._context_tokens.get(chat_id)
            config_resp = await self._api_post("ilink/bot/getconfig", {
                "ilink_user_id": chat_id,
                "context_token": context_token or "",
            })
            typing_ticket = config_resp.get("typing_ticket")
            if not typing_ticket:
                return

            await self._api_post("ilink/bot/sendtyping", {
                "ilink_user_id": chat_id,
                "typing_ticket": typing_ticket,
                "status": 1,  # 1=typing
            })
        except Exception as e:
            # typing 失败不影响主流程
            logger.debug(f"[{self.name}] Failed to send typing indicator: {e}")

    # ── Sync Buf 持久化 ────────────────────────────────────────────────────

    def _get_sync_buf_path(self) -> Path:
        """获取 sync buf 文件路径"""
        if self.config.sync_buf_path:
            return Path(self.config.sync_buf_path)
        return Path(DEFAULT_SYNC_BUF_DIR) / DEFAULT_SYNC_BUF_FILE

    def _load_sync_buf(self) -> None:
        """从文件加载 get_updates_buf"""
        path = self._get_sync_buf_path()
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                self._get_updates_buf = data.get("get_updates_buf", "")
                logger.info(
                    f"[{self.name}] Loaded sync buf from {path} "
                    f"({len(self._get_updates_buf)} bytes)"
                )
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to load sync buf from {path}: {e}")
            self._get_updates_buf = ""

    def _save_sync_buf(self) -> None:
        """持久化 get_updates_buf 到文件"""
        path = self._get_sync_buf_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"get_updates_buf": self._get_updates_buf}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to save sync buf to {path}: {e}")

    # ── 工具方法 ────────────────────────────────────────────────────────────

    @staticmethod
    def _split_text(text: str, max_len: int) -> List[str]:
        """将文本按最大长度分段，尽量在换行处断开"""
        if len(text) <= max_len:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break

            # 尝试在换行处断开
            split_pos = text.rfind("\n", 0, max_len)
            if split_pos <= 0:
                # 没有合适的换行，直接截断
                split_pos = max_len

            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")

        return chunks

    async def health_check(self) -> bool:
        """健康检查"""
        if not self.is_running:
            return False
        if self._poll_task and self._poll_task.done():
            return False
        return True

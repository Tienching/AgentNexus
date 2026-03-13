"""企业微信普通机器人 (WeCom Bot) Channel 实现

基于企业微信普通机器人 API，通过 Webhook 回调接收消息，
通过 webhook/send 主动发送消息：
- 单聊：等 AI 完成后一次性发送完整回复
- 群聊：通过 webhook/send 多次发送模拟流式效果

参考文档：
- 接收消息: https://developer.work.weixin.qq.com/document/path/99109
- 被动回复: https://developer.work.weixin.qq.com/document/path/99111
- 主动消息通告(webhook): https://developer.work.weixin.qq.com/document/path/99110
- 加解密方案: https://developer.work.weixin.qq.com/document/path/101033
"""

import asyncio
import json
import logging
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .base import BaseChannel
from .events import InboundMessage, MediaAttachment, MessageType, OutboundMessage
from .wecom_aibot import sanitize_wecom_markdown_content

logger = logging.getLogger(__name__)

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None

if TYPE_CHECKING:
    from .config import WeComBotConfig
    from .wecom_aibot import WeComCrypto

# WeCom Bot message length limits (bytes, UTF-8)
# Webhook: text ≤ 2048B, markdown ≤ 4096B
WECOM_BOT_TEXT_MAX_BYTES = 2048
WECOM_BOT_MARKDOWN_MAX_BYTES = 4096  # webhook markdown
# Legacy constant for backward compat (notification sink etc.)
WECOM_BOT_MAX_LENGTH = 20480

# Webhook 频率限制: 20 条/分钟 → 至少 3s 间隔
WECOM_WEBHOOK_MIN_INTERVAL = 3.0

# Webhook API base URL
WECOM_WEBHOOK_API = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"


@dataclass
class StreamSimulator:
    """模拟流式发送的状态管理

    企微普通机器人不支持原生流式回复，需要通过多次调用 webhook/send
    来模拟流式效果。

    累积 AI 增量文本，按配置的 chunk_size 和 interval 分批发送。
    """

    chat_id: str
    # 完整的累积内容
    full_content: str = ""
    # 上次发送时的内容长度
    _last_sent_len: int = 0
    # AI 是否已完成处理
    finished: bool = False
    # 创建时间
    created_at: float = field(default_factory=time.time)
    # 用于同步的事件
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def append(self, text: str) -> None:
        """追加增量内容"""
        if text:
            self.full_content += text
            self._event.set()

    def set_final(self, text: str) -> None:
        """设置最终完整内容"""
        self.full_content = text
        self._event.set()

    def mark_finished(self) -> None:
        """标记 AI 处理完成"""
        self.finished = True
        self._event.set()

    def get_unsent_content(self) -> str:
        """获取尚未发送的增量内容"""
        content = self.full_content[self._last_sent_len:]
        return content

    def mark_sent(self, length: int) -> None:
        """标记已发送到指定位置"""
        self._last_sent_len = length
        self._event.clear()

    @property
    def has_unsent_content(self) -> bool:
        """是否有未发送的内容"""
        return len(self.full_content) > self._last_sent_len

    async def wait_for_content(self, timeout: float = 2.0) -> bool:
        """等待新内容或完成信号"""
        if self.has_unsent_content or self.finished:
            return True
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


class WeComBotChannel(BaseChannel):
    """企业微信普通机器人消息通道

    必填配置：token + encoding_aes_key + webhook_key

    发送策略：
    - 单聊 → webhook/send：等 AI 完成后一次性发送完整消息
    - 群聊 → webhook/send：流式分段发送（20 条/分钟，≥3s 间隔）

    与智能机器人的区别：
    1. 不支持原生流式被动回复（stream）
    2. 主动发送走 webhook/send（而非 response_url）
    """

    def __init__(self, config: "WeComBotConfig"):
        if not HTTPX_AVAILABLE:
            raise ImportError(
                "WeCom Bot support requires 'httpx'. "
                "Install with: pip install httpx"
            )
        super().__init__(config)
        self.config: "WeComBotConfig" = config
        self._http_client: Optional[Any] = None
        self._crypto: Optional["WeComCrypto"] = None

        # 流式模拟器: simulator_id -> StreamSimulator
        self._stream_simulators: Dict[str, StreamSimulator] = {}
        # chat_id -> active simulator_id
        self._chat_simulator_ids: Dict[str, str] = {}
        # chat_id -> 回调消息中的 WebhookUrl（用于发送回复到正确的群）
        self._chat_webhook_urls: Dict[str, str] = {}

    @property
    def channel_type(self) -> str:
        return "wecom_bot"

    async def _start(self) -> None:
        """启动通道 — 初始化 HTTP 客户端和加解密工具"""
        self._http_client = httpx.AsyncClient(timeout=30.0)

        # 复用智能机器人的 WeComCrypto 加解密模块
        from .wecom_aibot import WeComCrypto

        self._crypto = WeComCrypto(
            token=self.config.token,
            encoding_aes_key=self.config.encoding_aes_key,
        )

        logger.info(
            f"[{self.name}] WeCom Bot channel started "
            f"(webhook_key={'set' if self.config.webhook_key else 'unset'})"
        )

    async def _stop(self) -> None:
        """停止通道"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._crypto = None
        self._stream_simulators.clear()
        self._chat_simulator_ids.clear()
        self._chat_webhook_urls.clear()

    # ============== URL 验证 ==============

    def verify_url(
        self,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        echostr: str,
    ) -> Optional[str]:
        """验证 URL 有效性（配置回调 URL 时的 GET 请求验证）

        与智能机器人的验证流程完全一致：
        1. URL decode echostr
        2. 验证签名
        3. 解密 echostr
        4. 返回解密后的明文
        """
        if not self._crypto:
            logger.error(f"[{self.name}] Crypto not initialized")
            return None

        from urllib.parse import unquote

        echostr = unquote(echostr)

        if not self._crypto.verify_signature(msg_signature, timestamp, nonce, echostr):
            logger.warning(f"[{self.name}] URL verification: signature mismatch")
            return None

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
        """处理回调消息

        普通机器人的回调格式与智能机器人类似：
        POST body: {"encrypt": "..."}
        查询参数: msg_signature, timestamp, nonce

        处理流程：
        1. 解密得到明文 JSON
        2. 根据消息类型分发处理
        3. 触发 AI 处理流程，通过主动发送接口返回结果（而非被动回复）

        Returns:
            普通机器人不使用被动回复返回流式内容，
            此处返回 None 或简单的确认响应。
        """
        if not self._crypto:
            logger.error(f"[{self.name}] Crypto not initialized")
            return None

        query_params = query_params or {}
        msg_signature = query_params.get("msg_signature", "")
        timestamp = query_params.get("timestamp", "")
        nonce = query_params.get("nonce", "")

        # 解析加密消息体（支持 JSON 和 XML 两种格式）
        encrypt = ""
        body_str = body.decode("utf-8")
        try:
            # 先尝试 JSON: {"encrypt": "..."}
            encrypted_payload = json.loads(body_str)
            encrypt = encrypted_payload.get("encrypt", "")
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        if not encrypt:
            # 再尝试 XML: <xml><Encrypt>...</Encrypt></xml>
            try:
                root = ET.fromstring(body_str)
                encrypt_node = root.find("Encrypt")
                if encrypt_node is not None and encrypt_node.text:
                    encrypt = encrypt_node.text
            except ET.ParseError:
                pass

        if not encrypt:
            logger.warning(f"[{self.name}] Missing 'encrypt' field in payload (tried JSON and XML)")
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
        except Exception as e:
            logger.error(f"[{self.name}] Failed to decrypt webhook message: {e}")
            return None

        logger.info(
            f"[{self.name}] Raw decrypted message: "
            f"{decrypted_str[:1000]}"
        )

        # 解析解密后的消息（支持 JSON 和 XML）
        payload: Dict[str, Any] = {}
        try:
            payload = json.loads(decrypted_str)
        except (json.JSONDecodeError, ValueError):
            # 尝试 XML 解析 — 支持嵌套子节点
            try:
                root = ET.fromstring(decrypted_str)
                for child in root:
                    if len(child) > 0:
                        # 有子节点，递归构建 dict
                        sub = {}
                        for sub_child in child:
                            sub[sub_child.tag] = sub_child.text or ""
                        payload[child.tag] = sub
                    else:
                        payload[child.tag] = child.text or ""
            except ET.ParseError as e2:
                logger.error(
                    f"[{self.name}] Failed to parse decrypted message "
                    f"(tried JSON and XML): {e2}"
                )
                return None

        logger.info(
            f"[{self.name}] Decrypted payload: "
            f"{json.dumps(payload, ensure_ascii=False)[:500]}"
        )

        # 根据消息类型分发
        msgtype = payload.get("msgtype", "") or payload.get("MsgType", "")
        event_type = payload.get("event_type", "") or payload.get("Event", "")

        if event_type:
            await self._handle_event(payload)
            return None

        if msgtype:
            result = await self._handle_message(payload, nonce=nonce)
            return result

        return None

    async def _handle_event(self, payload: dict) -> None:
        """处理事件（如进入会话）"""
        event_type = payload.get("event_type", "") or payload.get("Event", "")
        from_info = payload.get("from", {})
        userid = from_info.get("userid", "") or payload.get("FromUserName", "")
        chatid = payload.get("chatid", "") or payload.get("ChatId", "")

        if not chatid:
            chatid = userid

        logger.info(
            f"[{self.name}] Event: {event_type}, user={userid}, chat={chatid}"
        )

    async def _handle_message(self, payload: dict, nonce: str = "") -> Optional[Dict[str, Any]]:
        """处理接收到的消息

        支持文本、图片、语音等消息类型。
        - 单聊：通过被动回复提示用户到群聊中@机器人提问
        - 群聊：创建 StreamSimulator 并触发 AI 处理
        """
        msgtype = payload.get("msgtype", "") or payload.get("MsgType", "")
        msgid = payload.get("msgid", "") or payload.get("MsgId", "")
        chattype = payload.get("chattype", "") or payload.get("ChatType", "") or "single"
        chatid = payload.get("chatid", "") or payload.get("ChatId", "")
        from_info = payload.get("from", {})
        userid = from_info.get("userid", "") or payload.get("FromUserName", "")
        logger.info(f"[WeComBot] chattype={chattype!r}, chatid={chatid!r}, userid={userid!r}")

        if not chatid:
            chatid = userid

        # 保存回调消息中的 WebhookUrl（用于发送回复到正确的群）
        webhook_url = payload.get("webhook_url", "") or payload.get("WebhookUrl", "")
        if webhook_url and chatid:
            self._chat_webhook_urls[chatid] = webhook_url
            logger.debug(f"[{self.name}] Stored webhook_url for chatid={chatid}: {webhook_url}")

        # 单聊：被动回复提示，不走 AI 处理
        if chattype == "single":
            logger.info(f"[{self.name}] Single chat from {userid}, returning passive reply hint")
            reply_text = "暂不支持单聊，请在群聊中 @我 提问 😊"
            return self._build_passive_reply(reply_text, nonce)

        # 解析消息内容
        text_content = ""
        media_list: List[MediaAttachment] = []
        _content_parts: list[dict] = []
        inbound_msg_type = MessageType.TEXT

        if msgtype == "text":
            text_obj = payload.get("text", {})
            if isinstance(text_obj, dict):
                text_content = text_obj.get("content", "")
            else:
                text_content = str(text_obj) if text_obj else ""
            # 兼容大写字段（普通机器人 JSON/XML 格式）
            if not text_content:
                text_val = payload.get("Text", "")
                if isinstance(text_val, dict):
                    text_content = text_val.get("Content", "") or text_val.get("content", "")
                elif text_val:
                    text_content = str(text_val)
            if not text_content:
                text_content = payload.get("Content", "")
        elif msgtype == "image":
            inbound_msg_type = MessageType.IMAGE
            image_obj = payload.get("image", {})
            image_url = image_obj.get("url", "") or payload.get("PicUrl", "")
            if image_url:
                media_list.append(
                    MediaAttachment(url=image_url, mime_type=None)
                )
        elif msgtype == "voice":
            inbound_msg_type = MessageType.VOICE
            voice_obj = payload.get("voice", {})
            text_content = voice_obj.get("content", "") or payload.get("Recognition", "")
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
                        _content_parts.append({"type": "text", "content": t})
                elif item_type == "image":
                    img_url = item.get("image", {}).get("url", "")
                    if img_url:
                        media_list.append(
                            MediaAttachment(url=img_url, mime_type=None)
                        )
                        _content_parts.append({"type": "image", "url": img_url})
            if media_list:
                inbound_msg_type = MessageType.IMAGE
        else:
            text_content = f"[{msgtype} message]"

        # 处理引用消息
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

        # 创建 StreamSimulator
        simulator_id = f"sim_{uuid.uuid4().hex[:12]}"
        simulator = StreamSimulator(chat_id=chatid)
        self._stream_simulators[simulator_id] = simulator
        self._chat_simulator_ids[chatid] = simulator_id

        # 构建入站消息
        inbound = InboundMessage(
            channel="wecom_bot",
            sender_id=userid,
            sender_name="",
            chat_id=chatid,
            chat_type="private" if chattype == "single" else "group",
            message_id=msgid,
            content=text_content.strip(),
            message_type=inbound_msg_type,
            media=media_list,
            content_parts=_content_parts,
            metadata={
                "chattype": chattype,
                "msgtype": msgtype,
                "simulator_id": simulator_id,
            },
        )

        logger.info(
            f"[{self.name}] Message received: type={msgtype}, user={userid}, "
            f"chat={chatid}, simulator_id={simulator_id}"
        )

        await self._handle_inbound_message(inbound)
        return None

    # ============== 消息发送 ==============

    async def _send_message(self, message: OutboundMessage) -> Optional[Any]:
        """发送消息（通用接口，默认走 webhook）

        具体的单聊/群聊路由逻辑在 channel_service 的调度层处理，
        此方法作为通用 fallback 使用 webhook 发送。
        """
        return await self._send_via_webhook(message.content, chatid=message.chat_id)

    async def _send_via_webhook(
        self,
        content: str,
        msgtype: str = "markdown",
        mentioned_list: Optional[List[str]] = None,
        mentioned_mobile_list: Optional[List[str]] = None,
        chatid: Optional[str] = None,
    ) -> Optional[dict]:
        """通过 Webhook 群机器人接口发送消息

        POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY

        优先使用消息回调中携带的 WebhookUrl（按 chatid 查找），
        以确保回复发到正确的群。找不到则回退到配置的 webhook_key。
        当提供 chatid 时，也会将其写入 webhook/send 请求体，
        以支持通过同一个机器人向指定群会话发送消息。

        长度限制 (UTF-8 字节):
        - text: ≤ 2048 字节
        - markdown: ≤ 4096 字节
        - markdown_v2: ≤ 4096 字节（客户端 4.1.36 以下显示纯文本）
        """
        if not self._http_client:
            return None

        # 优先使用回调中的 WebhookUrl（内网地址，可路由到来源群）
        callback_url = self._chat_webhook_urls.get(chatid) if chatid else None
        if callback_url:
            url = callback_url
            logger.info(f"[{self.name}] Sending via callback webhook_url for chatid={chatid}")
        else:
            url = f"{WECOM_WEBHOOK_API}?key={self.config.webhook_key}"
            logger.info(f"[{self.name}] Sending via default webhook (no callback url for chatid={chatid})")

        if msgtype == "text":
            max_bytes = WECOM_BOT_TEXT_MAX_BYTES
            truncated = self._truncate_to_bytes(content, max_bytes)
            text_payload: Dict[str, Any] = {"content": truncated}
            if mentioned_list:
                text_payload["mentioned_list"] = mentioned_list
            if mentioned_mobile_list:
                text_payload["mentioned_mobile_list"] = mentioned_mobile_list
            body: Dict[str, Any] = {"msgtype": "text", "text": text_payload}
        elif msgtype == "markdown_v2":
            max_bytes = WECOM_BOT_MARKDOWN_MAX_BYTES
            truncated = self._truncate_to_bytes(content, max_bytes)
            body = {"msgtype": "markdown_v2", "markdown_v2": {"content": truncated}}
        else:
            # 默认 markdown
            max_bytes = WECOM_BOT_MARKDOWN_MAX_BYTES
            truncated = self._truncate_to_bytes(content, max_bytes)
            body = {"msgtype": "markdown", "markdown": {"content": truncated}}

        if chatid:
            body["chatid"] = chatid


        try:
            resp = await self._http_client.post(
                url,
                json=body,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            errcode = data.get("errcode", 0)
            if errcode == 0:
                logger.debug(f"[{self.name}] Webhook message sent successfully (chatid={chatid})")
                return data
            else:
                logger.error(
                    f"[{self.name}] Webhook send failed: errcode={errcode}, "
                    f"errmsg={data.get('errmsg', '')}"
                )
                return None
        except Exception as e:
            logger.error(f"[{self.name}] Webhook send error: {e}")
            return None

    async def send_stream_content(
        self,
        simulator_id: str,
    ) -> None:
        """模拟流式发送（仅群聊使用）：持续从 StreamSimulator 中取增量内容并发送

        通过 webhook/send 多次发送来模拟流式效果（20 条/分钟，≥3s 间隔）。

        单聊场景不使用此方法——在 _process_wecom_bot_single 中等 AI 完成后
        一次性通过 webhook 发送。

        策略：
        - 按 interval 间隔发送增量 text 消息
        - 最终完成后发送一条完整的 markdown 消息
        - 如果 AI 回复足够快（< interval），跳过中间增量，直接发最终消息
        """
        sim = self._stream_simulators.get(simulator_id)
        if not sim:
            logger.error(f"[{self.name}] StreamSimulator not found: {simulator_id}")
            return

        chunk_size = self.config.stream_chunk_size
        # webhook 限制 20条/分钟，至少 3s 间隔
        interval = max(
            self.config.stream_interval_ms / 1000.0,
            WECOM_WEBHOOK_MIN_INTERVAL,
        )

        chat_id = sim.chat_id
        sent_count = 0

        logger.info(
            f"[{self.name}] Starting stream simulation: "
            f"simulator_id={simulator_id}, chat_id={chat_id}, "
            f"interval={interval}s"
        )

        try:
            while not sim.finished or sim.has_unsent_content:
                await sim.wait_for_content(timeout=interval)

                if not sim.has_unsent_content:
                    if sim.finished:
                        break
                    continue

                # AI 已完成，不再发中间增量——直接跳出循环发最终消息
                if sim.finished:
                    break

                unsent = sim.get_unsent_content()
                if not unsent:
                    continue

                # 发送增量消息
                chunk = unsent[:chunk_size] if len(unsent) > chunk_size else unsent
                await self._send_via_webhook(chunk, msgtype="text", chatid=chat_id)

                sim.mark_sent(sim._last_sent_len + len(chunk))
                sent_count += 1

                # 遵守频率限制：发送后等待
                await asyncio.sleep(interval)

        except Exception as e:
            logger.error(
                f"[{self.name}] Stream simulation error: {e}", exc_info=True
            )
        finally:
            # 发送最终完整消息
            final_content = sim.full_content
            if final_content:
                logger.info(
                    f"[{self.name}] Sending final complete message: "
                    f"{len(final_content)} chars, intermediate_msgs={sent_count}"
                )
                await self._send_via_webhook(final_content, chatid=chat_id)

            self._cleanup_simulator(simulator_id, chat_id)

    def _cleanup_simulator(self, simulator_id: str, chat_id: str) -> None:
        """清理流式模拟器"""
        self._stream_simulators.pop(simulator_id, None)
        if self._chat_simulator_ids.get(chat_id) == simulator_id:
            self._chat_simulator_ids.pop(chat_id, None)

    # ============== 辅助方法 ==============

    def _build_passive_reply(self, text: str, nonce: str) -> Optional[Dict[str, Any]]:
        """构造加密的被动回复消息

        被动回复需要在 HTTP response 中返回加密的 JSON：
        {"encrypt": "...", "msgsignature": "...", "timestamp": ..., "nonce": "..."}

        明文格式: {"msgtype": "text", "text": {"content": "..."}}
        """
        if not self._crypto:
            logger.error(f"[{self.name}] Crypto not initialized, cannot build passive reply")
            return None

        reply_json = json.dumps(
            {"msgtype": "text", "text": {"content": text}},
            ensure_ascii=False,
        )
        try:
            encrypted = self._crypto.encrypt_reply(reply_json, nonce)
            logger.info(f"[{self.name}] Built passive reply: {text[:50]}")
            return encrypted
        except Exception as e:
            logger.error(f"[{self.name}] Failed to build passive reply: {e}")
            return None

    @staticmethod
    def _truncate_to_bytes(text: str, max_bytes: int) -> str:
        """将文本截断到指定的 UTF-8 字节长度，保证不截断多字节字符。

        Args:
            text: 原始文本
            max_bytes: 最大 UTF-8 字节数

        Returns:
            截断后的文本
        """
        encoded = text.encode("utf-8")
        if len(encoded) <= max_bytes:
            return text
        # 二分法找到安全截断位置
        truncated = encoded[:max_bytes]
        # 去掉可能的截断多字节字符（UTF-8 尾部不完整字节）
        return truncated.decode("utf-8", errors="ignore")

    async def send_typing(self, chat_id: str) -> None:
        """企微没有 typing 指示 API"""
        pass

    async def edit_message(self, message_id: str, content: str) -> bool:
        """企微普通机器人不支持编辑已发送消息"""
        logger.debug(
            f"[{self.name}] WeCom Bot does not support message editing"
        )
        return False

    def get_stream_simulator(self, chat_id: str) -> Optional[StreamSimulator]:
        """获取指定会话的活跃流式模拟器"""
        simulator_id = self._chat_simulator_ids.get(chat_id)
        if simulator_id:
            return self._stream_simulators.get(simulator_id)
        return None

    def get_stream_simulator_by_id(
        self, simulator_id: str
    ) -> Optional[StreamSimulator]:
        """通过 simulator_id 获取流式模拟器"""
        return self._stream_simulators.get(simulator_id)

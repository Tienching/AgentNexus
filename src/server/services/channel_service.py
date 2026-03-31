"""Channel 服务 - 集成多平台消息通道

将 channels 模块集成到 virtual-human-sdk 服务中，
实现 Telegram、Slack 等平台的消息接收和 AI 回复。

Supports non-blocking AI processing with real-time progress updates
via the unified notification system.
"""

import ast
import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from ..config import settings
from ..logger import get_logger
from src.channels import (
    ChannelManager,
    InboundMessage,
    TelegramConfig,
    SlackConfig,
    DiscordConfig,
    WhatsAppConfig,
    SignalConfig,
    FeishuConfig,
    WeComConfig,
    WeComBotConfig,
    WeChatConfig,
)
from .notification import (
    NotificationTarget,
    UnifiedNotificationHandler,
    get_notification_handler,
)
from src.runtime.stores.session_storage import get_session_storage
from src.runtime.models.session import (
    SessionMeta, SessionStatus, StoredMessage, MessageStatus,
    StoredToolCall, ToolCallStatus, ContentSegment,
)
from .media_downloader import download_images, download_files

logger = get_logger(__name__)

CHANNEL_MAX_LENGTH = {
    "telegram": 4000,
    "discord": 1900,
    "slack": 3800,
    "feishu": 3800,
    "wecom": 20480,
    "wecom_bot": 20480,
    "whatsapp": 65000,
    "signal": 65000,
    "wechat": 4000,
}

# Progress update interval (seconds) — how often to edit the placeholder message
PROGRESS_UPDATE_INTERVAL = 8

# Type alias for the optional on_text_delta callback
OnTextDelta = Callable[[str], Coroutine[Any, Any, None]]


@dataclass
class ExecutorResult:
    """Unified result from _consume_executor_events()."""
    final_content: str = ""
    is_error: bool = False
    tool_summaries: List[str] = field(default_factory=list)
    tool_call_count: int = 0
    collected_text_parts: List[str] = field(default_factory=list)


# 全局 channel 服务实例
_channel_service: Optional["ChannelService"] = None


class ChannelService:
    """Channel 服务
    
    管理多平台消息通道，将收到的消息转发给 AI 处理，
    并将 AI 回复发送回用户。

    Uses the unified notification system for progress updates and
    completion notifications so users don't stare at a blank screen.
    """
    
    def __init__(self):
        self.manager: Optional[ChannelManager] = None
        self._executor = None  # AI 执行器
        self._active_sessions: Dict[str, Dict[str, Any]] = {}
        self._background_tasks: Dict[str, asyncio.Task] = {}

    def _get_channel_config(self, channel_name: str) -> Optional["ChannelConfig"]:
        """Get the ChannelConfig for a given channel name from the manager."""
        if self.manager and channel_name in self.manager.configs:
            return self.manager.configs[channel_name]
        return None

    def _resolve_exec_user(self, channel_name: str) -> str:
        """Resolve exec_user: channel-level config > global settings."""
        cfg = self._get_channel_config(channel_name)
        if cfg and cfg.exec_user:
            return cfg.exec_user
        return settings.exec_user or "ubuntu"

    def _resolve_effective_exec_user(self, channel_name: str, session_id: Optional[str] = None) -> str:
        """Resolve the effective exec_user, allowing session-level /switch to win."""
        exec_user = self._resolve_exec_user(channel_name)
        if not session_id:
            return exec_user
        try:
            storage = get_session_storage()
            session_exec_user = storage.get_session_exec_user(session_id)
            if session_exec_user:
                return session_exec_user
        except Exception as e:
            logger.warning(f"[{channel_name}] Failed to resolve session exec_user for {session_id}: {e}")
        return exec_user

    async def initialize(self) -> bool:
        """初始化 channel 服务
        
        从 settings 读取配置并初始化各个通道。
        """
        configs = {}
        
        # Telegram 配置
        if settings.telegram_bot_token:
            try:
                allowed_list = [
                    u.strip() 
                    for u in settings.telegram_allowed_users.split(",") 
                    if u.strip()
                ]
                
                configs["telegram"] = TelegramConfig(
                    name="telegram",
                    bot_token=settings.telegram_bot_token,
                    allowed_users=allowed_list,
                    provider=settings.telegram_provider or None,
                    alias=settings.telegram_alias or None,
                    exec_user=settings.telegram_exec_user or None,
                )
                logger.info("Telegram channel configured")
            except Exception as e:
                logger.error(f"Failed to configure Telegram: {e}")
        
        # Slack 配置
        if settings.slack_bot_token and settings.slack_app_token:
            try:
                configs["slack"] = SlackConfig(
                    name="slack",
                    bot_token=settings.slack_bot_token,
                    app_token=settings.slack_app_token,
                    socket_mode=True,
                    provider=settings.slack_provider or None,
                    alias=settings.slack_alias or None,
                    exec_user=settings.slack_exec_user or None,
                )
                logger.info("Slack channel configured")
            except Exception as e:
                logger.error(f"Failed to configure Slack: {e}")
        
        # Discord 配置
        if settings.discord_bot_token:
            try:
                configs["discord"] = DiscordConfig(
                    name="discord",
                    bot_token=settings.discord_bot_token,
                    provider=settings.discord_provider or None,
                    alias=settings.discord_alias or None,
                    exec_user=settings.discord_exec_user or None,
                )
                logger.info("Discord channel configured")
            except Exception as e:
                logger.error(f"Failed to configure Discord: {e}")

        # 飞书 配置
        if settings.feishu_app_id and settings.feishu_app_secret:
            try:
                configs["feishu"] = FeishuConfig(
                    name="feishu",
                    app_id=settings.feishu_app_id,
                    app_secret=settings.feishu_app_secret,
                    verification_token=settings.feishu_verification_token,
                    encrypt_key=settings.feishu_encrypt_key,
                    domain=settings.feishu_domain,
                    provider=settings.feishu_provider or None,
                    alias=settings.feishu_alias or None,
                    exec_user=settings.feishu_exec_user or None,
                )
                logger.info("Feishu channel configured")
            except Exception as e:
                logger.error(f"Failed to configure Feishu: {e}")

        # WhatsApp 配置
        if settings.whatsapp_bridge_url:
            try:
                configs["whatsapp"] = WhatsAppConfig(
                    name="whatsapp",
                    bridge_url=settings.whatsapp_bridge_url,
                    bridge_auth_token=settings.whatsapp_bridge_auth_token,
                    session_name=settings.whatsapp_session_name or "default",
                )
                logger.info("WhatsApp channel configured")
            except Exception as e:
                logger.error(f"Failed to configure WhatsApp: {e}")

        # Signal 配置
        if settings.signal_phone_number:
            try:
                configs["signal"] = SignalConfig(
                    name="signal",
                    api_url=settings.signal_api_url,
                    phone_number=settings.signal_phone_number,
                )
                logger.info("Signal channel configured")
            except Exception as e:
                logger.error(f"Failed to configure Signal: {e}")

        # 企业微信智能机器人配置
        if (
            settings.wecom_mode == "websocket"
            or (settings.wecom_token and settings.wecom_encoding_aes_key)
        ):
            try:
                configs["wecom"] = WeComConfig(
                    name="wecom",
                    mode=settings.wecom_mode,
                    token=settings.wecom_token or "",
                    encoding_aes_key=settings.wecom_encoding_aes_key or "",
                    aibot_id=settings.wecom_aibot_id,
                    bot_id=settings.wecom_ai_bot_id or "",
                    secret=settings.wecom_secret or "",
                    ws_url=settings.wecom_ws_url,
                    heartbeat_interval=settings.wecom_heartbeat_interval,
                    reconnect_max_attempts=settings.wecom_reconnect_max_attempts,
                    reconnect_base_delay=settings.wecom_reconnect_base_delay,
                    reconnect_max_delay=settings.wecom_reconnect_max_delay,
                    ws_stream_interval_ms=settings.wecom_ws_stream_interval_ms,
                    provider=settings.wecom_provider or None,
                    alias=settings.wecom_alias or None,
                    exec_user=settings.wecom_exec_user or None,
                )
                logger.info(f"WeCom AI Bot channel configured ({settings.wecom_mode})")
            except Exception as e:
                logger.error(f"Failed to configure WeCom: {e}")

        # 企业微信普通机器人配置
        if settings.wecom_bot_token and settings.wecom_bot_encoding_aes_key:
            try:
                configs["wecom_bot"] = WeComBotConfig(
                    name="wecom_bot",
                    token=settings.wecom_bot_token,
                    encoding_aes_key=settings.wecom_bot_encoding_aes_key,
                    webhook_key=settings.wecom_bot_webhook_key or "",
                    stream_chunk_size=settings.wecom_bot_stream_chunk_size,
                    stream_interval_ms=settings.wecom_bot_stream_interval_ms,
                    provider=settings.wecom_bot_provider or None,
                    alias=settings.wecom_bot_alias or None,
                    exec_user=settings.wecom_bot_exec_user or None,
                )
                logger.info("WeCom Bot channel configured (webhook)")
            except Exception as e:
                logger.error(f"Failed to configure WeCom Bot: {e}")

        # WeChat 个人号配置
        if settings.wechat_bot_token:
            try:
                configs["wechat"] = WeChatConfig(
                    name="wechat",
                    bot_token=settings.wechat_bot_token,
                    base_url=settings.wechat_base_url,
                    poll_timeout_ms=settings.wechat_poll_timeout_ms,
                    api_timeout_ms=settings.wechat_api_timeout_ms,
                    provider=settings.wechat_provider or None,
                    alias=settings.wechat_alias or None,
                    exec_user=settings.wechat_exec_user or None,
                )
                logger.info("WeChat channel configured")
            except Exception as e:
                logger.error(f"Failed to configure WeChat: {e}")

        if not configs:
            logger.info("No channel configured, channel service disabled")
            return False
        
        # 创建管理器
        self.manager = ChannelManager(configs)
        self.manager.on_message = self._handle_message
        self.manager.on_error = self._handle_error
        
        return True
    
    async def start(self) -> None:
        """启动所有通道"""
        if not self.manager:
            return
            
        await self.manager.initialize()
        await self.manager.start()
        logger.info(f"Channel service started with {len(self.manager.channels)} channel(s)")
    
    async def stop(self) -> None:
        """停止所有通道"""
        # Cancel background processing tasks
        for key, task in list(self._background_tasks.items()):
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(
                *self._background_tasks.values(), return_exceptions=True
            )
            self._background_tasks.clear()

        if self.manager:
            await self.manager.stop()
            logger.info("Channel service stopped")

    # ------------------------------------------------------------------
    # Shared helpers — build request & consume executor events
    # ------------------------------------------------------------------

    @staticmethod
    def _get_wecom_bot_followup_instruction() -> str:
        """Return a prompt prefix describing WeCom Bot interaction limits."""
        return (
            "[渠道限制]\n"
            "当前渠道是企业微信普通机器人。不要调用 `ask_followup_question` / `AskUserQuestion`，"
            "也不要依赖按钮、卡片或表单回传选择结果。"
            "如果需要用户确认，请直接用自然语言提问，把选项写成“1. ... / 2. ...”这样的编号列表，"
            "并在本轮结束后等待用户下一条消息。"
        )

    @staticmethod
    def _resolve_cli_timeout(channel: str) -> int:
        """Resolve per-channel CLI timeout with channel-specific override."""
        base_timeout = int(settings.cli_timeout or 600)
        if channel == "wecom":
            wecom_timeout = int(getattr(settings, "wecom_cli_timeout", 0) or 0)
            if wecom_timeout > 0:
                return max(base_timeout, wecom_timeout)
        if channel == "wecom_bot":
            wecom_bot_timeout = int(getattr(settings, "wecom_bot_cli_timeout", 0) or 0)
            if wecom_bot_timeout > 0:
                return max(base_timeout, wecom_bot_timeout)
        return base_timeout

    async def _build_request(
        self,
        message: InboundMessage,
        session_id: str,
    ):
        """Build a RequestModel from an InboundMessage (shared across all channels).

        Handles: image/file download, model/provider overrides, model_changed detection.
        """
        from ..services import CLIExecutor  # noqa: F811
        from ..models import RequestModel

        exec_user = self._resolve_effective_exec_user(message.channel, session_id)
        session_dir = Path(settings.user_home_base) / exec_user / ".nexus" / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Download media
        image_paths: list[str] = []
        file_paths: list[str] = []
        _decrypt_fn = None
        if message.channel == "wecom" and self.manager:
            _ch = self.manager.get_channel("wecom")
            _crypto = getattr(_ch, "_crypto", None) if _ch else None
            _decrypt_fn = _crypto.decrypt_file if _crypto else None
        elif message.channel == "wecom_bot" and self.manager:
            _ch = self.manager.get_channel("wecom_bot")
            _crypto = getattr(_ch, "_crypto", None) if _ch else None
            _decrypt_fn = _crypto.decrypt_file if _crypto else None
        if message.media:
            image_items = [
                {"url": m.url, "mime_type": m.mime_type}
                for m in message.media
                if m.url and (not m.mime_type or "image" in (m.mime_type or ""))
            ]
            file_items = [
                {"url": m.url, "file_name": m.file_name}
                for m in message.media
                if m.url and m.mime_type and "image" not in (m.mime_type or "")
            ]
            if image_items:
                try:
                    image_paths = await download_images(image_items, dest_dir=str(session_dir), session_id=session_id, decrypt_fn=_decrypt_fn)
                    if image_paths:
                        logger.info(f"[{message.channel}] Downloaded {len(image_paths)} image(s)", extra={"session_id": session_id})
                except Exception as e:
                    logger.warning(f"[{message.channel}] Failed to download images: {e}")
            if file_items:
                try:
                    file_paths = await download_files(file_items, dest_dir=str(session_dir), session_id=session_id, decrypt_fn=_decrypt_fn)
                    if file_paths:
                        logger.info(f"[{message.channel}] Downloaded {len(file_paths)} file(s)", extra={"session_id": session_id})
                except Exception as e:
                    logger.warning(f"[{message.channel}] Failed to download files: {e}")

        # Build content_parts with local paths replacing URLs
        content_parts: list[dict] = []
        if getattr(message, "content_parts", None):
            # Build URL -> local path mapping
            _url_to_path: dict[str, str] = {}
            img_urls = [m.url for m in message.media if m.url and (not m.mime_type or "image" in (m.mime_type or ""))]
            for url, path in zip(img_urls, image_paths):
                _url_to_path[url] = path
            for part in message.content_parts:
                if part.get("type") == "image" and part.get("url") in _url_to_path:
                    content_parts.append({"type": "image", "path": _url_to_path[part["url"]]})
                elif part.get("type") == "text":
                    content_parts.append({"type": "text", "content": part.get("content", "")})
                else:
                    content_parts.append(part)

        content = message.content
        if not content.strip() and image_paths:
            content = ""

        if message.channel == "wecom_bot" and not content.lstrip().startswith("/"):
            user_prompt = content.strip() or "（用户未附带文字，请结合图片或附件理解需求。）"
            content = (
                f"{self._get_wecom_bot_followup_instruction()}\n\n"
                f"用户消息：\n{user_prompt}"
            )

        request = RequestModel(
            content=content,
            user=f"{message.channel}_{message.sender_id}",
            session_id=session_id,
            msg_id=f"msg-{uuid.uuid4().hex[:8]}",
            image_paths=image_paths,
            file_paths=file_paths,
            content_parts=content_parts if content_parts else None,
        )

        # Apply model / provider overrides
        # Priority: session-level /switch > channel-level config > global defaults
        try:
            storage = get_session_storage()
            model_override = storage.get_model_override(session_id)
            if model_override:
                request.model = model_override
                active_model = storage.get_active_model(session_id)
                if active_model != model_override:
                    request.model_changed = True
                    logger.info(
                        f"[{message.channel}] Model changed: {active_model} -> {model_override}",
                        extra={"session_id": session_id},
                    )
                else:
                    logger.info(
                        f"[{message.channel}] Model override applied: {model_override}",
                        extra={"session_id": session_id},
                    )
            handoff_prov = storage.get_handoff_provider(session_id)
            if handoff_prov:
                hp_provider, hp_alias = handoff_prov
                request.provider = hp_provider
                request.alias = hp_alias
                logger.info(
                    f"[{message.channel}] Provider override (session): provider={hp_provider}, alias={hp_alias}",
                    extra={"session_id": session_id},
                )
            else:
                # No session-level override — apply channel-level config if present
                ch_cfg = self._get_channel_config(message.channel)
                if ch_cfg:
                    if ch_cfg.provider:
                        request.provider = ch_cfg.provider
                    if ch_cfg.alias:
                        request.alias = ch_cfg.alias
                    if ch_cfg.provider or ch_cfg.alias:
                        logger.info(
                            f"[{message.channel}] Provider override (channel): provider={ch_cfg.provider}, alias={ch_cfg.alias}",
                            extra={"session_id": session_id},
                        )
        except Exception as e:
            logger.warning(f"[{message.channel}] Failed to read session overrides: {e}")

        return request

    def _archive_user_message(
        self,
        message: InboundMessage,
        session_id: str,
        request,
    ) -> None:
        """Immediately persist the user message to Redis so it shows up in the
        Nexus UI as soon as the session enters RUNNING state — before the AI
        starts responding.
        """
        try:
            storage = get_session_storage()

            # Build user message content with embedded image/file paths
            req_content_parts = getattr(request, "content_parts", None) or []
            if req_content_parts:
                assembled: list[str] = []
                for part in req_content_parts:
                    if part.get("type") == "image":
                        p = part.get("path") or part.get("url", "")
                        assembled.append(f"{{image: {p}}}")
                    elif part.get("type") == "text":
                        assembled.append(part.get("content", ""))
                    elif part.get("type") == "file":
                        p = part.get("path") or part.get("url", "")
                        assembled.append(f"{{file: {p}}}")
                user_content = "\n".join(assembled)
            else:
                user_content = message.content or ""
                image_paths = getattr(request, "image_paths", None) or []
                file_paths = getattr(request, "file_paths", None) or []

                parts: list[str] = []
                for p in image_paths:
                    parts.append(f"{{image: {p}}}")
                for p in file_paths:
                    parts.append(f"{{file: {p}}}")

                # Fallback: when media download fails, keep original media URL tags
                # so Nexus still renders placeholders like {image: ...}.
                if not parts and getattr(message, "media", None):
                    for m in message.media:
                        if not getattr(m, "url", None):
                            continue
                        mime = (getattr(m, "mime_type", "") or "").lower()
                        if (not mime) or ("image" in mime):
                            parts.append(f"{{image: {m.url}}}")
                        else:
                            parts.append(f"{{file: {m.url}}}")

                if parts:
                    media_tags = " ".join(parts)
                    if user_content.strip():
                        user_content = f"{media_tags}\n\n{user_content}"
                    else:
                        user_content = media_tags

            storage.add_session_message(
                session_id,
                StoredMessage(
                    id=f"ch-u-{uuid.uuid4().hex[:8]}",
                    role="user",
                    content=user_content,
                    status=MessageStatus.COMPLETE,
                ),
            )
        except Exception as e:
            logger.warning(f"[{message.channel}] Failed to archive user message: {e}")

    async def _consume_executor_events(
        self,
        message: InboundMessage,
        session_id: str,
        request,
        *,
        on_text_delta: Optional[OnTextDelta] = None,
        on_tool_start: Optional[Callable[[str, str], Coroutine[Any, Any, None]]] = None,
        on_tool_display_update: Optional[Callable[[str, str], Coroutine[Any, Any, None]]] = None,
        on_tool_summary: Optional[Callable[[str, str], Coroutine[Any, Any, None]]] = None,
    ) -> ExecutorResult:
        """Consume raw executor events — **single source of truth** for all channels.

        Responsibilities:
        1. Drive ``executor.execute()`` iteration
        2. Parse stream_event / assistant / result event types
        3. Track tool calls (AG-UI + legacy)
        4. Deduplicate text (has_streamed_text flag)
        5. Archive assistant message to Redis on ``result``
           (user message is persisted earlier by ``_archive_user_message``)
        6. Emit real-time AGUI events to Redis so the SSE endpoint can
           stream them to the Nexus frontend (TEXT_MESSAGE_*, TOOL_CALL_*, etc.)

        Channel-specific behaviour is injected via callbacks:
        - *on_text_delta(text)*: called for each incremental text chunk (wecom writes to StreamBuffer)
        - *on_tool_start(tool_id, tool_name)*: called when a tool call starts (for real-time progress)
        - *on_tool_display_update(tool_id, display)*: called when tool args arrive and a richer
          display name can be generated (e.g. ``Grep: /path`` instead of ``Grep: 搜索内容``)
        - *on_tool_summary(tool_id, summary)*: called when a tool call is finalised (wecom appends to StreamBuffer)
        """
        from ..services import CLIExecutor

        executor = CLIExecutor(config=settings)
        exec_user = self._resolve_effective_exec_user(message.channel, session_id)
        timeout = self._resolve_cli_timeout(message.channel)

        result = ExecutorResult()
        tool_block_buffer: Dict[int, Dict[str, str]] = {}
        agui_tool_buffer: Dict[str, Dict[str, str]] = {}
        has_streamed_text = False
        _tool_display_updated: set = set()  # tool_ids that already got a display update
        _tool_id_to_name: Dict[str, str] = {}  # tool_id -> raw tool_name (for subagent detection)

        # AGUI archival state — tracks content_segments and tool_calls for
        # faithful reproduction of the assistant response in the Nexus UI.
        _content_segments: List[ContentSegment] = []
        _tool_calls: List[StoredToolCall] = []
        _tool_call_ids: List[str] = []
        _segment_seq = 0
        _last_text_snapshot = ""  # text length at which we last emitted a text segment

        # --- Real-time AGUI event emitting for SSE streaming ---
        _agui_storage = get_session_storage()
        _agui_msg_id = f"ch-stream-{uuid.uuid4().hex[:8]}"
        _agui_text_started = False  # Whether we've emitted TEXT_MESSAGE_START

        def _emit_agui(evt: dict) -> None:
            """Append an AGUI event to Redis for the SSE endpoint to pick up."""
            try:
                _agui_storage.append_agui_event(session_id, evt)
            except Exception:
                pass

        async def _handle_tool_start(tool_id: str, tool_name: str) -> None:
            """Shared logic when a tool call begins (AG-UI or legacy).

            Closes any open text segment, emits TOOL_CALL_START, flushes
            preceding text as a content segment, and records the tool_call
            segment for archival.
            """
            nonlocal _agui_text_started, _segment_seq, _last_text_snapshot

            result.tool_call_count += 1
            _tool_id_to_name[tool_id] = tool_name

            # End any open text segment before tool call
            if _agui_text_started:
                _emit_agui({"type": "TEXT_MESSAGE_END", "messageId": _agui_msg_id})
                _agui_text_started = False

            _emit_agui({"type": "TOOL_CALL_START", "toolCallId": tool_id, "toolCallName": tool_name})

            # Notify channel that a tool call is starting (real-time progress)
            if on_tool_start:
                await on_tool_start(tool_id, tool_name)

            # Flush preceding text as a content segment
            current_text = "".join(result.collected_text_parts)
            new_text = current_text[len(_last_text_snapshot):]
            if new_text.strip():
                _content_segments.append(ContentSegment(type="text", content=new_text, sequence=_segment_seq))
                _segment_seq += 1
            _last_text_snapshot = current_text

            # Add tool_call segment
            _content_segments.append(ContentSegment(type="tool_call", tool_call_id=tool_id, sequence=_segment_seq))
            _segment_seq += 1
            _tool_call_ids.append(tool_id)

        async def _try_update_tool_display(tool_id: str, tool_name: str, accumulated_args: str) -> None:
            """Try to parse accumulated args and generate a richer display name.

            Called each time a TOOL_CALL_ARGS delta arrives.  Fires
            ``on_tool_display_update`` at most once per tool_id — only when
            the parsed args yield a display name different from the
            parameter-less fallback.

            Handles the case where *tool_name* was already formatted by the
            adapter (e.g. ``"Read: 读取文件"``).  In that scenario we strip the
            prefix, resolve the raw tool key, and re-derive the display name
            with the newly-arrived params.
            """
            if tool_id in _tool_display_updated:
                return
            params = self._parse_tool_params(accumulated_args)
            if not params:
                return

            # If the adapter already formatted tool_name (contains ": "),
            # _get_tool_display_name would short-circuit and return it as-is.
            # We need to recover the raw tool key so params can take effect.
            raw_tool_name = tool_name
            if ": " in tool_name:
                raw_tool_name = self._resolve_raw_tool_key(tool_name)

            new_display = self._get_tool_display_name(raw_tool_name, params)
            fallback_display = self._get_tool_display_name(raw_tool_name, {})
            if new_display and new_display != fallback_display:
                _tool_display_updated.add(tool_id)
                if on_tool_display_update:
                    await on_tool_display_update(tool_id, new_display)

        async def _handle_tool_end(
            tool_id: str,
            tool_name: str,
            args_string: str,
            tc_result: Any = None,
        ) -> None:
            """Shared logic when a tool call completes (AG-UI or legacy).

            Parses args JSON, builds display name / summary, creates a
            StoredToolCall, and emits the AGUI TOOL_CALL_END event.
            """
            params_obj = self._parse_tool_params(args_string)

            # Recover raw tool key if the adapter already formatted tool_name
            # (e.g. "Glob: 搜索文件" → "search_file"), so params can take effect.
            raw_name = tool_name
            if ": " in tool_name:
                raw_name = self._resolve_raw_tool_key(tool_name)
            display = self._get_tool_display_name(raw_name, params_obj)
            summary = self._format_tool_summary(message.channel, display)
            result.tool_summaries.append(summary)
            if on_tool_summary:
                await on_tool_summary(tool_id, summary)

            _tool_calls.append(StoredToolCall(
                id=tool_id,
                tool_name=tool_name,
                args=params_obj,
                args_string=args_string,
                status=ToolCallStatus.COMPLETED,
                result=tc_result,
                end_time=int(time.time() * 1000),
            ))

            _emit_agui({
                "type": "TOOL_CALL_END",
                "toolCallId": tool_id,
                "result": tc_result,
                "toolCallDisplayName": display,
            })

        async def _process_stream():
            nonlocal has_streamed_text, _agui_text_started
            async for output in executor.execute(request, exec_user=exec_user, output_format="raw"):
                if not output:
                    continue
                try:
                    data = json.loads(output)
                    if not isinstance(data, dict):
                        continue
                except json.JSONDecodeError:
                    continue

                event_type = data.get("type", "")

                # --- stream_event ---
                if event_type == "stream_event":
                    event = data.get("event", {})
                    evt_type = event.get("type", "")

                    if evt_type == "content_block_delta":
                        delta = event.get("delta", {})
                        delta_type = delta.get("type", "")
                        if delta_type == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                result.collected_text_parts.append(text)
                                has_streamed_text = True
                                if not _agui_text_started:
                                    _emit_agui({"type": "TEXT_MESSAGE_START", "messageId": _agui_msg_id, "role": "assistant"})
                                    _agui_text_started = True
                                _emit_agui({"type": "TEXT_MESSAGE_CONTENT", "messageId": _agui_msg_id, "delta": text})
                                if on_text_delta:
                                    await on_text_delta(text)
                        elif delta_type == "input_json_delta":
                            index = event.get("index", 0)
                            partial = delta.get("partial_json", "")
                            if partial and index in tool_block_buffer:
                                tool_block_buffer[index]["json_buf"] += partial
                                tool_id = tool_block_buffer[index].get("id")
                                if tool_id:
                                    _emit_agui({"type": "TOOL_CALL_ARGS", "toolCallId": tool_id, "delta": partial})
                                    await _try_update_tool_display(
                                        tool_id,
                                        tool_block_buffer[index].get("name", "unknown"),
                                        tool_block_buffer[index]["json_buf"],
                                    )

                    # AG-UI tool tracking
                    elif evt_type == "TOOL_CALL_START":
                        tool_name = event.get("toolCallName", "unknown")
                        tool_id = event.get("toolCallId", "")
                        if tool_id:
                            agui_tool_buffer[tool_id] = {"name": tool_name, "args": ""}
                            await _handle_tool_start(tool_id, tool_name)

                    elif evt_type == "TOOL_CALL_ARGS":
                        tool_id = event.get("toolCallId", "")
                        delta_str = event.get("delta", "")
                        if tool_id and delta_str and tool_id in agui_tool_buffer:
                            agui_tool_buffer[tool_id]["args"] += delta_str
                            _emit_agui({"type": "TOOL_CALL_ARGS", "toolCallId": tool_id, "delta": delta_str})
                            await _try_update_tool_display(
                                tool_id,
                                agui_tool_buffer[tool_id]["name"],
                                agui_tool_buffer[tool_id]["args"],
                            )

                    elif evt_type in ("TOOL_CALL_END", "TOOL_CALL_RESULT"):
                        tool_id = event.get("toolCallId", "")
                        if tool_id and tool_id in agui_tool_buffer:
                            entry = agui_tool_buffer.pop(tool_id)
                            tc_result = event.get("result") if evt_type == "TOOL_CALL_END" else event.get("content")
                            await _handle_tool_end(tool_id, entry["name"], entry["args"], tc_result)

                    # Legacy tool blocks
                    elif evt_type == "content_block_start":
                        content_block = event.get("content_block", {})
                        if content_block.get("type") == "tool_use":
                            tool_name = content_block.get("name", "unknown")
                            tool_id = content_block.get("id", f"tool-{uuid.uuid4().hex[:8]}")
                            index = event.get("index", 0)
                            tool_block_buffer[index] = {"name": tool_name, "json_buf": "", "id": tool_id}
                            await _handle_tool_start(tool_id, tool_name)

                    elif evt_type == "content_block_stop":
                        index = event.get("index", 0)
                        if index in tool_block_buffer:
                            entry = tool_block_buffer.pop(index)
                            await _handle_tool_end(entry["id"], entry["name"], entry["json_buf"])

                # --- assistant event (skip if already streamed) ---
                elif event_type == "assistant":
                    if not has_streamed_text:
                        msg = data.get("message", {})
                        msg_content = msg.get("content", [])
                        if isinstance(msg_content, list):
                            for item in msg_content:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    text = item.get("text", "")
                                    if text:
                                        result.collected_text_parts.append(text)
                                        if not _agui_text_started:
                                            _emit_agui({"type": "TEXT_MESSAGE_START", "messageId": _agui_msg_id, "role": "assistant"})
                                            _agui_text_started = True
                                        _emit_agui({"type": "TEXT_MESSAGE_CONTENT", "messageId": _agui_msg_id, "delta": text})
                                        if on_text_delta:
                                            await on_text_delta(text)

                # --- user event (tool_result may embed nested subagent tool calls) ---
                elif event_type == "user":
                    user_message = data.get("message", {})
                    user_content = user_message.get("content", [])
                    if isinstance(user_content, list):
                        for item in user_content:
                            if not isinstance(item, dict) or item.get("type") != "tool_result":
                                continue

                            parent_tool_use_id = item.get("tool_use_id", "")
                            raw_result = self._extract_tool_result_text(item.get("content"))
                            nested_calls = self._parse_subagent_tool_calls(raw_result)
                            for nested in nested_calls:
                                tool_id = nested["tool_id"]
                                tool_name = nested["tool_name"]
                                args_obj = nested.get("arguments") or {}
                                args_str = json.dumps(args_obj, ensure_ascii=False) if args_obj else ""
                                await _handle_tool_start(tool_id, tool_name)
                                if args_str:
                                    _emit_agui({"type": "TOOL_CALL_ARGS", "toolCallId": tool_id, "delta": args_str})
                                await _handle_tool_end(tool_id, tool_name, args_str)

                            # If the tool_result belongs to a "task" (subagent),
                            # extract the text content (excluding <tool_call> blocks)
                            # and emit it so channels can display the subagent analysis.
                            parent_tool_name = _tool_id_to_name.get(parent_tool_use_id, "")
                            parent_tool_key = parent_tool_name.strip().lower()
                            # Also handle formatted names like "Task: analyst - ..."
                            is_task_tool = parent_tool_key == "task" or parent_tool_key.startswith("task:")
                            if is_task_tool and raw_result:
                                # Strip <tool_call>...</tool_call> blocks to get pure text
                                subagent_text = re.sub(
                                    r'<tool_call>.*?</tool_call>', '', raw_result, flags=re.DOTALL
                                ).strip()
                                if subagent_text:
                                    # Truncate overly long subagent output
                                    max_subagent_len = CHANNEL_MAX_LENGTH.get(message.channel, 4000)
                                    if len(subagent_text) > max_subagent_len:
                                        subagent_text = subagent_text[:max_subagent_len] + "\n\n... (子任务输出被截断)"
                                    result.collected_text_parts.append(subagent_text)
                                    has_streamed_text = True
                                    if not _agui_text_started:
                                        _emit_agui({"type": "TEXT_MESSAGE_START", "messageId": _agui_msg_id, "role": "assistant"})
                                        _agui_text_started = True
                                    _emit_agui({"type": "TEXT_MESSAGE_CONTENT", "messageId": _agui_msg_id, "delta": subagent_text})
                                    if on_text_delta:
                                        await on_text_delta(subagent_text)
                                    logger.debug(
                                        f"[{message.channel}] Emitted subagent text content "
                                        f"({len(subagent_text)} chars) from tool {parent_tool_use_id}"
                                    )

                # --- result event ---
                elif event_type == "result":
                    is_error = data.get("is_error", False)
                    content = data.get("content", "") or data.get("result", "")
                    if not content and is_error:
                        errors = data.get("errors", [])
                        if errors:
                            content = "❌ " + "; ".join(str(e) for e in errors[:3])
                    result.final_content = content or ""
                    result.is_error = is_error
                    return  # result is terminal

        try:
            await asyncio.wait_for(_process_stream(), timeout=timeout)
        except TimeoutError:
            logger.error(f"[{message.channel}] AI execution timed out after {timeout}s")
            executor.kill_process()
            result.is_error = True
            result.final_content = ""
        except Exception as e:
            logger.error(f"[{message.channel}] AI processing error: {e}", exc_info=True)
            result.is_error = True
            result.final_content = f"❌ 处理出错：{str(e)[:200]}"

        # --- Close any open AGUI text segment and emit RUN_FINISHED ---
        if _agui_text_started:
            _emit_agui({"type": "TEXT_MESSAGE_END", "messageId": _agui_msg_id})
        _emit_agui({"type": "RUN_FINISHED", "threadId": session_id})

        # --- Set session status to COMPLETED ---
        try:
            _agui_storage.update_session_status(
                session_id,
                SessionStatus.ERROR if result.is_error else SessionStatus.COMPLETED,
            )
        except Exception as e:
            logger.warning(f"[{message.channel}] Failed to set session completed: {e}")

        # --- Archive assistant message to Redis (AGUI format) ---
        # (User message is already persisted by _archive_user_message before
        #  _consume_executor_events is called.)
        final = result.final_content or "".join(result.collected_text_parts).strip()
        if final:
            try:
                storage = get_session_storage()

                # Flush any remaining text after the last tool call as a final segment
                current_text = "".join(result.collected_text_parts)
                remaining = current_text[len(_last_text_snapshot):]
                if remaining.strip():
                    _content_segments.append(ContentSegment(type="text", content=remaining, sequence=_segment_seq))
                # If no segments were built but we have content, create a single text segment
                if not _content_segments and final:
                    _content_segments.append(ContentSegment(type="text", content=final, sequence=0))

                assistant_msg_id = f"ch-a-{uuid.uuid4().hex[:8]}"
                storage.add_session_message(
                    session_id,
                    StoredMessage(
                        id=assistant_msg_id,
                        role="assistant",
                        content=final,
                        status=MessageStatus.COMPLETE,
                        tool_call_ids=_tool_call_ids if _tool_call_ids else None,
                        content_segments=_content_segments if _content_segments else None,
                    ),
                )

                # Persist tool calls to Redis
                for tc in _tool_calls:
                    tc.parent_message_id = assistant_msg_id
                    storage.save_tool_call(session_id, tc)

            except Exception as e:
                logger.warning(f"[{message.channel}] Failed to archive messages: {e}")

        return result

    async def _handle_message(self, message: InboundMessage) -> None:
        """处理收到的消息（非阻塞模式）

        1. 立即发送 "⏳ 正在处理…" 占位消息（非企微通道）
        2. 后台异步执行 AI 处理
        3. 定期更新占位消息显示进度
        4. 完成后编辑占位消息（短回复）或发送新消息（长回复）

        企微通道使用流式被动回复，AI 增量内容写入 StreamBuffer，
        由企微流式刷新回调取走。
        """
        logger.info(f"[{message.channel}] Message from {message.sender_id}: {message.content[:100]}")

        from ..utils.ids import gen_channel_session_id
        session_id = gen_channel_session_id(message.channel, message.chat_id)

        # Ensure session meta exists in Redis (so it shows up in Runtime list)
        # Always set status to RUNNING so the frontend can detect new activity
        exec_user = self._resolve_effective_exec_user(message.channel, session_id)
        try:
            storage = get_session_storage()
            existing_meta = storage.get_session_meta(session_id)
            session_dir = Path(settings.user_home_base) / exec_user / ".nexus" / "sessions" / session_id
            if not existing_meta or not existing_meta.id:
                title = (message.content or "")[:50]
                if len(message.content or "") > 50:
                    title += "..."
                title = title or f"Channel: {message.channel}"
                meta = SessionMeta(
                    id=session_id,
                    thread_id=session_id,
                    title=title,
                    username=exec_user,
                    exec_user=exec_user,
                    status=SessionStatus.RUNNING,
                    exec_dir=str(session_dir),
                )
                storage.save_session_meta(meta)
                logger.info(f"[{message.channel}] Created session meta: {session_id}")
            else:
                meta_changed = False
                previous_exec_user = (
                    (existing_meta.exec_user or existing_meta.username or "").strip()
                )
                existing_exec_dir = (existing_meta.exec_dir or "").strip()
                if (existing_meta.username or "").strip() != exec_user:
                    existing_meta.username = exec_user
                    meta_changed = True
                if (existing_meta.exec_user or "").strip() != exec_user:
                    existing_meta.exec_user = exec_user
                    meta_changed = True

                should_update_exec_dir = not existing_exec_dir
                if not should_update_exec_dir and previous_exec_user:
                    previous_default_dir = (
                        Path(settings.user_home_base)
                        / previous_exec_user
                        / ".nexus"
                        / "sessions"
                        / session_id
                    )
                    should_update_exec_dir = existing_exec_dir == str(previous_default_dir)
                if should_update_exec_dir and existing_exec_dir != str(session_dir):
                    existing_meta.exec_dir = str(session_dir)
                    meta_changed = True

                if meta_changed:
                    storage.save_session_meta(existing_meta)
                # Session already exists — update status to RUNNING so the
                # frontend picks up the new activity (shows running indicator,
                # connects SSE stream, etc.)
                storage.update_session_status(session_id, SessionStatus.RUNNING)
                logger.info(f"[{message.channel}] Updated existing session to running: {session_id}")

            # CRITICAL: Write RUN_STARTED event IMMEDIATELY after setting status
            # to RUNNING.  Channel messages use _consume_executor_events() which
            # bypasses the archiver/orchestrator, so no RUN_STARTED event is
            # emitted automatically.  Without this, the SSE self-heal logic sees
            # the previous run's RUN_FINISHED without a matching RUN_STARTED and
            # incorrectly resets the status back to completed.
            storage.append_agui_event(session_id, {
                "type": "RUN_STARTED",
                "threadId": session_id,
            })
        except Exception as e:
            logger.warning(f"[{message.channel}] Failed to init session meta: {e}")

        handler = get_notification_handler()
        target = handler.build_target_from_channel(
            channel_name=message.channel,
            chat_id=message.chat_id,
        )

        # 企微智能机器人通道：Webhook 模式走被动流式，WebSocket 模式走原生长连接流式
        if message.channel == "wecom":
            if message.metadata.get("ws_mode"):
                req_id = message.metadata.get("req_id", "")
                task = asyncio.create_task(
                    self._process_wecom_ws_stream(message, session_id, req_id)
                )
            else:
                stream_id = message.metadata.get("stream_id", "")
                task = asyncio.create_task(
                    self._process_wecom_stream(message, session_id, stream_id)
                )
        elif message.channel == "wecom_bot":
            # 企微普通机器人通道：按 chattype 区分单聊/群聊
            simulator_id = message.metadata.get("simulator_id", "")
            if message.chat_type == "group":
                # 群聊：先发进度提示，再按语义事件分段发送
                await handler.notify_progress(target, "正在处理，请稍候…")
                task = asyncio.create_task(
                    self._process_wecom_bot_event_based(message, session_id, simulator_id)
                )
            else:
                # 单聊：等 AI 完成后一次性发送完整回复
                task = asyncio.create_task(
                    self._process_wecom_bot_single(message, session_id, simulator_id)
                )
        else:
            # 其他通道：发进度占位消息
            progress_result = await handler.notify_progress(
                target, "⏳ 正在处理，请稍候…"
            )
            if progress_result.success and progress_result.message_id:
                target.message_id = progress_result.message_id

            task = asyncio.create_task(
                self._process_and_notify(message, session_id, target, handler)
            )

        task_key = f"{message.channel}_{message.chat_id}_{message.internal_id}"
        self._background_tasks[task_key] = task

        def _cleanup(t: asyncio.Task, key: str = task_key):
            self._background_tasks.pop(key, None)
        task.add_done_callback(_cleanup)

    async def _process_wecom_ws_stream(
        self,
        message: InboundMessage,
        session_id: str,
        req_id: str,
    ) -> None:
        """企微智能机器人 WebSocket 模式：直接通过长连接推送原生流式消息。"""
        channel = self.manager.get_channel("wecom") if self.manager else None
        if not channel:
            logger.error("[wecom] Channel not found for websocket stream processing")
            return

        if not req_id:
            logger.error("[wecom] Missing req_id for websocket response")
            return

        request = await self._build_request(message, session_id)
        # Inject unified notification target for WS-mode slash commands (e.g. /task, /chat -c).
        # When a slash command creates or re-enqueues a task, the executor reads these
        # fields and stores them on the Task so that task_notifier can deliver the result
        # via WeComSink.send_text() → channel.send_ws_msg() when the task completes.
        if request is not None:
            try:
                request.notification_sink_type = "wecom"
                request.notification_channel = "wecom"
                request.notification_chat_id = message.chat_id
            except (AttributeError, TypeError):
                pass  # Non-receptive request object (e.g. mock/stub in tests)
        self._archive_user_message(message, session_id, request)

        from dataclasses import dataclass

        @dataclass
        class _WsState:
            stream_id: str
            segment_content: str = ""
            last_sent: float = 0.0
            first_push_at: "Optional[float]" = None
            active_send_mode: bool = False
            active_send_reason: str = ""
            active_send_started_at: "Optional[float]" = None
            current_stream_closed: bool = False
            final_active_sent: bool = False
            delivered_content: str = ""

        state = _WsState(stream_id=f"ws_stream_{uuid.uuid4().hex[:12]}")
        ws_interval = max(
            getattr(channel.config, "ws_stream_interval_ms", 500) / 1000.0,
            0.2,
        )
        soft_limit = max(int(getattr(channel.config, "ws_stream_soft_limit_seconds", 330) or 330), 30)
        hard_limit = max(int(getattr(channel.config, "ws_stream_hard_limit_seconds", 350) or 350), soft_limit + 5)
        rollover_notice = "⏭️ 长内容自动分段：接下文..."
        active_send_notice = "⏭️ 长回复处理中，完成后将主动发送后续结果。"
        active_chat_type = (message.metadata or {}).get("chattype") or message.chat_type or None

        # Track in-progress tool start placeholders so the summary can replace them
        _ws_tool_placeholders: Dict[str, str] = {}  # tool_id -> placeholder text
        final_output_content = ""

        def _segment_payload(content: str) -> str:
            return self._truncate_response(content, "wecom") if content else ""

        def _stream_elapsed() -> float:
            if state.first_push_at is None:
                return 0.0
            return max(time.time() - state.first_push_at, 0.0)

        def _can_rollover_now() -> bool:
            return bool(state.segment_content) and not _ws_tool_placeholders

        def _remember_delivered_content(content: str) -> None:
            if not content:
                return

            normalized = content
            for placeholder in _ws_tool_placeholders.values():
                normalized = normalized.replace(f"\n\n{placeholder}\n\n", "\n\n")
                normalized = normalized.replace(placeholder, "")
            normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
            if normalized:
                state.delivered_content += normalized

        def _build_active_send_payload(content: str) -> str:
            normalized = _segment_payload(content)
            if not normalized:
                return ""

            delivered = state.delivered_content
            if delivered and normalized.startswith(delivered):
                remaining = normalized[len(delivered):].lstrip()
                if remaining:
                    return remaining

            return normalized

        async def _send_active_message(content: str) -> bool:
            if not content:
                return False

            sender = getattr(channel, "send_ws_active_message", None)
            if callable(sender):
                return await sender(
                    message.chat_id,
                    content,
                    msgtype="markdown",
                    chat_type=active_chat_type,
                )

            return await channel.send_ws_msg(
                message.chat_id,
                content,
                msgtype="markdown",
                chat_type=active_chat_type,
            )

        async def _close_current_stream(*, notice: str = "") -> None:
            if state.current_stream_closed:
                return

            payload_source = state.segment_content
            if state.segment_content:
                _remember_delivered_content(state.segment_content)
            if notice:
                payload_source = f"{payload_source}\n\n{notice}".strip() if payload_source else notice
            payload = _segment_payload(payload_source)
            if payload:
                await channel.send_ws_stream_finish(req_id, state.stream_id, payload)

            # Flush completely, so the next stage starts cleanly.
            state.segment_content = ""
            state.last_sent = 0.0
            state.first_push_at = None
            state.current_stream_closed = True

        async def _rollover_stream(reason: str) -> None:
            logger.info(
                f"[wecom] WS stream rollover triggered: req_id={req_id}, "
                f"chat_id={message.chat_id}, old_stream_id={state.stream_id}, "
                f"elapsed={_stream_elapsed():.1f}, reason={reason}"
            )
            await _close_current_stream(notice=rollover_notice)
            state.stream_id = f"ws_stream_{uuid.uuid4().hex[:12]}"
            state.current_stream_closed = False

        async def _switch_to_active_send(reason: str) -> None:
            if state.active_send_mode:
                return

            elapsed = _stream_elapsed()
            state.active_send_mode = True
            state.active_send_reason = reason
            state.active_send_started_at = time.time()
            logger.info(
                f"[wecom] WS stream switching to active send: req_id={req_id}, "
                f"chat_id={message.chat_id}, stream_id={state.stream_id}, "
                f"elapsed={elapsed:.1f}, reason={reason}"
            )
            await _close_current_stream(notice=active_send_notice)

        async def _maybe_rollover_stream(*, boundary_safe: bool, reason: str) -> None:
            """Evaluate whether to roll over or switch to active send."""
            if state.active_send_mode or state.first_push_at is None:
                return
            elapsed = _stream_elapsed()
            if elapsed < soft_limit:
                return

            # WeCom WS mode strongly supports sequential distinct stream bubbles for long output,
            # but once we cross the hard limit we stop streaming and rely on主动补发收尾。
            if boundary_safe and _can_rollover_now():
                await _rollover_stream(f"{reason}-soft-limit")
                return
            if elapsed >= hard_limit:
                await _switch_to_active_send(f"{reason}-hard-limit")

        async def _maybe_push(*, force: bool = False) -> None:
            if state.active_send_mode:
                return

            content = state.segment_content
            if not content:
                return
            now = time.time()
            if not force and state.last_sent > 0 and (now - state.last_sent) < ws_interval:
                return
            if state.first_push_at is not None and _stream_elapsed() >= hard_limit and _ws_tool_placeholders:
                await _switch_to_active_send("hard-limit-before-unsafe-update")
                return
            payload = _segment_payload(content)
            if not payload:
                return
            ok = await channel.send_ws_stream_update(req_id, state.stream_id, payload, finish=False)
            if ok:
                sent_at = time.time()
                state.current_stream_closed = False
                if state.first_push_at is None:
                    state.first_push_at = sent_at
                state.last_sent = sent_at

        async def _on_text(text: str) -> None:
            if not text:
                return
            state.segment_content += text
            await _maybe_push()
            await _maybe_rollover_stream(
                boundary_safe=True,
                reason="text-boundary",
            )

        async def _on_tool_start(tool_id: str, tool_name: str) -> None:
            display = self._get_tool_display_name(tool_name, {})
            placeholder = f"⏳ `{display}`"
            _ws_tool_placeholders[tool_id] = placeholder
            if state.segment_content:
                state.segment_content += "\n\n"
            state.segment_content += placeholder
            state.segment_content += "\n\n"
            await _maybe_push(force=True)
            await _maybe_rollover_stream(boundary_safe=False, reason="tool-start")

        async def _on_tool_display_update(tool_id: str, new_display: str) -> None:
            old_placeholder = _ws_tool_placeholders.get(tool_id)
            if not old_placeholder:
                return
            new_placeholder = f"⏳ `{new_display}`"
            if old_placeholder in state.segment_content:
                state.segment_content = state.segment_content.replace(old_placeholder, new_placeholder, 1)
                _ws_tool_placeholders[tool_id] = new_placeholder
                await _maybe_push(force=True)
                await _maybe_rollover_stream(boundary_safe=False, reason="tool-display-update")

        async def _on_tool(tool_id: str, summary: str) -> None:
            if not summary:
                return
            placeholder = _ws_tool_placeholders.pop(tool_id, None)
            if placeholder and placeholder in state.segment_content:
                state.segment_content = state.segment_content.replace(placeholder, summary, 1)
            else:
                if state.segment_content:
                    state.segment_content += "\n\n"
                state.segment_content += summary
                state.segment_content += "\n\n"
            await _maybe_push(force=True)
            await _maybe_rollover_stream(boundary_safe=True, reason="tool-summary")

        def _finalize_pending_tool_placeholders() -> None:
            if not _ws_tool_placeholders:
                return
            for tool_id, placeholder in list(_ws_tool_placeholders.items()):
                summary = placeholder.replace("⏳", "🔧", 1)
                if placeholder in state.segment_content:
                    state.segment_content = state.segment_content.replace(placeholder, summary, 1)
                else:
                    if state.segment_content:
                        state.segment_content += "\n\n"
                    state.segment_content += summary
                    state.segment_content += "\n\n"
                _ws_tool_placeholders.pop(tool_id, None)

        try:
            result = await self._consume_executor_events(
                message,
                session_id,
                request,
                on_text_delta=_on_text,
                on_tool_start=_on_tool_start,
                on_tool_display_update=_on_tool_display_update,
                on_tool_summary=_on_tool,
            )

            content = result.final_content
            if content:
                content = self._truncate_response(content, "wecom")
                content = self._prepend_tool_summaries(content, result)
                final_output_content = content

                # In rollover mode, we don't completely override the accumulated stream text
                # to prevent duplicating bubbles. We only ensure pending components exist if we miss them.
                if not state.segment_content and content:
                    state.segment_content = content
                elif result.tool_summaries:
                    missing = [s for s in result.tool_summaries if s not in state.segment_content]
                    if missing:
                        state.segment_content += "\n\n" + "\n".join(missing)

            elif result.is_error and not result.final_content:
                if state.segment_content:
                    state.segment_content += "\n\n"
                state.segment_content += "⏰ 处理超时，请稍后重试。"
                final_output_content = state.segment_content
        except Exception as e:
            logger.error(f"[wecom] AI processing error (websocket): {e}", exc_info=True)
            state.segment_content = f"❌ 处理出错：{str(e)[:200]}"
            final_output_content = state.segment_content
        finally:
            _finalize_pending_tool_placeholders()
            if not final_output_content:
                final_output_content = state.segment_content

            if state.active_send_mode:
                active_payload = _build_active_send_payload(final_output_content)
                if active_payload:
                    state.final_active_sent = await _send_active_message(active_payload)
                    logger.info(
                        f"[wecom] WS active send finalized: req_id={req_id}, "
                        f"chat_id={message.chat_id}, stream_id={state.stream_id}, "
                        f"reason={state.active_send_reason or 'unknown'}, "
                        f"success={state.final_active_sent}"
                    )
                return

            final_content = _segment_payload(state.segment_content)
            if final_content and not state.current_stream_closed:
                await channel.send_ws_stream_finish(req_id, state.stream_id, final_content)

    async def _process_wecom_stream(
        self,
        message: InboundMessage,
        session_id: str,
        stream_id: str,
    ) -> None:
        """企微专用：流式处理 AI 事件，text_delta 实时写入 StreamBuffer。

        Uses the shared ``_consume_executor_events()`` loop; channel-specific
        behaviour is injected via callbacks.
        """
        channel = self.manager.get_channel("wecom") if self.manager else None
        if not channel:
            logger.error("[wecom] Channel not found for stream processing")
            return

        buf = channel.get_stream_buffer_by_id(stream_id)
        if not buf:
            logger.error(f"[wecom] StreamBuffer not found: {stream_id}")
            return

        request = await self._build_request(message, session_id)

        # Persist user message immediately so it appears in the UI
        self._archive_user_message(message, session_id, request)

        # Callbacks: write text deltas and tool summaries to StreamBuffer in real time
        async def _on_text(text: str) -> None:
            buf.append(text)

        async def _on_tool(tool_id: str, summary: str) -> None:
            buf.append(f"\n\n{summary}\n\n")

        try:
            result = await self._consume_executor_events(
                message, session_id, request,
                on_text_delta=_on_text,
                on_tool_summary=_on_tool,
            )

            content = result.final_content
            if content:
                content = self._truncate_response(content, "wecom")
                content = self._prepend_tool_summaries(content, result)

                current = buf.full_content
                if not current:
                    # 没有任何流式增量时，直接落地最终内容
                    buf.set_final(content)
                elif content.startswith(current) or current in content:
                    # 最终内容包含当前已展示内容：可安全切换为规范化终稿
                    if content != current:
                        buf.set_final(content)
                        logger.debug(
                            f"[wecom] Stream final content normalized: {len(current)} -> {len(content)}"
                        )
                elif content != current:
                    # 防止回退覆盖：当前已展示内容优先；但补齐缺失工具摘要，减少与 Nexus 不一致
                    if result.tool_summaries:
                        missing = [s for s in result.tool_summaries if s not in current]
                        if missing:
                            buf.append("\n\n" + "\n".join(missing))
                    logger.info(
                        f"[wecom] Skip unsafe final override: "
                        f"streamed_len={len(current)}, final_len={len(content)}"
                    )
            elif result.is_error and not result.final_content:
                buf.append("\n\n⏰ 处理超时，请稍后重试。")
        except Exception as e:
            logger.error(f"[wecom] AI processing error: {e}", exc_info=True)
            buf.set_final(f"❌ 处理出错：{str(e)[:200]}")
        finally:
            buf.mark_finished()

    async def _process_wecom_bot_stream(
        self,
        message: InboundMessage,
        session_id: str,
        simulator_id: str,
    ) -> None:
        """企微普通机器人专用：AI 事件实时写入 StreamSimulator，
        并启动模拟流式发送任务。

        Uses the shared ``_consume_executor_events()`` loop; channel-specific
        behaviour is injected via callbacks.
        """
        channel = self.manager.get_channel("wecom_bot") if self.manager else None
        if not channel:
            logger.error("[wecom_bot] Channel not found for stream processing")
            return

        sim = channel.get_stream_simulator_by_id(simulator_id)
        if not sim:
            logger.error(f"[wecom_bot] StreamSimulator not found: {simulator_id}")
            return

        request = await self._build_request(message, session_id)

        # Persist user message immediately
        self._archive_user_message(message, session_id, request)

        # Start the stream simulation task (sends incremental content)
        stream_task = asyncio.create_task(
            channel.send_stream_content(simulator_id)
        )

        # Callbacks: write text deltas and tool summaries to StreamSimulator
        async def _on_text(text: str) -> None:
            sim.append(text)

        async def _on_tool(tool_id: str, summary: str) -> None:
            sim.append(f"\n\n{summary}\n\n")

        try:
            result = await self._consume_executor_events(
                message, session_id, request,
                on_text_delta=_on_text,
                on_tool_summary=_on_tool,
            )

            content = result.final_content
            if content:
                content = self._truncate_response(content, "wecom_bot")
                content = self._prepend_tool_summaries(content, result)

                current = sim.full_content
                if not current:
                    sim.set_final(content)
                elif content != current:
                    # 补齐缺失工具摘要
                    if result.tool_summaries:
                        missing = [s for s in result.tool_summaries if s not in current]
                        if missing:
                            sim.append("\n\n" + "\n".join(missing))
            elif result.is_error and not result.final_content:
                sim.append("\n\n⏰ 处理超时，请稍后重试。")
        except Exception as e:
            logger.error(f"[wecom_bot] AI processing error: {e}", exc_info=True)
            sim.set_final(f"❌ 处理出错：{str(e)[:200]}")
        finally:
            sim.mark_finished()
            # Wait for stream simulation to complete sending
            try:
                await asyncio.wait_for(stream_task, timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning("[wecom_bot] Stream simulation timed out")
                stream_task.cancel()

    async def _process_wecom_bot_single(
        self,
        message: InboundMessage,
        session_id: str,
        simulator_id: str,
    ) -> None:
        """企微普通机器人单聊专用：等 AI 全部完成后一次性发送完整消息。

        单聊场景不需要流式模拟，等待 AI 处理完毕后直接发送最终结果。
        仍使用 StreamSimulator 收集内容，但不启动 send_stream_content 任务。
        """
        channel = self.manager.get_channel("wecom_bot") if self.manager else None
        if not channel:
            logger.error("[wecom_bot] Channel not found for single chat processing")
            return

        sim = channel.get_stream_simulator_by_id(simulator_id)
        if not sim:
            logger.error(f"[wecom_bot] StreamSimulator not found: {simulator_id}")
            return

        request = await self._build_request(message, session_id)

        # Persist user message immediately
        self._archive_user_message(message, session_id, request)

        # Callbacks: still accumulate text in StreamSimulator (for final content)
        async def _on_text(text: str) -> None:
            sim.append(text)

        async def _on_tool(tool_id: str, summary: str) -> None:
            sim.append(f"\n\n{summary}\n\n")

        try:
            result = await self._consume_executor_events(
                message, session_id, request,
                on_text_delta=_on_text,
                on_tool_summary=_on_tool,
            )

            content = result.final_content
            if content:
                content = self._truncate_response(content, "wecom_bot")
                content = self._prepend_tool_summaries(content, result)

                current = sim.full_content
                if not current:
                    sim.set_final(content)
                elif content != current:
                    if result.tool_summaries:
                        missing = [s for s in result.tool_summaries if s not in current]
                        if missing:
                            sim.append("\n\n" + "\n".join(missing))
            elif result.is_error and not result.final_content:
                sim.set_final("⏰ 处理超时，请稍后重试。")
        except Exception as e:
            logger.error(f"[wecom_bot] AI processing error (single): {e}", exc_info=True)
            sim.set_final(f"❌ 处理出错：{str(e)[:200]}")
        finally:
            sim.mark_finished()

            # 单聊：AI 完成后通过 webhook 一次性发送完整消息
            final_content = sim.full_content
            if final_content:
                chat_id = sim.chat_id
                sender_id = message.sender_id
                logger.info(
                    f"[wecom_bot] Single chat: sending final message "
                    f"({len(final_content)} chars) to {chat_id}, "
                    f"sender={sender_id}"
                )
                # 单聊通过 webhook 发到群里，@发送者以便其知道回复
                await channel._send_via_webhook(
                    final_content,
                    msgtype="text",
                    mentioned_list=[sender_id] if sender_id else None,
                    chatid=chat_id,
                )

            # Cleanup simulator
            channel._cleanup_simulator(simulator_id, sim.chat_id)

    async def _process_wecom_bot_event_based(
        self,
        message: InboundMessage,
        session_id: str,
        simulator_id: str,
    ) -> None:
        """企微普通机器人群聊专用：按 AGUI 语义事件分段发送。

        不同于 _process_wecom_bot_single（一次性发完整消息）和
        _process_wecom_bot_stream（每隔 3s 发文本碎片），此方法
        按语义事件分界发送：

        1. 当 tool_call 开始时 → flush 之前累积的文本段为一条消息
        2. 当 tool_call 结束时 → 发一条 "🔧 ToolName" 消息
        3. AI 完成后 → flush 剩余文本段为最终消息

        遵守 webhook 频率限制（20 条/分钟，≥3s 间隔）。
        """
        channel = self.manager.get_channel("wecom_bot") if self.manager else None
        if not channel:
            logger.error("[wecom_bot] Channel not found for event-based processing")
            return

        sim = channel.get_stream_simulator_by_id(simulator_id)
        if not sim:
            logger.error(f"[wecom_bot] StreamSimulator not found: {simulator_id}")
            return

        request = await self._build_request(message, session_id)
        self._archive_user_message(message, session_id, request)

        # -- Event-based sending state --
        _text_buffer: list[str] = []  # accumulates text deltas between events
        _last_send_time: float = 0.0
        _min_interval: float = 3.0  # webhook rate limit
        _chat_id: str = sim.chat_id  # 目标群的 chatid

        async def _send_event_msg(content: str, msgtype: str = "markdown") -> None:
            """Send a single message respecting webhook rate limit."""
            nonlocal _last_send_time
            if not content.strip():
                return
            elapsed = time.time() - _last_send_time
            if _last_send_time > 0 and elapsed < _min_interval:
                await asyncio.sleep(_min_interval - elapsed)
            await channel._send_via_webhook(content, msgtype=msgtype, chatid=_chat_id)
            _last_send_time = time.time()

        async def _flush_text() -> None:
            """Flush accumulated text buffer as one webhook message."""
            text = "".join(_text_buffer).strip()
            _text_buffer.clear()
            if text:
                await _send_event_msg(text)

        # Callbacks
        async def _on_text(text: str) -> None:
            _text_buffer.append(text)
            sim.append(text)

        async def _on_tool_start(tool_id: str, tool_name: str) -> None:
            # Tool call started → flush preceding text so it arrives before the tool summary
            await _flush_text()

        async def _on_tool(tool_id: str, summary: str) -> None:
            # Tool call ended → flush preceding text, then send tool summary
            await _flush_text()
            await _send_event_msg(summary)
            sim.append(f"\n\n{summary}\n\n")

        try:
            result = await self._consume_executor_events(
                message, session_id, request,
                on_text_delta=_on_text,
                on_tool_start=_on_tool_start,
                on_tool_summary=_on_tool,
            )

            # AI finished → always flush remaining text buffer first
            remaining = "".join(_text_buffer).strip()
            _text_buffer.clear()

            content = result.final_content
            current_streamed = sim.full_content.strip()

            if content and not current_streamed:
                # Nothing was sent yet → send the full final content
                content = self._truncate_response(content, "wecom_bot")
                await _send_event_msg(content)
                sim.set_final(content)
            elif remaining:
                # We've been streaming; flush any remaining text buffer
                await _send_event_msg(remaining)
            elif result.is_error:
                await _send_event_msg("⏰ 处理超时，请稍后重试。")
                sim.set_final("⏰ 处理超时，请稍后重试。")
        except Exception as e:
            logger.error(f"[wecom_bot] AI processing error (event-based): {e}", exc_info=True)
            err_msg = f"❌ 处理出错：{str(e)[:200]}"
            await _send_event_msg(err_msg)
            sim.set_final(err_msg)
        finally:
            sim.mark_finished()
            channel._cleanup_simulator(simulator_id, sim.chat_id)

    async def _process_and_notify(
        self,
        message: InboundMessage,
        session_id: str,
        target: NotificationTarget,
        handler: UnifiedNotificationHandler,
    ) -> None:
        """Background task: run AI processing with progress updates."""
        try:
            response = await self._process_with_ai(message, session_id, target, handler)

            if response:
                # Edit the progress placeholder with the final result,
                # or send new message(s) if the response is too long.
                max_len = CHANNEL_MAX_LENGTH.get(message.channel, 4000)
                if len(response) <= max_len and target.message_id:
                    await handler.notify_completion(target, response, success=True)
                else:
                    # For long responses, edit placeholder to summary, then send full content
                    if target.message_id:
                        summary = response[:200] + "…" if len(response) > 200 else response
                        await handler.notify_progress(target, f"✅ 处理完成（共 {len(response)} 字符）\n\n{summary}")
                    # Send full response via send_text (auto-splits)
                    full_target = handler.build_target_from_channel(
                        channel_name=message.channel,
                        chat_id=message.chat_id,
                    )
                    await handler.notify(full_target, response)
            else:
                # No response content
                await handler.notify_progress(target, "⚠️ 未能获取有效回复，请重试。")

        except Exception as e:
            logger.error(f"Error in background processing: {e}", exc_info=True)
            try:
                await handler.notify_progress(target, f"❌ 处理出错：{str(e)[:200]}")
            except Exception:
                pass

    def _truncate_response(self, content: str, channel: str) -> str:
        """根据通道限制截断响应"""
        max_len = CHANNEL_MAX_LENGTH.get(channel, 4000)
        if len(content) > max_len:
            return content[:max_len] + "\n\n... (响应被截断)"
        return content

    @staticmethod
    def _prepend_tool_summaries(content: str, result) -> str:
        """Prepend tool summaries to final content when tools were called."""
        if result.tool_call_count > 0 and result.tool_summaries:
            tool_section = "\n".join(result.tool_summaries)
            return tool_section + "\n\n---\n\n" + content
        return content

    @staticmethod
    def _extract_tool_result_text(result_content: Any) -> str:
        """Normalize tool_result payloads into plain text for nested tool parsing."""
        if isinstance(result_content, str):
            return result_content
        if isinstance(result_content, list):
            text_parts: list[str] = []
            for item in result_content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    if isinstance(text, str):
                        text_parts.append(text)
                elif isinstance(item, str):
                    text_parts.append(item)
                else:
                    text_parts.append(str(item))
            return "\n".join(text_parts) if text_parts else ""
        if result_content is None:
            return ""
        return str(result_content)

    @staticmethod
    def _parse_single_subagent_tool_call(content: str) -> Optional[dict[str, Any]]:
        """Parse one nested ``<tool_call>`` block emitted inside a tool_result."""
        if not content:
            return None

        lines = content.strip().splitlines()
        if not lines:
            return None

        tool_name = lines[0].strip()
        if not tool_name:
            return None

        arguments: dict[str, Any] = {}
        remaining = "\n".join(lines[1:]) if len(lines) > 1 else ""
        arg_pattern = r'<arg_key>(.*?)</arg_key>\s*<arg_value>(.*?)</arg_value>'

        for key, value in re.findall(arg_pattern, remaining, flags=re.DOTALL):
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            try:
                arguments[key] = json.loads(value)
            except (json.JSONDecodeError, ValueError, TypeError):
                arguments[key] = value

        return {
            "tool_name": tool_name,
            "arguments": arguments,
            "tool_id": f"subagent_{uuid.uuid4().hex[:12]}",
        }

    @classmethod
    def _parse_subagent_tool_calls(cls, text: str) -> list[dict[str, Any]]:
        """Extract nested tool calls embedded in ``tool_result`` text."""
        if not text or "<tool_call>" not in text:
            return []

        calls: list[dict[str, Any]] = []
        pattern = r'<tool_call>(.*?)</tool_call>'
        for match in re.findall(pattern, text, flags=re.DOTALL):
            parsed = cls._parse_single_subagent_tool_call(match.strip())
            if parsed:
                calls.append(parsed)
        return calls

    @staticmethod
    def _parse_tool_params(raw_params: Any) -> dict:
        """Parse tool parameters from structured data or raw argument strings.

        Handles several common edge cases from streaming executors:
        - Complete JSON objects
        - Truncated JSON missing the leading ``{"`` (Claude partial_json deltas)
        - Regex fallback for partially formed JSON strings
        """
        if isinstance(raw_params, dict):
            return raw_params
        if not isinstance(raw_params, str):
            return {}

        raw_text = raw_params.strip()
        if not raw_text:
            return {}

        # 1. Try direct JSON / literal_eval parse
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(raw_text)
            except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                return parsed

        # 2. Try repairing truncated JSON (e.g. missing leading `{"`)
        #    Claude partial_json deltas may omit the outer `{` / `}`.
        repaired = raw_text
        if not repaired.startswith("{"):
            repaired = "{" + repaired
        if not repaired.endswith("}"):
            repaired = repaired + "}"
        # Also handle first key missing its leading quote:
        #   e.g. 'command":"value"' → '"command":"value"'
        repaired = re.sub(r'^{\s*([a-zA-Z_]\w*)"', r'{"\1"', repaired)
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(repaired)
            except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                return parsed

        # 3. Regex fallback: extract known keys from partially formed JSON.
        #    The pattern allows the key to optionally lack its leading quote
        #    (covers truncated-delta edge case).
        extracted: dict[str, Any] = {}
        for key in (
            "explanation",
            "description",
            "command",
            "query",
            "searchTerm",
            "pattern",
            "filePath",
            "file_path",
            "path",
            "directory",
            "target_directory",
            "subagent_name",
            "subagent_type",
            "title",
            "prompt",
            "url",
            "skill",
        ):
            # Try strict match first: "key": "value"
            match = re.search(
                rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"',
                raw_text,
                re.S,
            )
            if not match:
                # Fallback: key without leading quote (truncated JSON)
                match = re.search(
                    rf'(?:^|[{{,\s]){re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"',
                    raw_text,
                    re.S,
                )
            if not match:
                continue
            value = match.group(1)
            try:
                extracted[key] = json.loads(f'"{value}"')
            except json.JSONDecodeError:
                extracted[key] = value.replace("\\n", " ").replace("\\t", " ").strip()

        return extracted

    @staticmethod
    def _format_tool_summary(channel: str, display: str) -> str:
        """Format a tool summary string for downstream channels."""
        display = (display or "").strip()
        if not display:
            return "🔧 Tool"

        if channel == "wecom_bot":
            return f"🔧 {display}"

        return f"🔧 `{display}`"

    @staticmethod
    def _extract_followup_question(params: dict) -> str:
        """Extract a readable follow-up question from ask_followup_question params."""
        if not isinstance(params, dict):
            return ""

        questions = params.get("questions")
        parsed_questions = questions
        if isinstance(questions, str):
            try:
                parsed_questions = json.loads(questions)
            except (json.JSONDecodeError, TypeError):
                parsed_questions = None

        if isinstance(parsed_questions, list):
            for item in parsed_questions:
                if isinstance(item, dict):
                    question = str(item.get("question", "")).strip()
                    if question:
                        return question

        title = str(params.get("title", "")).strip()
        if title:
            return title

        return ""

    @staticmethod
    def _resolve_raw_tool_key(formatted_name: str) -> str:
        """Reverse-map a formatted display name back to a raw tool key.

        When the adapter already formatted the tool name (e.g. ``"Read: 读取文件"``),
        ``_get_tool_display_name`` would short-circuit.  This helper extracts
        the prefix (``"Read"``) and maps it back to a canonical raw tool key
        so that ``_get_tool_display_name`` can re-derive the display with params.
        """
        _PREFIX_TO_RAW: dict[str, str] = {
            "read": "read_file",
            "write": "write_to_file",
            "edit": "replace_in_file",
            "grep": "search_content",
            "glob": "search_file",
            "bash": "execute_command",
            "task": "task",
            "skill": "use_skill",
            "search": "web_search",
            "fetch": "web_fetch",
            "todo": "todo_write",
            "codebase": "codebase_search",
            "list": "list_dir",
        }
        if ": " not in formatted_name:
            return formatted_name
        prefix = formatted_name.split(": ", 1)[0].strip().lower()
        return _PREFIX_TO_RAW.get(prefix, formatted_name)

    @staticmethod
    def _get_tool_display_name(tool_name: str, params: dict) -> str:
        """Generate a semantic display title for a tool call, matching AGUI style.

        Produces titles like ``Read: /home/ubuntu/app.py`` or ``Bash: 安装依赖包``
        instead of the raw tool name.  Falls back to the original tool name when
        no meaningful context can be extracted from *params*.
        """
        if not isinstance(params, dict):
            return tool_name

        if ": " in tool_name:
            return tool_name

        tool_key = (tool_name or "").strip().lower()

        if tool_key == "task":
            subagent = params.get("subagent_type", params.get("subagent_name", ""))
            desc = params.get("description", "")
            if subagent and desc:
                return f"Task: {subagent} - {desc}"
            elif subagent:
                return f"Task: {subagent}"
            elif desc:
                return f"Task: {desc}"

        elif tool_key in ("skill", "use_skill"):
            skill = params.get("skill", params.get("command", ""))
            if skill:
                return f"Skill: {skill}"

        elif tool_key in ("read", "read_file"):
            fp = params.get("file_path", params.get("filePath", ""))
            if fp:
                return f"Read: {fp}"
            return "Read: 读取文件"

        elif tool_key in ("write", "write_to_file"):
            fp = params.get("file_path", params.get("filePath", ""))
            if fp:
                return f"Write: {fp}"
            return "Write: 写入文件"

        elif tool_key in ("edit", "replace_in_file", "apply_patch"):
            fp = params.get("file_path", params.get("filePath", ""))
            if fp:
                return f"Edit: {fp}"
            return "Edit: 编辑文件"

        elif tool_key in ("grep", "search_content"):
            pattern = params.get("pattern", "")
            path = params.get("path", params.get("directory", ""))
            if pattern and path:
                if len(pattern) > 40:
                    pattern = pattern[:40] + "…"
                return f"Grep: `{pattern}` in {path}"
            elif pattern:
                if len(pattern) > 60:
                    pattern = pattern[:60] + "…"
                return f"Grep: `{pattern}`"
            elif path:
                return f"Grep: {path}"
            return "Grep: 搜索内容"

        elif tool_key in ("glob", "search_file"):
            path = params.get("path", params.get("target_directory", ""))
            pattern = params.get("pattern", "")
            if path and pattern:
                return f"Glob: {pattern} in {path}"
            elif path:
                return f"Glob: {path}"
            elif pattern:
                return f"Glob: {pattern}"
            return "Glob: 搜索文件"

        elif tool_key in ("bash", "execute_command"):
            description = params.get("description", params.get("explanation", ""))
            if description:
                return f"Bash: {description}"
            command = params.get("command", "")
            if command:
                if len(command) > 60:
                    command = command[:60] + "…"
                return f"Bash: {command}"
            return "Bash: 执行命令"

        elif tool_key in ("todowrite", "todo_write"):
            todos_str = params.get("todos", "")
            if todos_str:
                try:
                    todos = json.loads(todos_str) if isinstance(todos_str, str) else todos_str
                    if isinstance(todos, list) and todos:
                        total = len(todos)
                        current_index = 0
                        current_content = ""
                        for i, todo in enumerate(todos):
                            if isinstance(todo, dict) and todo.get("status") == "in_progress":
                                current_index = i + 1
                                current_content = todo.get("content", "")
                                break
                        if current_index > 0 and current_content:
                            return f"Todos: {current_index}/{total} - {current_content}"
                        elif current_index > 0:
                            return f"Todos: {current_index}/{total}"
                        else:
                            return f"Todos: {total} items"
                except (json.JSONDecodeError, TypeError):
                    pass

        elif tool_name in ("WebSearch", "web_search"):
            query = params.get("query", params.get("searchTerm", ""))
            if query:
                if len(query) > 60:
                    query = query[:60] + "…"
                return f"Search: {query}"

        elif tool_name in ("WebFetch", "web_fetch"):
            url = params.get("url", "")
            if url:
                if len(url) > 60:
                    url = url[:60] + "…"
                return f"Fetch: {url}"

        elif tool_name in ("AskUserQuestion", "ask_followup_question"):
            question = ChannelService._extract_followup_question(params)
            if question:
                if len(question) > 60:
                    question = question[:60] + "…"
                return f"AskUserQuestion: {question}"

        generic_context = [
            params.get("description"),
            params.get("explanation"),
            ChannelService._extract_followup_question(params),
            params.get("title"),
            params.get("prompt"),
            params.get("query"),
            params.get("searchTerm"),
            params.get("pattern"),
            params.get("command"),
            params.get("file_path", params.get("filePath", "")),
            params.get("path", params.get("directory", params.get("target_directory", ""))),
            params.get("url"),
        ]
        for candidate in generic_context:
            if isinstance(candidate, str):
                candidate = candidate.strip()
                if candidate:
                    if len(candidate) > 60:
                        candidate = candidate[:60] + "…"
                    return f"{tool_name}: {candidate}"

        # mcp__xxx and other tools — keep original name
        return tool_name

    async def _process_with_ai(
        self,
        message: InboundMessage,
        session_id: str,
        target: NotificationTarget,
        handler: UnifiedNotificationHandler,
    ) -> Optional[str]:
        """Process message with AI for non-streaming channels (Telegram, Slack, etc.).

        Uses the shared ``_consume_executor_events()`` loop; injects a progress
        callback so the user sees periodic "⏳ processing…" updates.
        """
        request = await self._build_request(message, session_id)

        # Persist user message immediately so it appears in the UI
        self._archive_user_message(message, session_id, request)

        last_progress_time = time.time()
        collected_chars = 0

        async def _on_text(text: str) -> None:
            nonlocal last_progress_time, collected_chars
            collected_chars += len(text)
            now = time.time()
            if now - last_progress_time >= PROGRESS_UPDATE_INTERVAL:
                last_progress_time = now
                await handler.notify_progress(
                    target,
                    f"⏳ 正在处理… 已收集 {collected_chars} 字符"
                )

        result = await self._consume_executor_events(
            message, session_id, request,
            on_text_delta=_on_text,
        )

        content = result.final_content
        if not content:
            # No result event — fall back to collected text parts
            content = "".join(result.collected_text_parts).strip()

        if not content:
            if result.is_error:
                return "抱歉，处理超时，请稍后重试。"
            # No text content but tools were called — surface tool summaries alone
            if result.tool_call_count > 0 and result.tool_summaries:
                return "\n".join(result.tool_summaries)
            return None

        content = self._truncate_response(content, message.channel)
        content = self._prepend_tool_summaries(content, result)

        return content
    
    async def _send_typing_indicator(self, message: InboundMessage) -> None:
        """发送输入中指示"""
        if not self.manager:
            return

        channel = self.manager.get_channel(message.channel)
        if not channel:
            return

        try:
            await channel.send_typing(message.chat_id)
        except Exception as e:
            logger.debug(f"Failed to send typing indicator: {e}")
    
    async def _handle_error(self, error: Exception, channel: str) -> None:
        """处理通道错误"""
        logger.error(f"Channel error [{channel}]: {error}")


def get_channel_service() -> Optional[ChannelService]:
    """获取全局 channel 服务实例"""
    return _channel_service


async def create_channel_service() -> Optional[ChannelService]:
    """创建并初始化 channel 服务"""
    global _channel_service
    
    service = ChannelService()
    if await service.initialize():
        _channel_service = service
        return service
    
    return None

"""Telegram Channel 实现

基于 python-telegram-bot 库，使用 Long Polling 模式。
参考 nanobot 的 telegram 实现。
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

from .base import BaseChannel
from .events import InboundMessage, MediaAttachment, MessageType, OutboundMessage

logger = logging.getLogger(__name__)

# 延迟导入 telegram 库
try:
    from telegram import Update, Message as TelegramMessage
    from telegram.constants import ChatType, ParseMode
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    Application = None

if TYPE_CHECKING:
    from .config import TelegramConfig


class TelegramChannel(BaseChannel):
    """Telegram 消息通道"""

    def __init__(self, config: "TelegramConfig"):
        if not TELEGRAM_AVAILABLE:
            raise ImportError(
                "Telegram support requires 'python-telegram-bot'. "
                "Install with: pip install 'virtual-human-sdk[telegram]'"
            )
        super().__init__(config)
        self.config: "TelegramConfig" = config
        self._app: Optional[Any] = None
        self._ready_event = None

    @property
    def channel_type(self) -> str:
        return "telegram"

    async def _start(self) -> None:
        """启动 Telegram Bot"""
        self._app = (
            Application.builder()
            .token(self.config.bot_token)
            .connect_timeout(self.config.connect_timeout)
            .read_timeout(self.config.read_timeout)
            .build()
        )

        # 注册处理器
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text_message)
        )
        self._app.add_handler(
            MessageHandler(filters.PHOTO, self._on_photo_message)
        )
        self._app.add_handler(
            MessageHandler(filters.VIDEO, self._on_video_message)
        )
        self._app.add_handler(
            MessageHandler(filters.VOICE, self._on_voice_message)
        )
        self._app.add_handler(
            MessageHandler(filters.Document.ALL, self._on_document_message)
        )
        self._app.add_handler(
            CommandHandler("start", self._on_start_command)
        )
        # 将所有其他 /command 也当作普通文本转发给 AI 处理
        self._app.add_handler(
            MessageHandler(filters.COMMAND, self._on_text_message)
        )

        # 初始化并启动
        await self._app.initialize()

        if self.config.webhook_url:
            # Webhook 模式
            await self._app.bot.set_webhook(
                url=self.config.webhook_url,
                secret_token=self.config.webhook_secret,
                allowed_updates=self.config.allowed_updates,
            )
            logger.info(f"[{self.name}] Webhook set to {self.config.webhook_url}")
        else:
            # Long Polling 模式
            await self._app.updater.start_polling(
                drop_pending_updates=self.config.skip_pending,
                allowed_updates=self.config.allowed_updates,
            )
            logger.info(f"[{self.name}] Started polling")

        await self._app.start()

    async def _stop(self) -> None:
        """停止 Telegram Bot"""
        if self._app:
            if not self.config.webhook_url:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

    async def _send_message(self, message: OutboundMessage) -> Optional[Any]:
        """发送消息到 Telegram"""
        if not self._app:
            return None

        bot = self._app.bot
        chat_id = int(message.chat_id) if message.chat_id.isdigit() else message.chat_id

        # 处理媒体
        if message.media_paths or message.media_urls:
            return await self._send_media_group(bot, chat_id, message)

        # 发送文本消息
        parse_mode = self._get_parse_mode(message.parse_mode)

        kwargs = {
            "chat_id": chat_id,
            "text": message.content,
            "parse_mode": parse_mode,
            "disable_notification": message.silent,
        }

        if message.reply_to:
            kwargs["reply_to_message_id"] = int(message.reply_to)

        return await bot.send_message(**kwargs)

    async def send_typing(self, chat_id: str) -> None:
        """发送输入中指示"""
        if not self._app:
            return

        try:
            chat_id_value = int(chat_id) if chat_id.isdigit() else chat_id
            await self._app.bot.send_chat_action(chat_id=chat_id_value, action="typing")
        except Exception as e:
            logger.debug(f"[{self.name}] Failed to send typing indicator: {e}")

    async def _send_media_group(
        self,
        bot: Any,
        chat_id: Any,
        message: OutboundMessage
    ) -> Optional[Any]:
        """发送媒体组"""
        import mimetypes
        from urllib.parse import urlparse
        from telegram import InputMediaAudio, InputMediaDocument, InputMediaPhoto, InputMediaVideo

        def _infer_media_class(mime_type: Optional[str]) -> Any:
            if mime_type:
                if mime_type.startswith("image/"):
                    return InputMediaPhoto
                if mime_type.startswith("video/"):
                    return InputMediaVideo
                if mime_type.startswith("audio/"):
                    return InputMediaAudio
            return InputMediaDocument

        media_list = []
        open_files = []

        try:
            # 处理本地文件
            for path in message.media_paths:
                mime_type, _ = mimetypes.guess_type(path)
                media_cls = _infer_media_class(mime_type)
                file_obj = open(path, "rb")
                open_files.append(file_obj)
                media_list.append(media_cls(media=file_obj))

            # 处理 URL
            for url in message.media_urls:
                parsed = urlparse(url)
                mime_type, _ = mimetypes.guess_type(parsed.path)
                media_cls = _infer_media_class(mime_type)
                media_list.append(media_cls(media=url))

            if not media_list:
                return None

            # 第一个媒体添加说明文字
            if message.content:
                media_list[0].caption = message.content
                parse_mode = self._get_parse_mode(message.parse_mode)
                if parse_mode:
                    media_list[0].parse_mode = parse_mode

            return await bot.send_media_group(
                chat_id=chat_id,
                media=media_list,
                disable_notification=message.silent,
            )
        finally:
            for f in open_files:
                try:
                    f.close()
                except Exception:
                    pass

    def _get_parse_mode(self, parse_mode: Optional[str]) -> Optional[Any]:
        """转换解析模式"""
        if not parse_mode:
            return None

        parse_mode = parse_mode.upper()
        if parse_mode == "HTML":
            return ParseMode.HTML
        elif parse_mode == "MARKDOWN":
            return ParseMode.MARKDOWN
        elif parse_mode == "MARKDOWNV2":
            return ParseMode.MARKDOWN_V2
        return None

    # ============== 消息处理器 ==============

    async def _on_text_message(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        """处理文本消息"""
        if not update.message:
            return

        message = self._convert_message(update.message, MessageType.TEXT)
        await self._handle_inbound_message(message)

    async def _on_photo_message(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        """处理图片消息"""
        if not update.message:
            return

        message = self._convert_message(update.message, MessageType.IMAGE)

        # 提取图片信息
        if update.message.photo:
            photo = update.message.photo[-1]  # 取最大尺寸
            message.media.append(MediaAttachment(
                file_id=photo.file_id,
                width=photo.width,
                height=photo.height,
                file_size=photo.file_size,
            ))

        await self._handle_inbound_message(message)

    async def _on_video_message(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        """处理视频消息"""
        if not update.message or not update.message.video:
            return

        message = self._convert_message(update.message, MessageType.VIDEO)
        video = update.message.video

        message.media.append(MediaAttachment(
            file_id=video.file_id,
            mime_type=video.mime_type,
            width=video.width,
            height=video.height,
            duration=video.duration,
            file_size=video.file_size,
        ))

        await self._handle_inbound_message(message)

    async def _on_voice_message(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        """处理语音消息"""
        if not update.message or not update.message.voice:
            return

        message = self._convert_message(update.message, MessageType.VOICE)
        voice = update.message.voice

        message.media.append(MediaAttachment(
            file_id=voice.file_id,
            mime_type=voice.mime_type,
            duration=voice.duration,
            file_size=voice.file_size,
        ))

        await self._handle_inbound_message(message)

    async def _on_document_message(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        """处理文档消息"""
        if not update.message or not update.message.document:
            return

        message = self._convert_message(update.message, MessageType.DOCUMENT)
        doc = update.message.document

        message.media.append(MediaAttachment(
            file_id=doc.file_id,
            file_name=doc.file_name,
            mime_type=doc.mime_type,
            file_size=doc.file_size,
        ))

        await self._handle_inbound_message(message)

    async def _on_start_command(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        """处理 /start 命令"""
        if update.message:
            await update.message.reply_text(
                "Hello! I'm a virtual human assistant. How can I help you today?"
            )

    def _convert_message(
        self,
        tg_msg: "TelegramMessage",
        msg_type: MessageType
    ) -> InboundMessage:
        """转换 Telegram 消息为内部格式"""
        # 确定聊天类型
        chat_type = "private"
        if tg_msg.chat.type == ChatType.GROUP:
            chat_type = "group"
        elif tg_msg.chat.type == ChatType.SUPERGROUP:
            chat_type = "supergroup"
        elif tg_msg.chat.type == ChatType.CHANNEL:
            chat_type = "channel"

        # 提取提及
        mentions = []
        if tg_msg.entities:
            for entity in tg_msg.entities:
                if entity.type == "mention":
                    mention_text = tg_msg.text[entity.offset:entity.offset + entity.length]
                    mentions.append(mention_text)

        return InboundMessage(
            channel=self.channel_type,
            sender_id=str(tg_msg.from_user.id) if tg_msg.from_user else "unknown",
            sender_name=tg_msg.from_user.full_name if tg_msg.from_user else None,
            chat_id=str(tg_msg.chat.id),
            chat_type=chat_type,
            message_id=str(tg_msg.message_id),
            content=tg_msg.text or tg_msg.caption or "",
            message_type=msg_type,
            reply_to=str(tg_msg.reply_to_message.message_id) if tg_msg.reply_to_message else None,
            mentions=mentions,
            metadata={
                "chat_title": tg_msg.chat.title,
                "chat_username": tg_msg.chat.username,
                "from_username": tg_msg.from_user.username if tg_msg.from_user else None,
                "date": tg_msg.date.isoformat() if tg_msg.date else None,
            },
        )

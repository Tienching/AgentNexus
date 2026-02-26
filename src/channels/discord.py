"""Discord Channel 实现

基于 discord.py 库，使用 Gateway WebSocket 连接。
参考 openclaw 的 discord 实现。
"""

import asyncio
import io
import logging
import os
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any, Optional

from .base import BaseChannel
from .events import InboundMessage, MediaAttachment, MessageType, OutboundMessage

logger = logging.getLogger(__name__)

# 延迟导入 discord 库
try:
    import discord
    from discord.ext import commands
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    discord = None

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None

if TYPE_CHECKING:
    from .config import DiscordConfig


class DiscordChannel(BaseChannel):
    """Discord 消息通道"""

    def __init__(self, config: "DiscordConfig"):
        if not DISCORD_AVAILABLE:
            raise ImportError(
                "Discord support requires 'discord.py'. "
                "Install with: pip install 'virtual-human-sdk[discord]'"
            )
        super().__init__(config)
        self.config: "DiscordConfig" = config
        self._client: Optional[Any] = None
        self._ready_event = asyncio.Event()

    @property
    def channel_type(self) -> str:
        return "discord"

    async def _start(self) -> None:
        """启动 Discord Bot"""
        # 构建 intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        intents.guild_messages = True

        # 创建客户端
        self._client = DiscordClient(
            config=self.config,
            intents=intents,
            message_handler=self._handle_inbound_message,
        )

        # 启动连接
        asyncio.create_task(self._client.start(self.config.bot_token))

        # 等待就绪
        try:
            await asyncio.wait_for(self._client.wait_until_ready(), timeout=30.0)
            logger.info(f"[{self.name}] Discord bot logged in as {self._client.user}")
        except asyncio.TimeoutError:
            raise RuntimeError("Discord bot failed to connect within 30 seconds")

    async def _stop(self) -> None:
        """停止 Discord Bot"""
        if self._client:
            await self._client.close()
            self._client = None

    async def _download_url_file(self, url: str) -> Optional["discord.File"]:
        """下载 URL 媒体并构造 discord.File"""
        filename = os.path.basename(urllib.parse.urlparse(url).path) or "file"
        try:
            if HTTPX_AVAILABLE:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return discord.File(io.BytesIO(resp.content), filename=filename)

            def _fetch() -> bytes:
                with urllib.request.urlopen(url, timeout=30) as response:
                    return response.read()

            data = await asyncio.to_thread(_fetch)
            return discord.File(io.BytesIO(data), filename=filename)
        except Exception as e:
            logger.error(f"[{self.name}] Failed to download media: {e}")
            return None

    async def _send_message(self, message: OutboundMessage) -> Optional[Any]:
        """发送消息到 Discord"""
        if not self._client:
            return None

        # 获取目标频道
        channel = self._client.get_channel(int(message.chat_id))
        if not channel:
            # 尝试作为用户获取
            try:
                user = await self._client.fetch_user(int(message.chat_id))
                if user:
                    channel = await user.create_dm()
            except Exception as e:
                logger.error(f"[{self.name}] Failed to fetch user/channel: {e}")
                return None

        if not channel:
            logger.error(f"[{self.name}] Channel not found: {message.chat_id}")
            return None

        # 发送媒体
        files = []
        for path in message.media_paths:
            files.append(discord.File(path))

        for url in message.media_urls:
            file_obj = await self._download_url_file(url)
            if file_obj:
                files.append(file_obj)

        # 发送消息
        kwargs = {
            "content": message.content or None,
            "files": files if files else None,
            "silent": message.silent,
        }

        # 处理回复
        if message.reply_to:
            try:
                reference = discord.MessageReference(
                    message_id=int(message.reply_to),
                    channel_id=channel.id,
                )
                kwargs["reference"] = reference
            except ValueError:
                pass

        # 移除 None 值
        kwargs = {k: v for k, v in kwargs.items() if v is not None}

        return await channel.send(**kwargs)

    async def send_typing(self, chat_id: str) -> None:
        """Send a typing indicator to the target channel."""
        if not self._client:
            return

        try:
            channel = self._client.get_channel(int(chat_id))
            if not channel:
                user = await self._client.fetch_user(int(chat_id))
                if user:
                    channel = await user.create_dm()

            if channel and hasattr(channel, "trigger_typing"):
                await channel.trigger_typing()
        except Exception as e:
            logger.debug(f"[{self.name}] Failed to send typing indicator: {e}")


class DiscordClient:
    """Discord 客户端基类占位符（当 discord.py 不可用时）"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

if DISCORD_AVAILABLE:
    class DiscordClient(discord.Client):
        """自定义 Discord 客户端"""

        def __init__(
            self,
            config: "DiscordConfig",
            message_handler: Any,
            **kwargs
        ):
            super().__init__(**kwargs)
            self.config = config
            self._message_handler = message_handler

        async def on_ready(self):
            """Bot 就绪"""
            logger.info(f"Discord bot ready: {self.user} (ID: {self.user.id})")

            # 设置状态
            if self.config.activity_name:
                activity_type = discord.ActivityType.playing
                if self.config.activity_type == "listening":
                    activity_type = discord.ActivityType.listening
                elif self.config.activity_type == "watching":
                    activity_type = discord.ActivityType.watching
                elif self.config.activity_type == "competing":
                    activity_type = discord.ActivityType.competing

                activity = discord.Activity(
                    type=activity_type,
                    name=self.config.activity_name,
                )
                await self.change_presence(activity=activity)

        async def on_message(self, message: discord.Message):
            """收到消息"""
            # 忽略自己的消息
            if message.author == self.user:
                return

            # 忽略其他 bot 的消息（可选）
            if message.author.bot:
                return

            # 转换为内部格式
            inbound_msg = self._convert_message(message)
            await self._message_handler(inbound_msg)

        async def on_error(self, event_method: str, *args, **kwargs):
            """处理错误"""
            logger.error(f"Discord error in {event_method}", exc_info=True)

        def _convert_message(self, msg: discord.Message) -> InboundMessage:
            """转换 Discord 消息为内部格式"""
            # 确定聊天类型
            chat_type = "private"
            if isinstance(msg.channel, discord.DMChannel):
                chat_type = "private"
            elif isinstance(msg.channel, discord.TextChannel):
                chat_type = "channel"
            elif isinstance(msg.channel, discord.GroupChannel):
                chat_type = "group"

            # 提取提及
            mentions = [str(m.id) for m in msg.mentions]

            # 提取媒体
            media = []
            for attachment in msg.attachments:
                media_type = MessageType.DOCUMENT
                if attachment.content_type:
                    if attachment.content_type.startswith("image/"):
                        media_type = MessageType.IMAGE
                    elif attachment.content_type.startswith("video/"):
                        media_type = MessageType.VIDEO
                    elif attachment.content_type.startswith("audio/"):
                        media_type = MessageType.AUDIO

                media.append(MediaAttachment(
                    url=attachment.url,
                    file_name=attachment.filename,
                    mime_type=attachment.content_type,
                    file_size=attachment.size,
                    width=attachment.width,
                    height=attachment.height,
                ))

            # 确定消息类型
            message_type = MessageType.TEXT
            if media:
                message_type = media[0].mime_type.split("/")[0] if media[0].mime_type else MessageType.DOCUMENT
                message_type_map = {
                    "image": MessageType.IMAGE,
                    "video": MessageType.VIDEO,
                    "audio": MessageType.AUDIO,
                }
                message_type = message_type_map.get(message_type, MessageType.DOCUMENT)

            return InboundMessage(
                channel="discord",
                sender_id=str(msg.author.id),
                sender_name=msg.author.display_name,
                chat_id=str(msg.channel.id),
                chat_type=chat_type,
                message_id=str(msg.id),
                content=msg.content,
                message_type=message_type,
                media=media,
                reply_to=str(msg.reference.message_id) if msg.reference else None,
                mentions=mentions,
                metadata={
                    "guild_id": str(msg.guild.id) if msg.guild else None,
                    "guild_name": msg.guild.name if msg.guild else None,
                    "author_username": msg.author.name,
                    "author_discriminator": msg.author.discriminator if hasattr(msg.author, 'discriminator') else None,
                    "is_bot": msg.author.bot,
                },
            )

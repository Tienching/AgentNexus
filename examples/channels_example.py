"""Channels 模块使用示例

展示如何使用 virtual-human-sdk 的 channels 模块连接多个消息平台。

运行前请安装依赖:
    pip install -e ".[all-channels]"

环境变量:
    TELEGRAM_BOT_TOKEN - Telegram Bot Token
    SLACK_BOT_TOKEN - Slack Bot Token
    SLACK_APP_TOKEN - Slack App Token (Socket Mode)
    DISCORD_BOT_TOKEN - Discord Bot Token
"""

import asyncio
import os
from typing import Optional

from src.channels import (
    ChannelManager,
    InboundMessage,
    OutboundMessage,
    TelegramConfig,
    SlackConfig,
    DiscordConfig,
    WhatsAppConfig,
    SignalConfig,
)


class BotApplication:
    """示例 Bot 应用"""

    def __init__(self):
        self.manager: Optional[ChannelManager] = None

    async def handle_message(self, message: InboundMessage) -> None:
        """处理收到的消息"""
        print(f"\n📨 [{message.channel.upper()}] {message.sender_name or message.sender_id}: {message.content}")

        # 简单的 echo 回复
        if message.content.lower() in ("hello", "hi", "你好"):
            reply = OutboundMessage(
                channel=message.channel,
                chat_id=message.chat_id,
                content=f"Hello {message.sender_name or 'there'}! 👋",
                reply_to=message.message_id,
            )
            await self.manager.send(message.channel, reply)

        elif message.content.lower() in ("help", "帮助"):
            help_text = """Available commands:
- hello / hi / 你好 - Greeting
- help / 帮助 - Show this help
- ping - Test latency"""
            reply = OutboundMessage(
                channel=message.channel,
                chat_id=message.chat_id,
                content=help_text,
                reply_to=message.message_id,
            )
            await self.manager.send(message.channel, reply)

        elif message.content.lower() == "ping":
            reply = OutboundMessage(
                channel=message.channel,
                chat_id=message.chat_id,
                content="Pong! 🏓",
                reply_to=message.message_id,
            )
            await self.manager.send(message.channel, reply)

    async def handle_error(self, error: Exception, channel: str) -> None:
        """处理错误"""
        print(f"\n❌ Error in {channel}: {error}")

    async def run(self) -> None:
        """运行 Bot"""
        # 构建配置
        configs = {}

        # Telegram 配置
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if telegram_token:
            configs["telegram"] = TelegramConfig(
                name="telegram-bot",
                bot_token=telegram_token,
                allowed_users=[],  # 空列表表示允许所有用户
            )
            print("✅ Telegram configured")

        # Slack 配置 (Socket Mode)
        slack_token = os.getenv("SLACK_BOT_TOKEN")
        slack_app_token = os.getenv("SLACK_APP_TOKEN")
        if slack_token and slack_app_token:
            configs["slack"] = SlackConfig(
                name="slack-bot",
                bot_token=slack_token,
                app_token=slack_app_token,
                socket_mode=True,
            )
            print("✅ Slack configured")

        # Discord 配置
        discord_token = os.getenv("DISCORD_BOT_TOKEN")
        if discord_token:
            configs["discord"] = DiscordConfig(
                name="discord-bot",
                bot_token=discord_token,
                activity_name="with humans",
                activity_type="playing",
            )
            print("✅ Discord configured")

        # WhatsApp 配置
        whatsapp_bridge = os.getenv("WHATSAPP_BRIDGE_URL")
        if whatsapp_bridge:
            configs["whatsapp"] = WhatsAppConfig(
                name="whatsapp-bot",
                bridge_url=whatsapp_bridge,
            )
            print("✅ WhatsApp configured")

        # Signal 配置
        signal_phone = os.getenv("SIGNAL_PHONE_NUMBER")
        if signal_phone:
            configs["signal"] = SignalConfig(
                name="signal-bot",
                phone_number=signal_phone,
            )
            print("✅ Signal configured")

        if not configs:
            print("⚠️  No channels configured. Set environment variables to enable channels.")
            print("\nRequired environment variables:")
            print("  - TELEGRAM_BOT_TOKEN")
            print("  - SLACK_BOT_TOKEN + SLACK_APP_TOKEN")
            print("  - DISCORD_BOT_TOKEN")
            print("  - WHATSAPP_BRIDGE_URL")
            print("  - SIGNAL_PHONE_NUMBER")
            return

        # 创建管理器
        self.manager = ChannelManager(configs)
        self.manager.on_message = self.handle_message
        self.manager.on_error = self.handle_error

        # 初始化并启动
        await self.manager.initialize()
        await self.manager.start()

        print(f"\n🚀 Bot started with {len(configs)} channel(s)!")
        print("Press Ctrl+C to stop\n")

        # 保持运行
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            print("\n🛑 Stopping bot...")
            await self.manager.stop()
            print("👋 Goodbye!")


async def demo_single_channel():
    """单通道使用示例"""
    from src.channels import TelegramChannel, TelegramConfig

    config = TelegramConfig(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "your-token-here"),
    )

    channel = TelegramChannel(config)

    async def on_message(msg: InboundMessage):
        print(f"Received: {msg.content}")

        # 回复
        reply = OutboundMessage(
            channel="telegram",
            chat_id=msg.chat_id,
            content=f"Echo: {msg.content}",
        )
        await channel.send(reply)

    channel.set_message_handler(on_message)

    await channel.start()
    print("Telegram channel started. Press Ctrl+C to stop.")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await channel.stop()


async def demo_send_message():
    """发送消息示例"""
    from src.channels import TelegramChannel, TelegramConfig, OutboundMessage

    config = TelegramConfig(bot_token="your-token")
    channel = TelegramChannel(config)

    await channel.start()

    # 发送文本消息
    msg = OutboundMessage(
        channel="telegram",
        chat_id="123456789",  # 用户或群组 ID
        content="Hello from virtual-human-sdk!",
        parse_mode="HTML",
    )
    await channel.send(msg)

    # 发送带媒体的消息
    msg_with_media = OutboundMessage(
        channel="telegram",
        chat_id="123456789",
        content="Check out this image!",
        media_paths=["/path/to/image.png"],
    )
    await channel.send(msg_with_media)

    await channel.stop()


if __name__ == "__main__":
    # 运行完整示例
    app = BotApplication()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        pass

"""Telegram 机器人示例

最简单的 Telegram Bot 连接示例。

使用方法:
    1. 在 Telegram 搜索 @BotFather，创建新机器人，获取 Token
    2. 设置环境变量: export TELEGRAM_BOT_TOKEN="your-bot-token"
    3. 运行: python telegram_bot.py

安装依赖:
    pip install -e ".[telegram]"
"""

import asyncio
import os
from src.channels import (
    ChannelManager,
    InboundMessage,
    OutboundMessage,
    TelegramConfig,
)


async def main():
    # 1. 获取 Bot Token
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("❌ 请设置 TELEGRAM_BOT_TOKEN 环境变量")
        print("   export TELEGRAM_BOT_TOKEN='your-bot-token'")
        return

    # 2. 配置 Telegram
    config = TelegramConfig(
        name="my-telegram-bot",
        bot_token=bot_token,
        # allowed_users=["123456789"],  # 可选：限制只允许特定用户
    )

    # 3. 创建管理器
    manager = ChannelManager({"telegram": config})

    # 4. 设置消息处理器
    async def handle_message(message: InboundMessage):
        """处理收到的消息"""
        print(f"\n📨 收到消息:")
        print(f"   来自: {message.sender_name or message.sender_id}")
        print(f"   内容: {message.content}")
        print(f"   聊天类型: {message.chat_type}")

        # 简单的回复逻辑
        user_text = message.content.lower()

        if user_text in ("hello", "hi", "你好"):
            reply = OutboundMessage(
                channel="telegram",
                chat_id=message.chat_id,
                content=f"你好 {message.sender_name or '朋友'}! 👋\n我是你的 AI 助手。",
                reply_to=message.message_id,
            )
            await manager.send("telegram", reply)

        elif user_text == "ping":
            reply = OutboundMessage(
                channel="telegram",
                chat_id=message.chat_id,
                content="Pong! 🏓",
                reply_to=message.message_id,
            )
            await manager.send("telegram", reply)

        elif user_text in ("help", "帮助"):
            help_text = """🤖 可用命令:
/hello, /hi, 你好 - 打招呼
/ping - 测试延迟
/help, 帮助 - 显示帮助
/id - 获取你的用户 ID"""
            reply = OutboundMessage(
                channel="telegram",
                chat_id=message.chat_id,
                content=help_text,
                parse_mode="HTML",
            )
            await manager.send("telegram", reply)

        elif user_text == "id":
            reply = OutboundMessage(
                channel="telegram",
                chat_id=message.chat_id,
                content=f"你的用户 ID: <code>{message.sender_id}</code>",
                parse_mode="HTML",
            )
            await manager.send("telegram", reply)

        else:
            # Echo 回复
            reply = OutboundMessage(
                channel="telegram",
                chat_id=message.chat_id,
                content=f"你说: {message.content}",
                reply_to=message.message_id,
            )
            await manager.send("telegram", reply)

    # 5. 设置错误处理器
    async def handle_error(error: Exception, channel: str):
        print(f"\n❌ [{channel}] 错误: {error}")

    manager.on_message = handle_message
    manager.on_error = handle_error

    # 6. 启动
    print("🚀 启动 Telegram Bot...")
    await manager.initialize()
    await manager.start()

    print("✅ Bot 已启动!")
    print("   在 Telegram 中给你的机器人发送消息进行测试")
    print("   按 Ctrl+C 停止\n")

    # 7. 保持运行
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n🛑 停止 Bot...")
        await manager.stop()
        print("👋 再见!")


if __name__ == "__main__":
    asyncio.run(main())

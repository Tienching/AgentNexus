"""Channel 管理器"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from .base import BaseChannel, ChannelState
from .config import ChannelConfig, ChannelType
from .events import InboundMessage, OutboundMessage
from .registry import get_registry

logger = logging.getLogger(__name__)


class ChannelManager:
    """
    Channel 管理器

    统一管理多个消息通道的生命周期和消息路由。
    统一管理多个消息通道的生命周期和消息路由。

    Usage:
        config = {
            "telegram": TelegramConfig(bot_token="xxx"),
            "slack": SlackConfig(bot_token="xxx", app_token="xxx"),
        }

        manager = ChannelManager(config)

        # 设置消息处理器
        async def handle_message(msg: InboundMessage):
            print(f"收到: {msg.content}")

        manager.on_message = handle_message

        # 启动所有通道
        await manager.initialize()
        await manager.start()

        # 发送消息
        await manager.send("telegram", OutboundMessage(
            channel="telegram",
            chat_id="123456",
            content="Hello!"
        ))

        # 停止
        await manager.stop()
    """

    def __init__(self, configs: Optional[Dict[str, ChannelConfig]] = None):
        self.configs = configs or {}
        self.channels: Dict[str, BaseChannel] = {}
        self._registry = get_registry()
        self._lock = asyncio.Lock()

        # 消息处理器（用户可设置）
        self.on_message: Optional[
            Callable[[InboundMessage], Coroutine[Any, Any, None]]
        ] = None
        self.on_error: Optional[
            Callable[[Exception, str], Coroutine[Any, Any, None]]
        ] = None

    async def initialize(self) -> None:
        """初始化所有配置的通道"""
        for name, config in self.configs.items():
            if not config.enabled:
                logger.info(f"[{name}] Channel is disabled, skipping")
                continue

            channel = self._registry.create(config.type.value, config)
            if channel:
                channel.set_message_handler(self._handle_message)
                channel.set_error_handler(self._handle_error)
                self.channels[name] = channel
                logger.info(f"[{name}] Channel initialized")
            else:
                logger.error(f"[{name}] Failed to create channel")

    async def start(self) -> None:
        """启动所有通道"""
        if not self.channels:
            logger.warning("No channels to start")
            return

        logger.info(f"Starting {len(self.channels)} channels...")

        # 并行启动所有通道
        tasks = []
        for name, channel in self.channels.items():
            task = asyncio.create_task(
                self._start_channel(name, channel),
                name=f"start_{name}"
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 统计结果
        success = sum(1 for r in results if not isinstance(r, Exception))
        failed = len(results) - success

        logger.info(f"Channels started: {success} success, {failed} failed")

    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """启动单个通道（带错误处理）"""
        try:
            await channel.start()
        except Exception as e:
            logger.error(f"[{name}] Failed to start: {e}")
            raise

    async def stop(self) -> None:
        """停止所有通道"""
        if not self.channels:
            return

        logger.info(f"Stopping {len(self.channels)} channels...")

        # 并行停止所有通道
        tasks = []
        for name, channel in list(self.channels.items()):
            task = asyncio.create_task(
                self._stop_channel(name, channel),
                name=f"stop_{name}"
            )
            tasks.append(task)

        await asyncio.gather(*tasks, return_exceptions=True)
        self.channels.clear()

        logger.info("All channels stopped")

    async def _stop_channel(self, name: str, channel: BaseChannel) -> None:
        """停止单个通道（带错误处理）"""
        try:
            await channel.stop()
        except Exception as e:
            logger.error(f"[{name}] Error stopping: {e}")

    async def send(
        self,
        channel_name: str,
        message: OutboundMessage
    ) -> Optional[Any]:
        """
        通过指定通道发送消息

        Args:
            channel_name: 通道名称
            message: 出站消息

        Returns:
            发送结果
        """
        channel = self.channels.get(channel_name)
        if not channel:
            raise ValueError(f"Channel not found: {channel_name}")

        return await channel.send(message)

    async def broadcast(
        self,
        message: OutboundMessage,
        channel_names: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        广播消息到多个通道

        Args:
            message: 出站消息
            channel_names: 目标通道列表（None 表示所有通道）

        Returns:
            各通道的发送结果
        """
        targets = channel_names or list(self.channels.keys())
        results = {}

        async def send_to(name: str) -> None:
            try:
                result = await self.send(name, message)
                results[name] = {"success": True, "result": result}
            except Exception as e:
                results[name] = {"success": False, "error": str(e)}

        await asyncio.gather(
            *[send_to(name) for name in targets],
            return_exceptions=True
        )

        return results

    async def _handle_message(self, message: InboundMessage) -> None:
        """内部消息处理器"""
        if self.on_message:
            try:
                await self.on_message(message)
            except Exception as e:
                logger.error(f"Error in on_message handler: {e}")
                await self._handle_error(e, message.channel)

    async def _handle_error(self, error: Exception, channel_name: str = "unknown") -> None:
        """内部错误处理器"""
        if self.on_error:
            try:
                await self.on_error(error, channel_name)
            except Exception as e:
                logger.error(f"Error in on_error handler: {e}")

    def get_channel(self, name: str) -> Optional[BaseChannel]:
        """获取指定通道实例"""
        return self.channels.get(name)

    def get_channel_info(self) -> List[dict]:
        """获取所有通道信息"""
        return [ch.get_info() for ch in self.channels.values()]

    def is_healthy(self) -> bool:
        """检查所有通道是否健康"""
        if not self.channels:
            return True
        return all(ch.is_running for ch in self.channels.values())

    async def restart_channel(self, name: str) -> None:
        """重启指定通道"""
        channel = self.channels.get(name)
        if not channel:
            raise ValueError(f"Channel not found: {name}")

        logger.info(f"[{name}] Restarting channel...")
        await channel.stop()
        await asyncio.sleep(1)
        await channel.start()
        logger.info(f"[{name}] Channel restarted")

    async def add_channel(self, name: str, config: ChannelConfig) -> None:
        """动态添加通道"""
        async with self._lock:
            if name in self.channels:
                raise ValueError(f"Channel already exists: {name}")

            channel = self._registry.create(config.type.value, config)
            if not channel:
                raise ValueError(f"Failed to create channel: {config.type.value}")

            channel.set_message_handler(self._handle_message)
            channel.set_error_handler(self._handle_error)

            await channel.start()
            self.channels[name] = channel
            self.configs[name] = config

            logger.info(f"[{name}] Channel added and started")

    async def remove_channel(self, name: str) -> None:
        """移除通道"""
        async with self._lock:
            channel = self.channels.pop(name, None)
            if channel:
                await channel.stop()
                self.configs.pop(name, None)
                logger.info(f"[{name}] Channel removed")

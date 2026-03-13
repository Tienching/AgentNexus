"""Channel 基类定义"""

import asyncio
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional

if TYPE_CHECKING:
    from .config import ChannelConfig
    from .events import InboundMessage, OutboundMessage

logger = logging.getLogger(__name__)


class ChannelState(Enum):
    """通道状态"""
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class BaseChannel(ABC):
    """
    消息通道基类

    所有具体通道实现（Telegram, Slack, Discord 等）都应继承此类。
    提供统一的接口。

    Usage:
        class MyChannel(BaseChannel):
            @property
            def channel_type(self) -> str:
                return "my_channel"

            async def _start(self):
                # 启动连接
                pass

            async def _stop(self):
                # 关闭连接
                pass

            async def _send_message(self, msg):
                # 发送消息
                pass
    """

    def __init__(self, config: "ChannelConfig"):
        self.config = config
        self.state = ChannelState.IDLE
        self._message_handler: Optional[
            Callable[["InboundMessage"], Coroutine[Any, Any, None]]
        ] = None
        self._error_handler: Optional[
            Callable[[Exception, str], Coroutine[Any, Any, None]]
        ] = None
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """返回通道类型标识符"""
        pass

    @property
    def name(self) -> str:
        """返回通道名称"""
        return self.config.name or self.channel_type

    @property
    def is_running(self) -> bool:
        """通道是否正在运行"""
        return self.state == ChannelState.RUNNING

    def set_message_handler(
        self,
        handler: Callable[["InboundMessage"], Coroutine[Any, Any, None]]
    ) -> None:
        """设置消息处理器"""
        self._message_handler = handler

    def set_error_handler(
        self,
        handler: Callable[[Exception, str], Coroutine[Any, Any, None]]
    ) -> None:
        """设置错误处理器"""
        self._error_handler = handler

    async def start(self) -> None:
        """启动通道"""
        async with self._lock:
            if self.state == ChannelState.RUNNING:
                logger.warning(f"[{self.name}] Channel already running")
                return

            if self.state == ChannelState.INITIALIZING:
                logger.warning(f"[{self.name}] Channel is initializing")
                return

            self.state = ChannelState.INITIALIZING
            self._stop_event.clear()

        try:
            logger.info(f"[{self.name}] Starting {self.channel_type} channel...")
            await self._start()

            async with self._lock:
                self.state = ChannelState.RUNNING

            logger.info(f"[{self.name}] Channel started successfully")

        except Exception as e:
            async with self._lock:
                self.state = ChannelState.ERROR
            logger.error(f"[{self.name}] Failed to start channel: {type(e).__name__}: {e}", exc_info=True)
            raise

    async def stop(self) -> None:
        """停止通道"""
        async with self._lock:
            if self.state in (ChannelState.IDLE, ChannelState.STOPPING):
                return

            self.state = ChannelState.STOPPING
            self._stop_event.set()

        try:
            logger.info(f"[{self.name}] Stopping {self.channel_type} channel...")
            await self._stop()

            async with self._lock:
                self.state = ChannelState.IDLE

            logger.info(f"[{self.name}] Channel stopped")

        except Exception as e:
            async with self._lock:
                self.state = ChannelState.ERROR
            logger.error(f"[{self.name}] Error stopping channel: {e}")
            raise

    async def send(self, message: "OutboundMessage") -> Optional[Any]:
        """
        发送消息

        Args:
            message: 出站消息

        Returns:
            平台特定的发送结果
        """
        if not self.is_running:
            raise RuntimeError(f"Channel {self.name} is not running")

        if not self.is_allowed(message.chat_id):
            logger.warning(f"[{self.name}] Message to {message.chat_id} is not allowed")
            return None

        try:
            return await self._send_message(message)
        except Exception as e:
            logger.error(f"[{self.name}] Failed to send message: {e}")
            raise

    async def send_typing(self, chat_id: str) -> None:
        """发送输入中指示（可选实现）"""
        return None

    def is_allowed(self, user_id: str) -> bool:
        """
        检查用户是否被允许访问

        Args:
            user_id: 用户 ID

        Returns:
            是否允许访问
        """
        # 检查黑名单
        if user_id in self.config.blocked_users:
            return False

        # 检查白名单（空列表表示允许所有）
        if self.config.allowed_users and user_id not in self.config.allowed_users:
            return False

        return True

    async def _handle_inbound_message(self, message: "InboundMessage") -> None:
        """
        处理入站消息（内部方法）

        Args:
            message: 入站消息
        """
        # 检查用户权限
        if not self.is_allowed(message.sender_id):
            logger.debug(f"[{self.name}] Ignoring message from unauthorized user: {message.sender_id}")
            return

        # 调用用户设置的消息处理器
        if self._message_handler:
            try:
                await self._message_handler(message)
            except Exception as e:
                logger.error(f"[{self.name}] Error in message handler: {e}")
                if self._error_handler:
                    await self._error_handler(e, self.channel_type)
        else:
            logger.warning(f"[{self.name}] No message handler set, dropping message")

    async def _handle_error(self, error: Exception) -> None:
        """处理错误（内部方法）"""
        logger.error(f"[{self.name}] Channel error: {error}")
        if self._error_handler:
            try:
                await self._error_handler(error, self.channel_type)
            except Exception as e:
                logger.error(f"[{self.name}] Error in error handler: {e}")

    # ============== 抽象方法（子类必须实现） ==============

    @abstractmethod
    async def _start(self) -> None:
        """启动通道的具体实现"""
        pass

    @abstractmethod
    async def _stop(self) -> None:
        """停止通道的具体实现"""
        pass

    @abstractmethod
    async def _send_message(self, message: "OutboundMessage") -> Optional[Any]:
        """发送消息的具体实现"""
        pass

    # ============== 可选重写方法 ==============

    async def health_check(self) -> bool:
        """健康检查，返回通道是否健康"""
        return self.is_running

    def get_info(self) -> dict:
        """获取通道信息"""
        return {
            "type": self.channel_type,
            "name": self.name,
            "state": self.state.value,
            "enabled": self.config.enabled,
        }

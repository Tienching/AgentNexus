"""Channel 注册表"""

import logging
from typing import TYPE_CHECKING, Dict, Optional, Type

if TYPE_CHECKING:
    from .base import BaseChannel
    from .config import ChannelConfig, ChannelType

logger = logging.getLogger(__name__)


class ChannelRegistry:
    """
    Channel 注册表

    管理所有可用的通道类型，支持动态注册和获取。
    参考 openclaw 的 registry 模式。

    Usage:
        registry = ChannelRegistry()

        # 注册自定义通道
        registry.register("custom", CustomChannel)

        # 创建通道实例
        channel = registry.create("telegram", config)
    """

    def __init__(self):
        self._channels: Dict[str, Type["BaseChannel"]] = {}
        self._register_builtin()

    def _register_builtin(self) -> None:
        """注册内置通道类型（延迟导入）"""
        # 延迟导入避免强制依赖
        pass  # 在 get 方法中动态导入

    def register(self, type_: str, channel_class: Type["BaseChannel"]) -> None:
        """
        注册通道类型

        Args:
            type_: 通道类型标识符
            channel_class: 通道类
        """
        self._channels[type_] = channel_class
        logger.debug(f"Registered channel type: {type_}")

    def unregister(self, type_: str) -> None:
        """注销通道类型"""
        if type_ in self._channels:
            del self._channels[type_]
            logger.debug(f"Unregistered channel type: {type_}")

    def get(self, type_: str) -> Optional[Type["BaseChannel"]]:
        """
        获取通道类

        Args:
            type_: 通道类型标识符

        Returns:
            通道类或 None
        """
        # 先检查已注册的
        if type_ in self._channels:
            return self._channels[type_]

        # 动态导入内置通道
        channel_class = self._import_builtin(type_)
        if channel_class:
            self._channels[type_] = channel_class
            return channel_class

        return None

    def _import_builtin(self, type_: str) -> Optional[Type["BaseChannel"]]:
        """动态导入内置通道"""
        try:
            if type_ == "telegram":
                from .telegram import TelegramChannel
                return TelegramChannel
            elif type_ == "slack":
                from .slack import SlackChannel
                return SlackChannel
            elif type_ == "discord":
                from .discord import DiscordChannel
                return DiscordChannel
            elif type_ == "whatsapp":
                from .whatsapp import WhatsAppChannel
                return WhatsAppChannel
            elif type_ == "signal":
                from .signal_ import SignalChannel
                return SignalChannel
            elif type_ == "feishu":
                from .feishu import FeishuChannel
                return FeishuChannel
            elif type_ == "wecom":
                from .wecom_aibot import WeComChannel
                return WeComChannel
            elif type_ == "wecom_bot":
                from .wecom_bot import WeComBotChannel
                return WeComBotChannel
            elif type_ == "wechat":
                from .wechat import WeChatChannel
                return WeChatChannel
        except ImportError as e:
            logger.warning(f"Failed to import {type_} channel: {e}")
        return None

    def create(self, type_: str, config: "ChannelConfig") -> Optional["BaseChannel"]:
        """
        创建通道实例

        Args:
            type_: 通道类型标识符
            config: 通道配置

        Returns:
            通道实例或 None
        """
        channel_class = self.get(type_)
        if not channel_class:
            logger.error(f"Unknown channel type: {type_}")
            return None

        try:
            return channel_class(config)
        except Exception as e:
            logger.error(f"Failed to create {type_} channel: {e}")
            return None

    def list_available(self) -> list:
        """列出所有可用通道类型"""
        available = []
        for type_ in ["telegram", "slack", "discord", "whatsapp", "signal", "feishu", "wecom", "wecom_bot", "wechat"]:
            if self._import_builtin(type_):
                available.append(type_)
        return available

    def is_available(self, type_: str) -> bool:
        """检查通道类型是否可用"""
        return self.get(type_) is not None


# 全局注册表实例
_default_registry: Optional[ChannelRegistry] = None


def get_registry() -> ChannelRegistry:
    """获取全局注册表实例"""
    global _default_registry
    if _default_registry is None:
        _default_registry = ChannelRegistry()
    return _default_registry

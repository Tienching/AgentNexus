# -*- coding: utf-8 -*-
"""
Channel 注册表
"""

from typing import Optional, Dict, List


class ChannelRegistry:
    """Channel 注册表"""
    
    _instance: Optional["ChannelRegistry"] = None
    
    def __new__(cls) -> "ChannelRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._channels = {}
            cls._instance._enabled = set()
        return cls._instance
    
    def register(self, name: str, channel: "Channel") -> None:
        """注册 Channel"""
        self._channels[name] = channel
    
    def get(self, name: str) -> Optional["Channel"]:
        """获取 Channel"""
        return self._channels.get(name)
    
    def enable(self, name: str) -> bool:
        """启用 Channel"""
        if name in self._channels:
            self._enabled.add(name)
            return True
        return False
    
    def disable(self, name: str) -> bool:
        """禁用 Channel"""
        if name in self._enabled:
            self._enabled.discard(name)
            return True
        return False
    
    def is_enabled(self, name: str) -> bool:
        """检查是否启用"""
        return name in self._enabled
    
    def list_all(self) -> List[str]:
        """列出所有已注册的 Channel"""
        return list(self._channels.keys())
    
    def list_enabled(self) -> List[str]:
        """列出已启用的 Channel"""
        return [name for name in self._channels if name in self._enabled]


# 全局单例
_registry: Optional[ChannelRegistry] = None


def get_channel_registry() -> ChannelRegistry:
    """获取全局 Channel 注册表"""
    global _registry
    if _registry is None:
        _registry = ChannelRegistry()
    return _registry

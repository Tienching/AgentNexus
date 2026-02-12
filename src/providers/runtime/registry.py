# -*- coding: utf-8 -*-
"""
Provider 注册表
"""

from typing import Optional, Dict, Type, Any
from dataclasses import dataclass

from .base import Provider


@dataclass
class ProviderResolution:
    """Provider 解析结果"""
    provider_name: str
    source: str  # "explicit" | "session" | "default"


class ProviderRegistry:
    """Provider 注册表 - 单例"""
    
    _instance: Optional["ProviderRegistry"] = None
    _providers: Dict[str, Provider]
    _default_provider: str
    
    def __new__(cls) -> "ProviderRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._providers = {}
            cls._instance._default_provider = "codebuddy"
        return cls._instance
    
    def register(self, name: str, provider: Provider) -> None:
        """注册 Provider"""
        self._providers[name] = provider
    
    def get(self, name: str) -> Optional[Provider]:
        """按名称获取 Provider"""
        return self._providers.get(name)
    
    def get_or_default(self, name: Optional[str] = None) -> Provider:
        """获取指定或默认 Provider"""
        provider_name = name or self._default_provider
        provider = self._providers.get(provider_name)
        if not provider:
            # fallback to default
            provider = self._providers.get(self._default_provider)
        if not provider:
            raise ValueError(f"Provider '{provider_name}' not found and no default available")
        return provider
    
    def resolve_provider(
        self,
        explicit: Optional[str] = None,
        session_meta: Optional[dict] = None,
    ) -> ProviderResolution:
        """解析 Provider（优先级：显式 > session > 默认）"""
        if explicit:
            return ProviderResolution(provider_name=explicit, source="explicit")
        
        if session_meta and session_meta.get("provider"):
            return ProviderResolution(
                provider_name=session_meta["provider"],
                source="session"
            )
        
        return ProviderResolution(
            provider_name=self._default_provider,
            source="default"
        )
    
    def list_providers(self) -> list[str]:
        """列出可用 Provider。

        为了与现有系统兼容，即使尚未注册具体 Provider 实例，也会暴露内置名称。
        """
        names = set(self._providers.keys())
        names.update({
            "claude",
            "gemini",
            "codex",
            "codebuddy",
        })
        return sorted(names)
    
    def set_default(self, name: str) -> None:
        """设置默认 Provider"""
        if name not in self.list_providers():
            raise ValueError(f"Provider '{name}' not available")
        self._default_provider = name
    
    @property
    def default_provider(self) -> str:
        return self._default_provider


# 全局单例
_registry: Optional[ProviderRegistry] = None


def get_provider_registry() -> ProviderRegistry:
    """获取全局 Provider 注册表"""
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry

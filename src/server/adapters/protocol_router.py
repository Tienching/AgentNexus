# -*- coding: utf-8 -*-
"""协议路由和检测

统一使用 AG-UI 协议
"""

from typing import Optional, Dict, Any
from fastapi import Request

from src.runtime.adapters import ProtocolType, BaseAdapter


# AG-UI 协议的 Accept header
AGUI_ACCEPT_HEADER = "application/x-agui-stream"
AGUI_CONTENT_TYPE = "text/event-stream"


def detect_protocol(
    request: Request,
    query_params: Optional[Dict[str, Any]] = None
) -> ProtocolType:
    """
    检测请求使用的协议类型
    
    统一使用 AG-UI 协议
    
    Args:
        request: FastAPI 请求对象
        query_params: 查询参数字典
        
    Returns:
        ProtocolType.AGUI
    """
    return ProtocolType.AGUI


def detect_protocol_from_body(body: Dict[str, Any]) -> ProtocolType:
    """
    从请求体检测协议类型
    
    统一使用 AG-UI 协议
    
    Args:
        body: 请求体字典
        
    Returns:
        ProtocolType.AGUI
    """
    return ProtocolType.AGUI


class ProtocolRouter:
    """协议路由器"""
    
    def __init__(self):
        self._adapters: Dict[ProtocolType, type] = {}
    
    def register(self, protocol: ProtocolType, adapter_class: type) -> None:
        """
        注册协议适配器
        
        Args:
            protocol: 协议类型
            adapter_class: 适配器类
        """
        self._adapters[protocol] = adapter_class
    
    def get_adapter(self, protocol: ProtocolType) -> BaseAdapter:
        """
        获取协议适配器实例
        
        Args:
            protocol: 协议类型
            
        Returns:
            适配器实例
            
        Raises:
            ValueError: 未注册的协议类型
        """
        if protocol not in self._adapters:
            raise ValueError(f"Unknown protocol: {protocol}")
        
        return self._adapters[protocol]()
    
    def get_adapter_for_request(
        self, 
        request: Request,
        body: Optional[Dict[str, Any]] = None
    ) -> BaseAdapter:
        """
        根据请求获取适配器
        
        统一返回 AGUI 适配器
        
        Args:
            request: FastAPI 请求对象
            body: 请求体（可选）
            
        Returns:
            AGUI 适配器实例
        """
        return self.get_adapter(ProtocolType.AGUI)


# 全局路由器实例
_router: Optional[ProtocolRouter] = None


def get_router() -> ProtocolRouter:
    """获取全局路由器实例"""
    global _router
    if _router is None:
        _router = ProtocolRouter()
        # 延迟导入避免循环依赖
        from src.runtime.adapters import AGUIAdapter
        _router.register(ProtocolType.AGUI, AGUIAdapter)
    return _router


def reset_router() -> None:
    """重置全局路由器实例（用于测试）"""
    global _router
    _router = None

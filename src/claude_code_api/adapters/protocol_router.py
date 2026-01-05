"""协议路由和检测"""

from enum import Enum
from typing import Optional, Dict, Any
from fastapi import Request

from .base_adapter import ProtocolType, BaseAdapter


# AG-UI 协议的 Accept header
AGUI_ACCEPT_HEADER = "application/x-agui-stream"
AGUI_CONTENT_TYPE = "text/event-stream"


def detect_protocol(
    request: Request,
    query_params: Optional[Dict[str, Any]] = None
) -> ProtocolType:
    """
    检测请求使用的协议类型
    
    检测优先级：
    1. 查询参数 ?protocol=agui
    2. Accept header: application/x-agui-stream
    3. 请求体中包含 AG-UI 特征字段 (threadId, runId, messages)
    4. 默认使用 Legacy 协议（向后兼容）
    
    Args:
        request: FastAPI 请求对象
        query_params: 查询参数字典
        
    Returns:
        检测到的协议类型
    """
    # 1. 检查查询参数
    if query_params:
        protocol = query_params.get("protocol", "").lower()
        if protocol == "agui":
            return ProtocolType.AGUI
    
    # 也检查 request.query_params
    if hasattr(request, "query_params"):
        protocol = request.query_params.get("protocol", "").lower()
        if protocol == "agui":
            return ProtocolType.AGUI
    
    # 2. 检查 Accept header
    accept_header = request.headers.get("accept", "")
    if AGUI_ACCEPT_HEADER in accept_header.lower():
        return ProtocolType.AGUI
    
    # 3. 检查 X-Protocol header（自定义header）
    x_protocol = request.headers.get("x-protocol", "").lower()
    if x_protocol == "agui":
        return ProtocolType.AGUI
    
    # 4. 默认使用 Legacy 协议
    return ProtocolType.LEGACY


def detect_protocol_from_body(body: Dict[str, Any]) -> ProtocolType:
    """
    从请求体检测协议类型
    
    AG-UI 请求特征：
    - 包含 threadId 和 runId 字段
    - 包含 messages 数组
    - 包含 forwardedProps 对象
    
    Args:
        body: 请求体字典
        
    Returns:
        检测到的协议类型
    """
    # AG-UI 特征字段
    agui_fields = {"threadId", "runId", "messages"}
    
    # 检查是否包含 AG-UI 特征字段
    if agui_fields.issubset(body.keys()):
        return ProtocolType.AGUI
    
    # 检查是否包含部分 AG-UI 字段
    if "threadId" in body and "messages" in body:
        return ProtocolType.AGUI
    
    # 默认 Legacy
    return ProtocolType.LEGACY


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
        
        Args:
            request: FastAPI 请求对象
            body: 请求体（可选）
            
        Returns:
            适配器实例
        """
        # 先从 header/query 检测
        protocol = detect_protocol(request)
        
        # 如果是 Legacy，再从 body 检测
        if protocol == ProtocolType.LEGACY and body:
            protocol = detect_protocol_from_body(body)
        
        return self.get_adapter(protocol)


# 全局路由器实例
_router: Optional[ProtocolRouter] = None


def get_router() -> ProtocolRouter:
    """获取全局路由器实例"""
    global _router
    if _router is None:
        _router = ProtocolRouter()
        # 延迟导入避免循环依赖
        from .agui_adapter import AGUIAdapter
        from .legacy_adapter import LegacyAdapter
        _router.register(ProtocolType.AGUI, AGUIAdapter)
        _router.register(ProtocolType.LEGACY, LegacyAdapter)
    return _router

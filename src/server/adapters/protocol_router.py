# -*- coding: utf-8 -*-
"""协议检测工具函数

统一使用 AG-UI 协议，保留 detect 函数供路由层调用。
"""

from typing import Optional, Dict, Any

from fastapi import Request

from src.runtime.adapters import ProtocolType


# AG-UI 协议常量
AGUI_ACCEPT_HEADER = "application/x-agui-stream"
AGUI_CONTENT_TYPE = "text/event-stream"


def detect_protocol(
    request: Request,
    query_params: Optional[Dict[str, Any]] = None,
) -> ProtocolType:
    """检测请求使用的协议类型（统一返回 AG-UI）。"""
    return ProtocolType.AGUI


def detect_protocol_from_body(body: Dict[str, Any]) -> ProtocolType:
    """从请求体检测协议类型（统一返回 AG-UI）。"""
    return ProtocolType.AGUI

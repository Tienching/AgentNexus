# -*- coding: utf-8 -*-
"""Health check and metrics router"""

from fastapi import APIRouter

from src.providers.claude_code_api.models import HealthResponse, MetricsResponse
from ..config import settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    健康检查接口

    用于监控服务状态
    """
    return HealthResponse(
        status="healthy", service="claude-code-api", version="0.1.0"
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    """
    获取服务指标

    返回请求统计等信息
    """
    # 从全局 metrics 获取数据
    from ..app import metrics
    
    return MetricsResponse(
        version="0.1.0",
        ccr_command=settings.ccr_command,
        requests_total=metrics["requests_total"],
        requests_active=metrics["requests_active"],
    )


@router.get("/")
async def root():
    """根路径"""
    return {
        "service": "Claude Code API",
        "version": "0.1.0",
        "status": "running",
        "endpoints": {
            "chat": "/chat/stream/{agent_name}",
            "health": "/health",
            "metrics": "/metrics",
            "docs": "/docs",
            "redoc": "/redoc",
        },
        "description": {
            "/chat/stream/{agent_name}": "统一SSE接口（自动检测协议类型：易事厅/AG-UI）",
            "agent_name": "URL路径参数，Linux系统用户名，用于执行命令",
            "api_user": "请求体中的user字段，用于创建工作目录/home/{agent_name}/{api_user}"
        },
        "protocols": {
            "legacy": "易事厅格式（默认）",
            "agui": "AG-UI协议（通过?protocol=agui或Accept: application/x-agui-stream启用）"
        }
    }

# -*- coding: utf-8 -*-
"""Health check and metrics router"""

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from ..models import HealthResponse, MetricsResponse
from ..config import settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    健康检查接口

    用于监控服务状态
    """
    return HealthResponse(
        status="healthy", service="agent-nexus", version="0.1.0"
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
        cli_command=settings.cli_command,
        requests_total=metrics["requests_total"],
        requests_active=metrics["requests_active"],
    )


@router.get("/nexus")
@router.get("/nexus/")
async def nexus_redirect():
    """旧路径兼容 — /nexus 重定向到根路径"""
    return RedirectResponse(url="/")

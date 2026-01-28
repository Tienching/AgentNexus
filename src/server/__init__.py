# -*- coding: utf-8 -*-
"""Agent Runtime Server Package

提供通用的 FastAPI 服务器基础设施，包括：
- config: 服务器配置
- logger: 日志系统
- middleware: 中间件（Correlation ID 等）
- routers: HTTP 路由
- services: 服务层
"""

from .config import Settings, ServerSettings, ProviderSettings, settings
from .logger import (
    setup_logger,
    get_logger,
    generate_correlation_id,
    set_correlation_id,
    get_correlation_id,
    RequestLogger,
    JsonFormatter,
    HumanReadableFormatter,
)
from .middleware import CorrelationMiddleware

__all__ = [
    # Config
    "Settings",
    "ServerSettings",
    "ProviderSettings",
    "settings",
    # Logger
    "setup_logger",
    "get_logger",
    "generate_correlation_id",
    "set_correlation_id",
    "get_correlation_id",
    "RequestLogger",
    "JsonFormatter",
    "HumanReadableFormatter",
    # Middleware
    "CorrelationMiddleware",
]

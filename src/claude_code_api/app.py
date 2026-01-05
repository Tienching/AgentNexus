# -*- coding: utf-8 -*-
"""FastAPI Application Entry Point"""

import time
import json
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import ValidationError

from .config import settings
from .middleware import CorrelationMiddleware
from .routers import chat_router, health_router
from .logger import setup_logger, get_logger

# 全局变量用于存储指标
metrics = {
    "requests_total": 0,
    "requests_active": 0,
    "start_time": time.time(),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    setup_logger(
        log_level=settings.log_level,
        log_dir=settings.log_dir,
        log_max_bytes=settings.log_max_bytes,
        log_backup_count=settings.log_backup_count,
        use_human_readable=(settings.environment == "development"),
    )
    logger = get_logger(__name__)
    logger.info(
        f"Starting Claude Code API v{app.version} "
        f"on {settings.api_host}:{settings.api_port}"
    )
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"CCR command: {settings.ccr_command}")

    yield

    # 关闭时
    logger.info("Shutting down Claude Code API")


# 创建FastAPI应用
app = FastAPI(
    title="Claude Code API",
    description="Stream API wrapper for ccr code CLI",
    version="0.1.0",
    lifespan=lifespan,
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加关联ID中间件
app.add_middleware(CorrelationMiddleware, metrics=metrics)

# 注册路由
app.include_router(health_router)
app.include_router(chat_router)

# 获取日志器
logger = get_logger(__name__)


# ============ 异常处理器 ============

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """通用异常处理器"""
    request_info = {
        "path": request.url.path,
        "method": request.method,
        "query_params": dict(request.query_params),
        "error_type": type(exc).__name__,
    }

    logger.error(
        f"Unhandled exception: {str(exc)}",
        exc_info=True,
        extra=request_info,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
        }
    )


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """验证异常处理器"""
    request_info = {
        "path": request.url.path,
        "method": request.method,
        "validation_errors": exc.errors(),
    }

    logger.error(
        f"Validation error on {request.method} {request.url.path}",
        extra=request_info,
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation error",
            "details": exc.errors(),
            "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
        }
    )

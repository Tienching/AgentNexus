# -*- coding: utf-8 -*-
"""FastAPI Application Entry Point"""

import time
import json
from typing import Optional
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import ValidationError

from .config import settings
from .middleware import CorrelationMiddleware
from .routers import chat_router, health_router
from .logger import setup_logger, get_logger
from .services import (
    TaskQueue,
    TaskExecutor,
    create_and_start_executor,
    get_executor,
)
from .models.task_models import Task

# 全局变量用于存储指标
metrics = {
    "requests_total": 0,
    "requests_active": 0,
    "start_time": time.time(),
}

# 全局任务队列
_task_queue: Optional[TaskQueue] = None


async def task_handler(task: Task) -> Optional[str]:
    """任务执行处理函数
    
    执行任务并返回错误消息（如果有）。
    返回 None 表示成功，返回字符串表示失败原因。
    """
    from .services import CCRExecutor
    from .models import RequestModel
    import asyncio
    
    logger = get_logger(__name__)
    
    # 使用任务中存储的 agent_name
    agent_name = task.agent_name or "ubuntu"
    logger.info(f"Executing task {task.id} for agent {agent_name}: {task.description[:50]}...")
    
    try:
        # 创建 CCR 执行器
        executor = CCRExecutor()
        
        # 构建请求模型
        request = RequestModel(
            content=task.description,
            user=task.project_id or "task_executor",  # 使用 project_id 作为用户标识
            session_id=f"task_{task.id}",
        )
        
        # 收集所有输出
        output_lines = []
        async for output in executor.execute(request, agent_name, output_format="raw"):
            output_lines.append(output)
            # 检查是否有错误
            try:
                data = json.loads(output)
                if data.get("type") == "error":
                    return data.get("message", "Unknown error")
            except json.JSONDecodeError:
                pass
        
        logger.info(f"Task {task.id} completed successfully")
        return None  # 成功
        
    except asyncio.CancelledError:
        logger.warning(f"Task {task.id} was cancelled")
        raise
    except Exception as e:
        logger.error(f"Task {task.id} failed: {e}", exc_info=True)
        return str(e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global _task_queue
    
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
    
    # 启动任务执行器
    executor = None
    if settings.executor_enabled:
        try:
            import os
            # 默认使用 ubuntu agent（与路由 /chat/stream/ubuntu 对应）
            agent_name = os.environ.get("AGENT_NAME", "ubuntu")
            
            # 初始化任务队列
            _task_queue = TaskQueue(agent_name=agent_name)
            
            # 创建并启动执行器
            executor = await create_and_start_executor(
                task_queue=_task_queue,
                task_handler=task_handler,
            )
            logger.info(f"Task executor started for agent: {agent_name}")
        except Exception as e:
            logger.error(f"Failed to start task executor: {e}", exc_info=True)

    yield

    # 关闭时
    if executor:
        try:
            await executor.stop()
            logger.info("Task executor stopped")
        except Exception as e:
            logger.error(f"Error stopping task executor: {e}")
    
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

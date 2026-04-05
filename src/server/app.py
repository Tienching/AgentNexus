# -*- coding: utf-8 -*-
"""FastAPI Application Entry Point"""

import os
import time
from typing import Any, Optional
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pydantic import ValidationError

from .config import settings
from .middleware import CorrelationMiddleware
from .routers import chat_router, health_router, channels_router
from .routers.nexus import router as nexus_router
from .routers.nexus_admin import router as nexus_admin_router
from .routers.nexus_auth import router as nexus_auth_router
from .routers.nexus_history import router as nexus_history_router
from .routers.nexus_ops import router as nexus_ops_router
from .routers.nexus_schedules import router as nexus_schedules_router
from .routers.nexus_security import router as nexus_security_router
from .routers.nexus_system import router as nexus_system_router
from .routers.nexus_terminal import router as nexus_terminal_router
from .routers.nexus_utils import router as nexus_utils_router
from .routers.nexus_runs import router as nexus_runs_router
from .routers.nexus_runtimes import router as nexus_runtimes_router
from .routers.nexus_missions import router as nexus_missions_router
from .routers.nexus_evolution import router as nexus_evolution_router
from .logger import setup_logger, get_logger
from .services import (
    TaskQueue,
    TaskExecutor,
    create_and_start_executor,
    get_executor,
)
from src.runtime import __version__ as runtime_version
from src.runtime.models.task_models import ExecutorConfig
from .models import Task

# 全局变量用于存储指标
metrics = {
    "requests_total": 0,
    "requests_active": 0,
    "start_time": time.time(),
}

# 全局任务队列
_task_queue: Optional[TaskQueue] = None

# Ralph Loop: sentinel returned by task_handler to signal re-queue (not an error)
RALPH_LOOP_RETRY_SIGNAL = "__RALPH_LOOP_RETRY__"


STARTUP_SUBSYSTEMS = {
    "task_executor": "Task Executor",
    "task_scheduler": "Task Scheduler",
    "channel_service": "Channel Service",
    "terminal_manager": "Terminal Manager",
    "evolution_service": "Evolution Service",
}


def _record_startup_state(
    app: FastAPI,
    subsystem: str,
    *,
    status: str,
    message: str,
    required: bool,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    startup_subsystems = getattr(app.state, "startup_subsystems", None)
    if startup_subsystems is None:
        startup_subsystems = {}
        app.state.startup_subsystems = startup_subsystems

    startup_subsystems[subsystem] = {
        "name": STARTUP_SUBSYSTEMS[subsystem],
        "status": status,
        "message": message,
        "required": required,
        "detail": detail or {},
    }


async def task_handler(task: Task) -> Optional[str]:
    """Thin wrapper — delegates to :func:`task_execution_service.execute_task`.

    Passes the module-level ``_task_queue`` so the service can persist
    CLI session IDs and handle Ralph Loop re-queue signalling.
    """
    from .services.task_execution_service import execute_task
    return await execute_task(task, task_queue=_task_queue)


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
        f"Starting Agent Nexus v{app.version} "
        f"on {settings.api_host}:{settings.api_port}"
    )
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"CLI command: {settings.cli_command}")
    app.state.startup_subsystems = {}
    
    # 启动任务执行器
    executor = None
    exec_user = os.environ.get("EXEC_USER", "ubuntu")
    if settings.executor_enabled:
        try:
            # 初始化任务队列
            _task_queue = TaskQueue(exec_user=exec_user)

            # 创建执行器配置（从 Redis 加载并发限制）
            from src.runtime.stores.concurrency_config import get_concurrency_config_store
            concurrency_store = get_concurrency_config_store()
            concurrency_cfg = concurrency_store.get_all()

            executor_config = ExecutorConfig(
                global_max_concurrency=concurrency_cfg.get("global_max_concurrency", 0) or settings.executor_default_max_concurrency,
                provider_concurrency=concurrency_cfg.get("provider_concurrency", {}),
                poll_interval=settings.executor_poll_interval,
                max_retries=settings.executor_max_retries,
                retry_delay=settings.executor_retry_delay,
                task_timeout=settings.executor_task_timeout,
            )

            # 创建并启动执行器
            executor = await create_and_start_executor(
                task_queue=_task_queue,
                task_handler=task_handler,
                config=executor_config,
            )
            logger.info(f"Task executor started for exec_user: {exec_user}")
            _record_startup_state(
                app,
                "task_executor",
                status="healthy",
                message=f"Started for exec_user: {exec_user}",
                required=True,
                detail={"exec_user": exec_user},
            )
        except Exception as e:
            logger.error(f"Failed to start task executor: {e}", exc_info=True)
            _record_startup_state(
                app,
                "task_executor",
                status="unhealthy",
                message=f"Startup failed: {e}",
                required=True,
                detail={"error": str(e), "exception_type": type(e).__name__},
            )
    else:
        _record_startup_state(
            app,
            "task_executor",
            status="disabled",
            message="Disabled by configuration",
            required=False,
            detail={"enabled": False},
        )

    # 启动定时调度器 (Cron Scheduler)
    scheduler = None
    if not settings.scheduler_enabled:
        _record_startup_state(
            app,
            "task_scheduler",
            status="disabled",
            message="Disabled by configuration",
            required=False,
            detail={"enabled": False},
        )
    elif not settings.executor_enabled:
        _record_startup_state(
            app,
            "task_scheduler",
            status="unhealthy",
            message="Startup blocked: task executor is disabled",
            required=True,
            detail={"dependency": "task_executor", "reason": "executor_disabled"},
        )
    elif not _task_queue:
        _record_startup_state(
            app,
            "task_scheduler",
            status="unhealthy",
            message="Startup blocked: task executor failed to start",
            required=True,
            detail={"dependency": "task_executor", "reason": "executor_startup_failed"},
        )
    else:
        try:
            from .services.schedule_storage import ScheduleStorage
            from src.runtime.execution.scheduler import create_and_start_scheduler

            schedule_storage = ScheduleStorage(exec_user=exec_user)
            scheduler = await create_and_start_scheduler(
                schedule_storage=schedule_storage,
                task_queue=_task_queue,
                poll_interval=settings.scheduler_poll_interval,
            )
            logger.info(f"Task scheduler started (poll_interval={settings.scheduler_poll_interval}s)")
            _record_startup_state(
                app,
                "task_scheduler",
                status="healthy",
                message=f"Started (poll_interval={settings.scheduler_poll_interval}s)",
                required=True,
                detail={"poll_interval_seconds": settings.scheduler_poll_interval},
            )
        except Exception as e:
            logger.error(f"Failed to start task scheduler: {e}", exc_info=True)
            _record_startup_state(
                app,
                "task_scheduler",
                status="unhealthy",
                message=f"Startup failed: {e}",
                required=True,
                detail={"error": str(e), "exception_type": type(e).__name__},
            )

    # 启动 Channel 服务（Telegram, Slack, Discord 等）
    channel_service = None
    try:
        from .services.channel_service import create_channel_service
        channel_service = await create_channel_service()
        if channel_service:
            await channel_service.start()
            logger.info("Channel service started")
            _record_startup_state(
                app,
                "channel_service",
                status="healthy",
                message="Started",
                required=True,
                detail={"configured": True},
            )
        else:
            _record_startup_state(
                app,
                "channel_service",
                status="disabled",
                message="No channels configured",
                required=False,
                detail={"configured": False},
            )
    except ImportError as e:
        logger.debug(f"Channel service not available: {e}")
        _record_startup_state(
            app,
            "channel_service",
            status="unhealthy",
            message=f"Startup failed: {e}",
            required=True,
            detail={"error": str(e), "exception_type": type(e).__name__},
        )
    except Exception as e:
        logger.warning(f"Failed to start channel service: {e}")
        _record_startup_state(
            app,
            "channel_service",
            status="unhealthy",
            message=f"Startup failed: {e}",
            required=True,
            detail={"error": str(e), "exception_type": type(e).__name__},
        )

    # 初始化 Terminal Manager (Web Terminal via tmux)
    terminal_manager = None
    try:
        from .services.terminal_manager import TerminalManager
        from .routers.nexus_terminal import set_terminal_manager
        terminal_manager = TerminalManager()
        set_terminal_manager(terminal_manager)
        logger.info("Terminal manager initialized")
        _record_startup_state(
            app,
            "terminal_manager",
            status="healthy",
            message="Initialized",
            required=True,
            detail={},
        )
    except Exception as e:
        logger.warning(f"Failed to initialize terminal manager: {e}")
        _record_startup_state(
            app,
            "terminal_manager",
            status="unhealthy",
            message=f"Startup failed: {e}",
            required=True,
            detail={"error": str(e), "exception_type": type(e).__name__},
        )

    # 启动自我进化系统（如果启用）
    evolution_service = None
    if settings.evolution_enabled:
        try:
            from .services.evolution_service import EvolutionService
            evolution_service = EvolutionService.create()
            await evolution_service.start()
            logger.info("Evolution service started")
            # Expose to routers via app state
            app.state.evolution_service = evolution_service
            _record_startup_state(
                app,
                "evolution_service",
                status="healthy",
                message="Started",
                required=True,
                detail={"enabled": True},
            )
        except Exception as e:
            logger.warning(f"Failed to start evolution service: {e}")
            _record_startup_state(
                app,
                "evolution_service",
                status="unhealthy",
                message=f"Startup failed: {e}",
                required=True,
                detail={"error": str(e), "exception_type": type(e).__name__},
            )
    else:
        _record_startup_state(
            app,
            "evolution_service",
            status="disabled",
            message="Disabled by configuration",
            required=False,
            detail={"enabled": False},
        )

    startup_subsystems = getattr(app.state, "startup_subsystems", {})
    required_startup_failures = []
    for subsystem, state in startup_subsystems.items():
        if not state or not state.get("required"):
            continue

        subsystem_status = str(state.get("status", "unknown"))
        if subsystem_status in {"healthy", "disabled"}:
            continue

        subsystem_name = str(state.get("name") or subsystem)
        subsystem_message = str(state.get("message") or "")
        required_startup_failures.append(
            f"{subsystem_name} ({subsystem_status})"
            if not subsystem_message
            else f"{subsystem_name} ({subsystem_status}): {subsystem_message}"
        )

    try:
        if required_startup_failures:
            logger.error(
                "Required startup subsystems failed; refusing to start API",
                extra={"startup_failures": required_startup_failures},
            )
            raise RuntimeError(
                "Required startup subsystems failed: "
                + "; ".join(required_startup_failures)
            )

        yield
    finally:
        # 关闭时
        # 停止自我进化系统
        if evolution_service:
            try:
                await evolution_service.stop()
                logger.info("Evolution service stopped")
            except Exception as e:
                logger.error(f"Error stopping evolution service: {e}")

        # 停止 Terminal Manager
        if terminal_manager:
            try:
                terminal_manager.cleanup_all()
                logger.info("Terminal manager stopped")
            except Exception as e:
                logger.error(f"Error stopping terminal manager: {e}")

        # 停止 Channel 服务
        if channel_service:
            try:
                await channel_service.stop()
                logger.info("Channel service stopped")
            except Exception as e:
                logger.error(f"Error stopping channel service: {e}")

        # 停止定时调度器
        if scheduler:
            try:
                await scheduler.stop()
                logger.info("Task scheduler stopped")
            except Exception as e:
                logger.error(f"Error stopping task scheduler: {e}")

        if executor:
            try:
                await executor.stop()
                logger.info("Task executor stopped")
            except Exception as e:
                logger.error(f"Error stopping task executor: {e}")
        
        logger.info("Shutting down Agent Nexus")


# 创建FastAPI应用
app = FastAPI(
    title="Agent Nexus",
    description="Multi-provider CLI wrapper with AG-UI SSE streaming",
    version=runtime_version,
    lifespan=lifespan,
)

# 配置CORS
# 注意: allow_credentials=True 时不能使用 allow_origins=["*"]，
# 浏览器会拒绝该组合。需要指定具体的域名。
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
_cors_allow_credentials = _cors_origins != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加关联ID中间件
app.add_middleware(CorrelationMiddleware, metrics=metrics)

# 注册路由
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(channels_router)
app.include_router(nexus_admin_router)
app.include_router(nexus_auth_router)
app.include_router(nexus_router)
app.include_router(nexus_history_router)
app.include_router(nexus_ops_router)
app.include_router(nexus_schedules_router)
app.include_router(nexus_security_router)
app.include_router(nexus_system_router)
app.include_router(nexus_terminal_router)
app.include_router(nexus_utils_router)
app.include_router(nexus_runs_router)
app.include_router(nexus_runtimes_router)
app.include_router(nexus_missions_router)
app.include_router(nexus_evolution_router)

# Mount static files for NexusHub Web UI (with cache-control middleware)
static_dir = os.path.join(os.path.dirname(__file__), "static", "nexus")
if os.path.exists(static_dir):
    class NexusNoCacheMiddleware:
        """Pure ASGI middleware to disable browser caching for Nexus HTML/JS/CSS files."""
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await self.app(scope, receive, send)

            path = scope.get("path", "")
            # Apply no-cache to HTML/JS/CSS assets and the root index page
            should_add_no_cache = (
                path.endswith((".html", ".js", ".css"))
                or path in ("/", "")
            )

            if not should_add_no_cache:
                return await self.app(scope, receive, send)

            async def send_with_no_cache(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.extend([
                        (b"cache-control", b"no-cache, no-store, must-revalidate"),
                        (b"pragma", b"no-cache"),
                        (b"expires", b"0"),
                    ])
                    message["headers"] = headers
                await send(message)

            return await self.app(scope, receive, send_with_no_cache)

    app.add_middleware(NexusNoCacheMiddleware)
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="nexus-ui")


# 获取日志器
logger = get_logger(__name__)


# Browser convenience: avoid noisy 404s for favicon
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": "Validation error",
            "details": exc.errors(),
            "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
        }
    )

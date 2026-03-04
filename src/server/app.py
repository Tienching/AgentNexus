# -*- coding: utf-8 -*-
"""FastAPI Application Entry Point"""

import os
import time
import json
from typing import Optional
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
from .routers.nexus_auth import router as nexus_auth_router
from .routers.nexus_history import router as nexus_history_router
from .logger import setup_logger, get_logger
from .services import (
    TaskQueue,
    TaskExecutor,
    create_and_start_executor,
    get_executor,
)
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


async def task_handler(task: Task) -> Optional[str]:
    """任务执行处理函数

    执行任务并返回错误消息（如果有）。
    返回 None 表示成功，返回字符串表示失败原因。

    关键：为了让 `/nexus/` 的 Task 详情能像 Chat 一样看到对话，
    这里会把 CLI 的 stream-json 输出转换成 AG-UI 事件并归档到 Redis 会话存储。
    """
    import asyncio
    import uuid

    from .adapters import ProtocolType, get_router
    from .models import RequestModel
    from .services import CLIExecutor, get_session_storage
    from .services.stream_archiver import create_archiver
    from src.providers.gemini import GeminiExecutor
    from src.providers.codex import CodexCLIExecutor
    from src.providers.codebuddy import CodebuddyCLIExecutor
    from src.runtime.adapters.gemini import GeminiAGUIAdapter
    from src.runtime.adapters.codex import CodexCLIAGUIAdapter
    from src.runtime.adapters.codebuddy import CodebuddyAGUIAdapter

    from src.server.utils.ids import gen_run_id

    logger = get_logger(__name__)

    # 使用任务中存储的 exec_user
    exec_user = task.exec_user or "ubuntu"
    logger.info(f"task_handler: task.session_id={task.session_id!r}, task.id={task.id}")
    session_id = task.session_id or f"task_{task.id}"  # Use stored session_id, fallback for legacy tasks
    logger.info(f"task_handler: using session_id={session_id}")
    run_id = gen_run_id()

    logger.info(f"Executing task {task.id} for exec_user {exec_user}: {task.description[:50]}...")

    # Provider pinned at task creation time (default: claude)
    provider = (getattr(task, "provider", None) or "claude").strip().lower() or "claude"

    # Create provider-specific executor
    if provider == "gemini":
        executor = GeminiExecutor(config=settings)
    elif provider == "codex":
        executor = CodexCLIExecutor()
    else:
        executor = CLIExecutor(config=settings)

    # Determine the user prompt for this run.
    ctx = getattr(task, "context", None) or {}
    
    # Debug: log context to understand what's being read
    logger.info(f"Task {task.id} context debug", extra={
        "task_id": task.id,
        "context_keys": list(ctx.keys()) if ctx else [],
        "next_user_message": ctx.get("next_user_message", "<MISSING>")[:100] if ctx.get("next_user_message") else "<MISSING>",
        "next_user_message_id": ctx.get("next_user_message_id", "<MISSING>"),
        "next_run_kind": ctx.get("next_run_kind", "<MISSING>"),
    })
    
    user_prompt = (ctx.get("next_user_message") or task.description or "").strip()

    # Resolve alias: task.alias if set, otherwise fallback to provider name
    alias_value = (getattr(task, "alias", None) or provider)
    # Resolve model: task.model if set
    model_value = (getattr(task, "model", None) or "").strip() or None

    # Resolve cli_session_id for session resumption (provider-agnostic).
    # Priority: cli_session_id > legacy claude_session_id
    cli_session_id = (
        getattr(task, "cli_session_id", None)
        or getattr(task, "claude_session_id", None)
        or None
    )

    # 构建请求模型
    request = RequestModel(
        content=user_prompt,
        user=task.project_id or "task_executor",  # 使用 project_id 作为用户标识
        session_id=session_id,
        msg_id=run_id,
        # If task carries an execution workspace, run CLI executor in that directory.
        cwd=task.workspace or "",
        # 传递 cwd_mode，用于控制 Claude Code 是否使用 -c (continue) 选项
        cwd_mode=ctx.get("cwd_mode", ""),
        # 传递 run_kind，用于区分首次执行和续聊
        run_kind=ctx.get("next_run_kind", ""),
        # Pass provider so CLIExecutor._build_command() uses the correct CLI
        # (e.g., "codebuddy" instead of defaulting to "claude")
        provider=provider,
        # Pass alias so _build_command() uses it as the actual CLI command name
        # (e.g., "claude-internal" as alias, while provider remains "claude")
        alias=alias_value,
        # Pass model so _build_command() uses the correct LLM model
        model=model_value,
        # Pass CLI session ID for precise session resumption
        # (claude --resume ID, gemini --resume ID, codex resume ID)
        cli_session_id=cli_session_id,
    )

    # 归档器（落 Redis，供 Nexus UI 查询）
    archiver = create_archiver(
        thread_id=session_id,
        run_id=run_id,
        username=request.user or "task_executor",
        exec_user=exec_user,
        provider=provider,
        alias=alias_value,
    )

    # 同时写入"原始 AG-UI 事件序列"，供 Task 详情页像 Chat 一样实时播放
    storage = get_session_storage()

    # Store task_id in session meta so we can identify task sessions without prefix
    try:
        key = f"session:{session_id}:meta"
        storage._redis.hset(key, "task_id", task.id)
    except Exception as e:
        logger.warning(f"Failed to set task_id in session meta: {e}")

    # Adapter: provider-specific stream-json -> AG-UI SSE
    if provider == "gemini":
        adapter = GeminiAGUIAdapter()
    elif provider == "codex":
        adapter = CodexCLIAGUIAdapter()
    elif provider == "codebuddy":
        adapter = CodebuddyAGUIAdapter()
    else:
        adapter = get_router().get_adapter(ProtocolType.AGUI)

    adapter.init_state(thread_id=session_id, run_id=run_id)

    # For chat-continue runs, ensure the initial user message id is unique so it won't be de-duplicated.
    initial_user_msg_id = ctx.get("next_user_message_id") or f"task-user-{task.id}"  # legacy

    initial_messages = [
        {
            "id": str(initial_user_msg_id),
            "role": "user",
            "content": user_prompt,
        }
    ]
    
    logger.info(f"Task {task.id} initial_messages", extra={
        "initial_user_msg_id": initial_user_msg_id,
        "user_prompt": user_prompt[:100] if user_prompt else "",
        "run_kind": ctx.get("next_run_kind", ""),
    })

    async def _archive_converted_sse(converted: str):
        if not converted:
            return
        for _evt in converted.split("\n\n"):
            _evt = _evt.strip()
            if not _evt.startswith("data:"):
                continue
            payload = _evt.replace("data:", "", 1).strip()
            if not payload:
                continue
            try:
                evt_obj = json.loads(payload)
                if isinstance(evt_obj, dict):
                    # 1) append to event log (for live playback)
                    try:
                        storage.append_agui_event(session_id, evt_obj)
                    except Exception:
                        pass
                    # 2) archive into session/messages storage (for snapshot view)
                    try:
                        await archiver.archive_event(evt_obj)
                    except Exception:
                        pass
            except Exception:
                continue

    # Track CLI session ID captured from stream output
    _captured_cli_session_id = None

    try:
        await archiver.on_run_started(initial_messages)

        start_event = adapter.create_start_event()
        if start_event:
            await _archive_converted_sse(start_event)

        async for output in executor.execute(request, exec_user, output_format="raw"):
            if not output:
                continue

            # 检查是否有错误
            try:
                data = json.loads(output)
                if isinstance(data, dict) and data.get("type") == "error":
                    err_msg = data.get("message", "Unknown error")
                    try:
                        err_event = adapter.create_error_event(err_msg)
                        if err_event:
                            await _archive_converted_sse(err_event)
                    except Exception:
                        pass
                    return err_msg

                # Capture CLI session ID from init/system events (provider-agnostic).
                # Claude: {"type": "system", "subtype": "init", "session_id": "UUID"}
                # Gemini: {"type": "init", "session_id": "UUID"} (if present)
                # Codex: {"type": "thread.started", "thread_id": "..."} (thread_id as fallback)
                if _captured_cli_session_id is None and isinstance(data, dict):
                    _sid = data.get("session_id") or data.get("thread_id")
                    if _sid and isinstance(_sid, str):
                        _captured_cli_session_id = _sid
                        logger.info(f"Captured CLI session ID for task {task.id}: {_sid}")

                # 转换为 AG-UI 事件并归档
                converted = adapter.convert(data) if isinstance(data, dict) else None
                if converted:
                    await _archive_converted_sse(converted)

            except json.JSONDecodeError:
                # 非 JSON 行忽略
                continue
            except Exception:
                # 单行转换/归档失败不应中断任务执行
                continue

        end_event = adapter.create_end_event()
        if end_event:
            await _archive_converted_sse(end_event)

        logger.info(f"Task {task.id} completed successfully")
        _task_error = None  # Track error for notification
        return None  # 成功

    except asyncio.CancelledError:
        logger.warning(f"Task {task.id} was cancelled")
        raise
    except Exception as e:
        logger.error(f"Task {task.id} failed: {e}", exc_info=True)
        _task_error = str(e)  # Track error for notification
        try:
            await archiver.on_run_error(str(e))
        except Exception:
            pass

        try:
            err_event = adapter.create_error_event(str(e))
            if err_event:
                await _archive_converted_sse(err_event)
        except Exception:
            pass

        return str(e)
    finally:
        try:
            await archiver.on_run_finished()
        except Exception:
            pass

        # Persist captured CLI session ID to the task for future resume.
        if _captured_cli_session_id:
            try:
                task.cli_session_id = _captured_cli_session_id
                # Also set legacy field for backward compat
                task.claude_session_id = _captured_cli_session_id
                queue = _task_queue
                if queue:
                    queue.update_task(task)
                    logger.info(f"Saved cli_session_id={_captured_cli_session_id} for task {task.id}")
            except Exception as e:
                logger.warning(f"Failed to save cli_session_id for task {task.id}: {e}")

        # Send task completion notification if response_url or notification target is set
        _has_notification = getattr(task, "response_url", None) or getattr(task, "notification_sink_type", None)
        if _has_notification:
            try:
                from .services.task_notifier import TaskNotifier
                notifier = TaskNotifier()
                # Check if _task_error was set in except block
                task_succeeded = "_task_error" not in dir() or _task_error is None
                # Build unified notification target from task fields
                notification_target = task.get_notification_target() if hasattr(task, "get_notification_target") else None
                await notifier.notify_task_completion(
                    task_id=task.id,
                    session_id=session_id,
                    response_url=task.response_url,
                    callback_msg_id=getattr(task, "callback_msg_id", None),
                    callback_user=getattr(task, "callback_user", None),
                    success=task_succeeded,
                    error_message=_task_error if not task_succeeded else None,
                    source_session_id=getattr(task, "source_session_id", None),
                    notification_target=notification_target,
                )
            except Exception as notify_err:
                logger.warning(f"Failed to send task completion notification: {notify_err}")


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
        f"Starting Virtual Human Agent v{app.version} "
        f"on {settings.api_host}:{settings.api_port}"
    )
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"CLI command: {settings.cli_command}")
    
    # 启动任务执行器
    executor = None
    if settings.executor_enabled:
        try:
            import os
            # 默认使用 ubuntu exec_user（与路由 /chat/stream/ubuntu 对应）
            exec_user = os.environ.get("EXEC_USER", "ubuntu")

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
        except Exception as e:
            logger.error(f"Failed to start task executor: {e}", exc_info=True)

    # 启动 Channel 服务（Telegram, Slack, Discord 等）
    channel_service = None
    try:
        from .services.channel_service import create_channel_service
        channel_service = await create_channel_service()
        if channel_service:
            await channel_service.start()
            logger.info("Channel service started")
    except ImportError as e:
        logger.debug(f"Channel service not available: {e}")
    except Exception as e:
        logger.warning(f"Failed to start channel service: {e}")

    yield

    # 关闭时
    # 停止 Channel 服务
    if channel_service:
        try:
            await channel_service.stop()
            logger.info("Channel service stopped")
        except Exception as e:
            logger.error(f"Error stopping channel service: {e}")

    if executor:
        try:
            await executor.stop()
            logger.info("Task executor stopped")
        except Exception as e:
            logger.error(f"Error stopping task executor: {e}")
    
    logger.info("Shutting down Virtual Human Agent")


# 创建FastAPI应用
app = FastAPI(
    title="Virtual Human Agent",
    description="Multi-provider CLI wrapper with AG-UI SSE streaming",
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
app.include_router(channels_router)
app.include_router(nexus_auth_router)
app.include_router(nexus_router)
app.include_router(nexus_history_router)

# Mount static files for NexusHub Web UI (with cache-control middleware)
static_dir = os.path.join(os.path.dirname(__file__), "static", "nexus")
if os.path.exists(static_dir):
    app.mount("/nexus", StaticFiles(directory=static_dir, html=True), name="nexus")

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
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation error",
            "details": exc.errors(),
            "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
        }
    )

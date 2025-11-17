"""FastAPI 应用主入口"""

import time
import json
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import ValidationError

from .models import RequestModel, HealthResponse, MetricsResponse
from .ccr_service import CCRCodeService
from .config import settings
from .logger import (
    setup_logger,
    get_logger,
    generate_correlation_id,
    set_correlation_id,
    RequestLogger,
)

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
    allow_origins=["*"],  # 生产环境应该配置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化服务
ccr_service = CCRCodeService(settings)
logger = get_logger(__name__)


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """为每个请求添加关联ID并记录请求详情"""
    # 生成或获取关联ID
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    set_correlation_id(correlation_id)

    # 创建请求日志记录器
    request_logger = RequestLogger(logger)

    # 获取客户端信息
    client_info = f"{request.client.host}:{request.client.port}" if request.client else None

    # 读取请求体（如果有）
    body = None
    if request.method in ["POST", "PUT", "PATCH"]:
        try:
            body_bytes = await request.body()
            if body_bytes:
                try:
                    body = json.loads(body_bytes.decode('utf-8'))
                except json.JSONDecodeError:
                    body = body_bytes.decode('utf-8', errors='ignore')
                # 重新设置请求体，使后续处理器能够读取
                request._body = body_bytes
        except Exception as e:
            logger.warning(f"Failed to read request body: {e}")

    # 记录请求
    request_logger.log_request(
        method=request.method,
        path=request.url.path,
        headers=dict(request.headers),
        body=body,
        query_params=dict(request.query_params),
        client_info=client_info,
    )

    # 更新活跃请求计数
    metrics["requests_active"] += 1
    metrics["requests_total"] += 1

    try:
        # 处理请求
        response = await call_next(request)

        # 记录响应
        request_logger.log_response(
            status_code=response.status_code,
        )

        # 添加关联ID到响应头
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    except Exception as e:
        # 记录错误响应
        request_logger.log_response(
            status_code=500,
            error=e,
        )
        raise

    finally:
        metrics["requests_active"] -= 1


@app.post("/chat/stream/{agent_name}", response_class=StreamingResponse)
async def chat_stream(request: Request, agent_name: str):
    """
    流式聊天接口

    接收用户消息并返回流式响应（Server-Sent Events格式）

    Args:
        request: FastAPI请求对象
        agent_name: Linux系统用户名，通过su切换到该用户运行CCR命令
    """
    # 获取原始请求体
    try:
        body_bytes = await request.body()
        body_str = body_bytes.decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to read request body: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read request body"
        )

    # 检查是否是测试连接请求（空body或仅包含{}）
    if not body_str or body_str.strip() in ['', '{}']:
        logger.info(f"Received test connectivity request for agent {agent_name} (empty body)")
        test_msg = f"Service is running with agent '{agent_name}'. This is a test response for connectivity check."

        async def test_response():
            """返回测试响应"""
            test_data = {
                "response": test_msg,
                "finished": True,
                "global_output": {
                    "context": "test",
                    "answer_success": 1,
                    "docs": []
                }
            }
            yield ccr_service._format_sse(test_data)

        return StreamingResponse(
            test_response(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Transfer-Encoding": "chunked",
            }
        )

    # 解析请求（宽松模式）
    try:
        request_model = RequestModel.model_validate_json(body_str)
        # 记录处理开始
        logger.debug(
            "Processing chat request with agent",
            extra={
                "api_user": request_model.user,  # 请求体中的API用户
                "agent_name": agent_name,  # URL中指定的Linux系统用户
                "session_id": request_model.session_id,
                "msg_id": request_model.msg_id,
                "content_length": len(request_model.content) if request_model.content else 0,
            }
        )
    except ValidationError as e:
        # 返回详细的错误信息
        error_detail = {
            "error": "Request validation failed",
            "validation_errors": e.errors(),
            "received_data": json.loads(body_str) if body_str else None
        }

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse request: {str(e)}"
        )

    # 检查必填字段
    if not request_model.user or not request_model.content:
        missing_fields = []
        if not request_model.user:
            missing_fields.append("user")
        if not request_model.content:
            missing_fields.append("content")

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required fields: {', '.join(missing_fields)}"
        )

    async def generate():
        """生成SSE流"""
        try:
            # 调用服务处理请求，传入agent_name和api_user
            async for chunk in ccr_service.process_request(request_model, agent_name=agent_name):
                yield chunk

        except Exception as e:
            logger.error(
                f"Stream generation error for agent {agent_name}: {e}",
                exc_info=True,
                extra={
                    "api_user": request_model.user,
                    "agent_name": agent_name
                },
            )
            # 发送错误响应
            yield ccr_service._format_sse(
                {
                    "response": "",
                    "finished": True,
                    "global_output": {
                        "context": "",
                        "answer_success": 0,
                        "docs": [],
                    },
                }
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用nginx缓冲
            "Transfer-Encoding": "chunked",
        },
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    健康检查接口

    用于监控服务状态
    """
    return HealthResponse(
        status="healthy", service="claude-code-api", version=app.version
    )


@app.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    """
    获取服务指标

    返回请求统计等信息
    """
    return MetricsResponse(
        version=app.version,
        ccr_command=settings.ccr_command,
        requests_total=metrics["requests_total"],
        requests_active=metrics["requests_active"],
    )


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "Claude Code API",
        "version": app.version,
        "status": "running",
        "endpoints": {
            "chat": "/chat/stream/{agent_name}",
            "health": "/health",
            "metrics": "/metrics",
            "docs": "/docs",
            "redoc": "/redoc",
        },
        "description": {
            "/chat/stream/{agent_name}": "通过su切换到指定Linux系统用户运行CCR命令",
            "agent_name": "URL路径参数，Linux系统用户名，用于执行命令",
            "api_user": "请求体中的user字段，用于创建工作目录/home/{agent_name}/{api_user}"
        }
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP异常处理器"""
    # 获取请求详细信息
    request_info = {
        "status_code": exc.status_code,
        "path": request.url.path,
        "method": request.method,
        "query_params": dict(request.query_params),
        "headers": dict(request.headers),
        "client": f"{request.client.host}:{request.client.port}" if request.client else None,
    }

    logger.warning(
        f"HTTP exception: {exc.status_code} - {exc.detail}",
        extra=request_info,
    )
    return {"error": exc.detail, "status_code": exc.status_code}


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """验证异常处理器"""
    # 获取请求详细信息
    request_info = {
        "path": request.url.path,
        "method": request.method,
        "validation_errors": exc.errors(),
        "query_params": dict(request.query_params),
    }

    # 尝试获取请求体
    try:
        if request.method in ["POST", "PUT", "PATCH"]:
            body = await request.body()
            if body:
                try:
                    request_info["body"] = json.loads(body.decode('utf-8'))
                except:
                    request_info["body"] = body.decode('utf-8', errors='ignore')[:1000]
    except:
        pass

    logger.error(
        f"Validation error on {request.method} {request.url.path}",
        extra=request_info,
    )

    return {
        "error": "Validation error",
        "details": exc.errors(),
        "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
    }


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """通用异常处理器"""
    # 获取请求详细信息
    request_info = {
        "path": request.url.path,
        "method": request.method,
        "query_params": dict(request.query_params),
        "headers": dict(request.headers),
        "client": f"{request.client.host}:{request.client.port}" if request.client else None,
        "error_type": type(exc).__name__,
    }

    logger.error(
        f"Unhandled exception: {str(exc)}",
        exc_info=True,
        extra=request_info,
    )
    return {
        "error": "Internal server error",
        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
    }
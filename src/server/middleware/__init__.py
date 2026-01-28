# -*- coding: utf-8 -*-
"""Correlation ID Middleware"""

import json
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from ..logger import (
    get_logger,
    generate_correlation_id,
    set_correlation_id,
    RequestLogger,
)

logger = get_logger(__name__)


class CorrelationMiddleware(BaseHTTPMiddleware):
    """为每个请求添加关联ID并记录请求详情"""

    def __init__(self, app, metrics: dict):
        super().__init__(app)
        self.metrics = metrics

    async def dispatch(self, request: Request, call_next):
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
        self.metrics["requests_active"] += 1
        self.metrics["requests_total"] += 1

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
            self.metrics["requests_active"] -= 1

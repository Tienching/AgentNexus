"""API集成测试"""

import pytest
import json
import warnings
from unittest.mock import patch
from httpx import AsyncClient
from pydantic import ValidationError
from starlette.requests import Request

from src.server.app import app, validation_exception_handler
from src.server.models import RequestModel


class TestAPIEndpoints:
    """API端点集成测试"""

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client: AsyncClient):
        """测试根路径直接提供 Web UI"""
        response = await client.get("/")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_nexus_redirect_to_root(self, client: AsyncClient):
        """测试 /nexus 重定向到根路径"""
        response = await client.get("/nexus", follow_redirects=False)
        assert response.status_code in (301, 302, 307)
        assert response.headers.get("location") == "/"

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client: AsyncClient):
        """测试健康检查端点"""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "agent-nexus"
        assert "version" in data

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, client: AsyncClient):
        """测试指标端点"""
        response = await client.get("/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "cli_command" in data
        assert "requests_total" in data
        assert "requests_active" in data

    @pytest.mark.asyncio
    async def test_required_startup_failure_blocks_app_lifespan(self, monkeypatch):
        """测试必需启动子系统失败时拒绝启动 API"""
        monkeypatch.setattr("src.server.app.settings.executor_enabled", False)
        monkeypatch.setattr("src.server.app.settings.scheduler_enabled", False)
        monkeypatch.setattr("src.server.app.settings.evolution_enabled", False)

        with patch("src.server.services.channel_service.create_channel_service", return_value=None), \
             patch("src.server.services.terminal_manager.TerminalManager", side_effect=RuntimeError("tmux missing")):
            with pytest.raises(RuntimeError, match="Terminal Manager"):
                async with app.router.lifespan_context(app):
                    pass

    @pytest.mark.asyncio
    async def test_chat_stream_endpoint_headers(self, client: AsyncClient, sample_request):
        """测试聊天流端点的响应头"""
        response = await client.post("/chat/stream/testuser", json=sample_request, follow_redirects=True)

        # 检查响应状态
        assert response.status_code == 200

        # 检查SSE相关的响应头
        assert response.headers.get("content-type") == "text/event-stream; charset=utf-8"
        assert response.headers.get("cache-control") == "no-cache"
        assert response.headers.get("connection") == "keep-alive"
        assert response.headers.get("x-accel-buffering") == "no"

    @pytest.mark.asyncio
    async def test_chat_stream_with_minimal_request(self, client: AsyncClient):
        """测试最小请求的聊天流"""
        minimal_request = {
            "user": "test_user",
            "content": "hi"
        }

        response = await client.post("/chat/stream/testuser", json=minimal_request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_chat_stream_with_invalid_request(self, client: AsyncClient):
        """测试无效请求的聊天流"""
        invalid_request = {
            "user": "test_user"
            # 缺少content字段
        }

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            response = await client.post("/chat/stream/testuser", json=invalid_request)

        assert response.status_code == 422  # Unprocessable Content
        assert not any(
            "HTTP_422_UNPROCESSABLE_ENTITY" in str(warning.message)
            for warning in caught
        )

    @pytest.mark.asyncio
    async def test_validation_exception_handler_uses_non_deprecated_422_constant(self):
        """测试验证异常处理器不会触发废弃常量警告"""
        try:
            RequestModel.model_validate({})
        except ValidationError as exc:
            validation_error = exc
        else:
            pytest.fail("Expected RequestModel.model_validate({}) to raise ValidationError")

        request = Request({
            "type": "http",
            "method": "POST",
            "path": "/chat/stream/testuser",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
            "client": ("testclient", 123),
        })

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            response = await validation_exception_handler(request, validation_error)

        body = json.loads(response.body)
        assert response.status_code == 422
        assert body["status_code"] == 422
        assert not any(
            "HTTP_422_UNPROCESSABLE_ENTITY" in str(warning.message)
            for warning in caught
        )

    @pytest.mark.asyncio
    async def test_correlation_id_header(self, client: AsyncClient):
        """测试关联ID头处理"""
        # 发送带有关联ID的请求
        correlation_id = "test-correlation-id-123"
        response = await client.get(
            "/health",
            headers={"X-Correlation-ID": correlation_id}
        )

        assert response.status_code == 200
        # 检查响应中是否包含相同的关联ID
        assert response.headers.get("X-Correlation-ID") == correlation_id

    @pytest.mark.asyncio
    async def test_auto_generated_correlation_id(self, client: AsyncClient):
        """测试自动生成的关联ID"""
        response = await client.get("/health")

        assert response.status_code == 200
        # 检查响应中是否有自动生成的关联ID
        assert "X-Correlation-ID" in response.headers
        assert len(response.headers["X-Correlation-ID"]) > 0

    @pytest.mark.asyncio
    async def test_chat_stream_with_different_commands(self, client: AsyncClient):
        """测试不同CLI命令的聊天流"""
        minimal_request = {
            "user": "test_user",
            "content": "hi"
        }

        # 测试不同的命令
        for cmd in ["ccr", "codebuddy", "codebuddy-code"]:
            response = await client.post("/chat/stream/testuser", json=minimal_request)
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_404_not_found(self, client: AsyncClient):
        """测试不存在的端点"""
        response = await client.get("/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_method_not_allowed(self, client: AsyncClient):
        """测试不允许的HTTP方法"""
        response = await client.post("/health")
        assert response.status_code == 405  # Method Not Allowed
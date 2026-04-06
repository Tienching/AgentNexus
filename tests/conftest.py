"""Pytest配置和fixtures"""

import pytest
import asyncio
from typing import Any, AsyncGenerator
from httpx import AsyncClient, ASGITransport
from src.server.app import AppStartupPolicy, create_app, create_app_settings


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def app_factory():
    """创建隔离于宿主环境的测试应用"""

    def _create_app(
        *,
        settings_overrides: dict[str, Any] | None = None,
        startup_policy: AppStartupPolicy | None = None,
    ):
        return create_app(
            settings_override=create_app_settings(
                use_env=False,
                overrides=settings_overrides,
            ),
            startup_policy=startup_policy,
        )

    return _create_app


@pytest.fixture
async def client(app_factory) -> AsyncGenerator[AsyncClient, None]:
    """创建测试客户端"""
    transport = ASGITransport(app=app_factory())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_request():
    """示例请求数据"""
    return {
        "user": "test_user",
        "msg_type": "text",
        "content": "你好",
        "msg_id": "test_msg_001",
        "raw_msg": "",
        "session_id": "test_session_001",
        "business_keys": ["test_key"],
    }


@pytest.fixture
def sample_stream_response():
    """示例流式响应"""
    return {
        "response": "你好",
        "finished": False,
        "global_output": {"context": "", "answer_success": 0, "docs": []},
    }
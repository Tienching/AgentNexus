"""Pytest配置和fixtures"""

import pytest
import asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from src.server.app import app


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """创建测试客户端"""
    transport = ASGITransport(app=app)
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
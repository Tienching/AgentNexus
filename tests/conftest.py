"""Pytest配置和fixtures"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient


_TEST_ENV_KEYS = ("NEXUS_DB_PATH", "NEXUS_HISTORY_CACHE_PATH")
_previous_test_env: dict[str, str | None] = {}
_test_runtime_dir: Path | None = None


def pytest_configure(config):
    """Bind the entire test process to disposable runtime storage."""
    del config
    global _previous_test_env, _test_runtime_dir
    if _test_runtime_dir is not None:
        return

    _test_runtime_dir = Path(tempfile.mkdtemp(prefix="agent-nexus-pytest-"))
    _previous_test_env = {key: os.environ.get(key) for key in _TEST_ENV_KEYS}
    os.environ["NEXUS_DB_PATH"] = str(_test_runtime_dir / "nexus.db")
    os.environ["NEXUS_HISTORY_CACHE_PATH"] = str(_test_runtime_dir / "history-cache.sqlite")


def pytest_unconfigure(config):
    """Restore the caller environment and remove disposable test storage."""
    del config
    global _previous_test_env, _test_runtime_dir
    for key, value in _previous_test_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    if _test_runtime_dir is not None:
        shutil.rmtree(_test_runtime_dir, ignore_errors=True)
    _previous_test_env = {}
    _test_runtime_dir = None


def pytest_collection_modifyitems(config, items):
    """Attach semantic markers based on test location when missing.

    This lets the suite select `unit` / `integration` / `slow` by marker rather
    than relying only on directory slicing in shell scripts.
    """
    for item in items:
        marker_names = {mark.name for mark in item.iter_markers()}
        path = Path(str(item.fspath))
        parts = set(path.parts)
        if "unit" in parts and "unit" not in marker_names:
            item.add_marker(pytest.mark.unit)
        if "integration" in parts and "integration" not in marker_names:
            item.add_marker(pytest.mark.integration)
        if "e2e" in parts:
            if "integration" not in marker_names:
                item.add_marker(pytest.mark.integration)
            if "slow" not in marker_names:
                item.add_marker(pytest.mark.slow)


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def app_factory(tmp_path):
    """创建隔离于宿主环境的测试应用"""

    def _create_app(
        *,
        settings_overrides: dict[str, Any] | None = None,
        startup_policy_overrides: dict[str, bool] | None = None,
    ):
        from src.server import app as server_app

        isolated_settings = {"log_dir": str(tmp_path / "logs")}
        if settings_overrides:
            isolated_settings.update(settings_overrides)

        return server_app.create_app_with_overrides(
            use_env=False,
            settings_overrides=isolated_settings,
            startup_policy_overrides=startup_policy_overrides,
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

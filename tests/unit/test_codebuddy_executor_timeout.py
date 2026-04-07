# -*- coding: utf-8 -*-
"""Regression tests for Codebuddy executor timeout cleanup."""

import asyncio
import gc
import json
import warnings
from unittest.mock import AsyncMock, Mock

import pytest

from src.providers.base import RequestContext
from src.providers.codebuddy.cli_executor import CodebuddyCLIExecutor


@pytest.mark.asyncio
async def test_execute_internal_timeout_awaits_async_kill_without_warnings(monkeypatch):
    """Timeout cleanup should await async-mock kill() and still emit the timeout event."""
    cfg = Mock()
    cfg.codebuddy_command = "codebuddy"
    cfg.timeout = 0.01
    cfg.user_home_base = "/home"
    executor = CodebuddyCLIExecutor(config=cfg)

    process = AsyncMock(spec=asyncio.subprocess.Process)
    process.kill = AsyncMock()
    process.wait = AsyncMock(return_value=0)
    process.stderr = AsyncMock()
    process.stderr.read = AsyncMock(return_value=b"")

    async def timeout_stream(_process):
        if False:  # pragma: no cover
            yield ""
        raise asyncio.TimeoutError

    monkeypatch.setattr(executor, "run_subprocess", AsyncMock(return_value=process))
    monkeypatch.setattr(executor, "_process_stream", timeout_stream)

    context = RequestContext(
        content="hello",
        exec_user="ubuntu",
        session_id="timeout-test",
        cwd="/tmp",
        cwd_mode="inplace",
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        outputs = [json.loads(item) async for item in executor._execute_internal(context)]
        await asyncio.sleep(0)
        gc.collect()

    assert outputs == [{"type": "error", "message": "处理超时，请重试"}]
    process.kill.assert_awaited_once()
    process.wait.assert_awaited_once()
    process.stderr.read.assert_awaited_once()
    runtime_warnings = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert runtime_warnings == []

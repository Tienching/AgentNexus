# -*- coding: utf-8 -*-
"""Regression tests for Codebuddy executor timeout cleanup."""

import asyncio
import gc
import json
import signal
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
    cfg.cli_timeout = 0.01
    cfg.user_home_base = "/home"
    executor = CodebuddyCLIExecutor(config=cfg)

    process = AsyncMock(spec=asyncio.subprocess.Process)
    process.kill = AsyncMock()
    process.wait = AsyncMock(return_value=0)
    process.stderr = AsyncMock()
    process.stderr.read = AsyncMock(return_value=b"")

    async def timeout_stream(_process, _context=None):
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


@pytest.mark.asyncio
async def test_execute_internal_enforces_overall_timeout_while_stream_keeps_output(monkeypatch):
    """Continuous CLI output must not extend the overall CodeBuddy timeout forever."""
    cfg = Mock()
    cfg.codebuddy_command = "codebuddy"
    cfg.cli_timeout = 0.05
    cfg.user_home_base = "/home"
    executor = CodebuddyCLIExecutor(config=cfg)

    class ContinuousStdout:
        async def readline(self):
            await asyncio.sleep(0.02)
            return b'{"type":"assistant","message":{"content":[{"type":"text","text":"still running"}]}}\n'

    process = Mock(spec=asyncio.subprocess.Process)
    process.stdout = ContinuousStdout()
    process.stderr = AsyncMock()
    process.stderr.read = AsyncMock(return_value=b"")
    process.kill = Mock()
    process.wait = AsyncMock(return_value=0)

    monkeypatch.setattr(executor, "run_subprocess", AsyncMock(return_value=process))

    context = RequestContext(
        content="hello",
        exec_user="ubuntu",
        session_id="timeout-test",
        cwd="/tmp",
        cwd_mode="inplace",
    )

    async def collect_outputs():
        return [json.loads(item) async for item in executor._execute_internal(context)]

    outputs = await asyncio.wait_for(collect_outputs(), timeout=0.3)

    assert outputs[-1] == {"type": "error", "message": "处理超时，请重试"}
    process.kill.assert_called_once()


@pytest.mark.asyncio
async def test_execute_internal_emits_error_when_cli_exits_nonzero_without_stdout(monkeypatch):
    """CodeBuddy startup failures on stderr must not look like a completed answer."""
    cfg = Mock()
    cfg.codebuddy_command = "codebuddy"
    cfg.cli_timeout = 1.0
    cfg.user_home_base = "/home"
    executor = CodebuddyCLIExecutor(config=cfg)

    process = Mock(spec=asyncio.subprocess.Process)
    process.returncode = 1
    process.stdout = AsyncMock()
    process.stdout.readline = AsyncMock(return_value=b"")
    process.stderr = AsyncMock()
    process.stderr.read = AsyncMock(return_value=b"Error: Cannot find module '@opentelemetry/api'")
    process.wait = AsyncMock(return_value=1)

    monkeypatch.setattr(executor, "run_subprocess", AsyncMock(return_value=process))

    context = RequestContext(
        content="hello",
        exec_user="ubuntu",
        session_id="nonzero-test",
        cwd="/tmp",
        cwd_mode="inplace",
    )

    outputs = [json.loads(item) async for item in executor._execute_internal(context)]

    assert outputs == [
        {
            "type": "error",
            "message": "CodeBuddy CLI exited with code 1: Error: Cannot find module '@opentelemetry/api'",
        }
    ]


@pytest.mark.asyncio
async def test_timeout_cleanup_kills_codebuddy_process_group(monkeypatch):
    """Timeout cleanup should terminate child tool processes spawned by CodeBuddy."""
    cfg = Mock()
    cfg.codebuddy_command = "codebuddy"
    cfg.cli_timeout = 0.05
    cfg.user_home_base = "/home"
    executor = CodebuddyCLIExecutor(config=cfg)

    process = Mock(spec=asyncio.subprocess.Process)
    process.pid = 1234
    process.kill = Mock()
    process.wait = AsyncMock(return_value=0)
    process.stderr = AsyncMock()
    process.stderr.read = AsyncMock(return_value=b"")

    killed_groups = []
    monkeypatch.setattr("src.providers.codebuddy.cli_executor.os.getpgid", lambda pid: 5678)
    monkeypatch.setattr(
        "src.providers.codebuddy.cli_executor.os.killpg",
        lambda pgid, sig: killed_groups.append((pgid, sig)),
    )

    await executor._cleanup_timed_out_process(process)

    assert killed_groups == [(5678, signal.SIGKILL)]
    process.kill.assert_not_called()

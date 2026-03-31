# -*- coding: utf-8 -*-
"""Tests for NanobotExecutor — callback→generator bridging."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.providers.base import RequestContext
from src.providers.nanobot.executor import NanobotExecutor, _NanobotPool, _serialise_event
from src.providers.nanobot.event_schema import (
    TextStartEvent,
    TextDeltaEvent,
    TextEndEvent,
    ToolStartEvent,
    ErrorEvent,
)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

class TestSerialiseEvent:

    def test_text_delta(self):
        event = TextDeltaEvent(message_id="msg-1", delta="Hello")
        s = _serialise_event(event)
        d = json.loads(s)
        assert d["type"] == "text_delta"
        assert d["message_id"] == "msg-1"
        assert d["delta"] == "Hello"

    def test_tool_start(self):
        event = ToolStartEvent(
            tool_call_id="tc-1", name="exec",
            arguments={"command": "ls"},
        )
        s = _serialise_event(event)
        d = json.loads(s)
        assert d["type"] == "tool_start"
        assert d["name"] == "exec"

    def test_error(self):
        event = ErrorEvent(message="oops")
        s = _serialise_event(event)
        d = json.loads(s)
        assert d["type"] == "error"
        assert d["message"] == "oops"


# ---------------------------------------------------------------------------
# Init / config
# ---------------------------------------------------------------------------

class TestNanobotExecutorInit:

    def test_default_workspace(self):
        executor = NanobotExecutor()
        assert executor._workspace is not None
        assert "Projects" in executor._workspace

    def test_workspace_from_config(self):
        config = MagicMock()
        config.nanobot_workspace = "/tmp/test-workspace"
        config.nanobot_model = "gpt-4o-mini"
        executor = NanobotExecutor(config=config)
        assert executor._workspace == "/tmp/test-workspace"
        assert executor._model == "gpt-4o-mini"

    def test_env_override(self):
        with patch.dict("os.environ", {"NANOBOT_WORKSPACE": "/env/workspace"}):
            executor = NanobotExecutor()
            assert executor._workspace == "/env/workspace"

    def test_build_command_returns_empty(self):
        executor = NanobotExecutor()
        ctx = RequestContext(content="test")
        assert executor._build_command(ctx) == []


# ---------------------------------------------------------------------------
# Execute — mock AgentLoop, verify queue bridge
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestNanobotExecutorExecute:

    async def test_error_on_pool_failure(self):
        executor = NanobotExecutor()

        with patch.object(
            _NanobotPool, "get_or_create",
            side_effect=RuntimeError("nanobot not installed"),
        ):
            ctx = RequestContext(content="hello", session_id="s1")
            lines = []
            async for line in executor.execute(ctx):
                lines.append(line)

        assert len(lines) == 1
        d = json.loads(lines[0])
        assert d["type"] == "error"
        assert "nanobot not installed" in d["message"]

    async def test_streaming_text(self):
        """Mock AgentLoop to push text events through the queue."""
        mock_loop = AsyncMock()

        async def fake_process_direct(
            content, session_key, channel, chat_id,
            on_stream, on_stream_end, on_tool_start, on_tool_end,
        ):
            await on_stream("Hello ")
            await on_stream("world!")
            await on_stream_end(resuming=False)
            return MagicMock(content="Hello world!")

        mock_loop.process_direct = fake_process_direct

        with patch.object(_NanobotPool, "get_or_create", return_value=mock_loop):
            executor = NanobotExecutor()
            ctx = RequestContext(content="hi", session_id="s2")
            lines = []
            async for line in executor.execute(ctx):
                lines.append(json.loads(line))

        types = [l["type"] for l in lines]
        assert "text_start" in types
        assert "text_delta" in types
        assert "text_end" in types
        deltas = [l["delta"] for l in lines if l["type"] == "text_delta"]
        assert "Hello " in deltas
        assert "world!" in deltas

    async def test_tool_events(self):
        """Mock AgentLoop to push tool events."""
        mock_loop = AsyncMock()

        async def fake_process_direct(
            content, session_key, channel, chat_id,
            on_stream, on_stream_end, on_tool_start, on_tool_end,
        ):
            await on_stream("Let me check...")
            await on_stream_end(resuming=True)
            await on_tool_start("read_file", "tc-1", {"path": "/tmp/x"})
            await on_tool_end("tc-1", "file contents")
            await on_stream("Done!")
            await on_stream_end(resuming=False)
            return MagicMock(content="Done!")

        mock_loop.process_direct = fake_process_direct

        with patch.object(_NanobotPool, "get_or_create", return_value=mock_loop):
            executor = NanobotExecutor()
            ctx = RequestContext(content="read file", session_id="s3")
            lines = []
            async for line in executor.execute(ctx):
                lines.append(json.loads(line))

        types = [l["type"] for l in lines]
        assert "tool_start" in types
        assert "tool_result" in types
        assert "tool_end" in types
        # Verify ordering
        ts = types.index("tool_start")
        tr = types.index("tool_result")
        te = types.index("tool_end")
        assert ts < tr < te

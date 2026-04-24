# -*- coding: utf-8 -*-
"""Tests for NexusAGUIAdapter."""

import json
import pytest

from src.runtime.adapters.nexus.agui_adapter import NexusAGUIAdapter


@pytest.fixture
def adapter():
    a = NexusAGUIAdapter()
    a.init_state(thread_id="thread-001", run_id="run-001")
    return a


class TestCreateStartEvent:
    def test_emits_run_started(self, adapter):
        sse = adapter.create_start_event()
        assert sse is not None
        data = json.loads(sse.split("data: ")[1].split("\n")[0])
        assert data["type"] == "RUN_STARTED"
        assert data["threadId"] == "thread-001"
        assert data["runId"] == "run-001"

    def test_idempotent(self, adapter):
        adapter.create_start_event()
        assert adapter.create_start_event() is None


class TestTextEvents:
    def test_text_start_delta_end(self, adapter):
        start = adapter.convert({"type": "text_start", "message_id": "msg-1"})
        assert start is not None
        assert "TEXT_MESSAGE_START" in start

        delta = adapter.convert({"type": "text_delta", "message_id": "msg-1", "delta": "Hello"})
        assert delta is not None
        assert "TEXT_MESSAGE_CONTENT" in delta
        assert "Hello" in delta

        end = adapter.convert({"type": "text_end", "message_id": "msg-1"})
        assert end is not None
        assert "TEXT_MESSAGE_END" in end

    def test_auto_open_on_delta(self, adapter):
        """text_delta without prior text_start should auto-open."""
        delta = adapter.convert({"type": "text_delta", "message_id": "msg-2", "delta": "Hi"})
        assert "TEXT_MESSAGE_START" in delta
        assert "TEXT_MESSAGE_CONTENT" in delta

    def test_empty_delta_ignored(self, adapter):
        assert adapter.convert({"type": "text_delta", "message_id": "msg-1", "delta": ""}) is None


class TestToolEvents:
    def test_tool_lifecycle(self, adapter):
        start = adapter.convert({
            "type": "tool_start",
            "tool_call_id": "tc-1",
            "name": "read_file",
            "arguments": {"path": "/tmp/test.txt"},
        })
        assert start is not None
        assert "TOOL_CALL_START" in start
        assert "TOOL_CALL_ARGS" in start
        assert "read_file" in start

        result = adapter.convert({
            "type": "tool_result",
            "tool_call_id": "tc-1",
            "content": "file contents here",
        })
        assert result is not None
        assert "TOOL_CALL_RESULT" in result

        end = adapter.convert({
            "type": "tool_end",
            "tool_call_id": "tc-1",
        })
        assert end is not None
        assert "TOOL_CALL_END" in end

    def test_tool_result_truncation(self, adapter):
        long_content = "x" * 2000
        result = adapter.convert({
            "type": "tool_result",
            "tool_call_id": "tc-2",
            "content": long_content,
        })
        assert "truncated" in result


class TestErrorEvent:
    def test_error_produces_text_and_run_error(self, adapter):
        result = adapter.convert({"type": "error", "message": "Something broke"})
        assert result is not None
        assert "TEXT_MESSAGE_START" in result
        assert "Something broke" in result
        assert "RUN_ERROR" in result


class TestCreateEndEvent:
    def test_normal_end(self, adapter):
        end = adapter.create_end_event()
        assert "RUN_FINISHED" in end

    def test_error_end(self, adapter):
        end = adapter.create_end_event(is_error=True, error_msg="fail")
        assert "RUN_ERROR" in end
        assert "RUN_FINISHED" in end

    def test_closes_open_message(self, adapter):
        adapter.convert({"type": "text_start", "message_id": "msg-1"})
        end = adapter.create_end_event()
        assert "TEXT_MESSAGE_END" in end
        assert "RUN_FINISHED" in end


class TestNoState:
    def test_convert_returns_none_without_state(self):
        adapter = NexusAGUIAdapter()
        assert adapter.convert({"type": "text_delta", "delta": "hi"}) is None

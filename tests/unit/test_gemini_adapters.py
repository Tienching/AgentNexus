"""Gemini CLI adapters tests"""

import json

from src.runtime.adapters.gemini import GeminiAGUIAdapter


class TestGeminiAGUIAdapter:
    def test_convert_message(self):
        adapter = GeminiAGUIAdapter()
        adapter.init_state(thread_id="t1", run_id="r1")

        event = {"type": "message", "role": "assistant", "content": "Hello"}
        result = adapter.convert(event)

        assert result is not None
        assert "TEXT_MESSAGE_START" in result
        assert "TEXT_MESSAGE_CONTENT" in result
        assert "Hello" in result

    def test_convert_tool_use_and_result(self):
        adapter = GeminiAGUIAdapter()
        adapter.init_state(thread_id="t1", run_id="r1")

        tool_use = {
            "type": "tool_use",
            "tool_name": "list_directory",
            "tool_id": "tool-1",
            "parameters": {"dir_path": "."},
        }
        result = adapter.convert(tool_use)
        assert result is not None
        assert "TOOL_CALL_START" in result
        assert "TOOL_CALL_ARGS" in result

        tool_result = {
            "type": "tool_result",
            "tool_id": "tool-1",
            "status": "success",
            "output": "Listed 1 item(s).",
        }
        result = adapter.convert(tool_result)
        assert result is not None
        assert "TOOL_CALL_RESULT" in result
        assert "TOOL_CALL_END" in result

    def test_convert_slash_command_result(self):
        adapter = GeminiAGUIAdapter()
        adapter.init_state(thread_id="t1", run_id="r1")

        event = {"type": "result", "subtype": "slash_command", "content": "ok"}
        result = adapter.convert(event)
        assert result is not None
        assert "TEXT_MESSAGE_CONTENT" in result
        assert "TEXT_MESSAGE_END" in result
        assert "ok" in result

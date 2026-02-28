# -*- coding: utf-8 -*-
"""CodebuddyAGUIAdapter 单元测试

测试 Codebuddy stream-json 到 AG-UI 事件的转换逻辑。
基于真实收集的 Codebuddy CLI 输出进行测试。
"""

import json
import pytest
from pathlib import Path

from src.runtime.adapters.codebuddy import CodebuddyAGUIAdapter


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "codebuddy"


def load_fixture(name: str) -> dict:
    """加载测试固件文件"""
    fixture_path = FIXTURES_DIR / f"{name}.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_sse_events(sse_output: str) -> list:
    """解析 SSE 格式输出为事件列表"""
    if not sse_output:
        return []
    events = []
    for line in sse_output.strip().split("\n\n"):
        if line.startswith("data:"):
            data_str = line.replace("data:", "", 1).strip()
            if data_str:
                try:
                    events.append(json.loads(data_str))
                except json.JSONDecodeError:
                    pass
    return events


class TestCodebuddyAGUIAdapterInit:
    """测试适配器初始化"""

    def test_adapter_creation(self):
        """测试创建适配器"""
        adapter = CodebuddyAGUIAdapter()
        assert adapter is not None

    def test_init_state(self):
        """测试初始化状态"""
        adapter = CodebuddyAGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        assert adapter.state is not None
        assert adapter.state.thread_id == "test-thread"
        assert adapter.state.run_id == "test-run"
        assert adapter.state.run_started is False
        assert adapter.state.message_started is False


class TestInitEvent:
    """测试 system/init 事件转换"""

    @pytest.fixture
    def adapter(self) -> CodebuddyAGUIAdapter:
        adapter = CodebuddyAGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        return adapter

    def test_convert_init_event(self, adapter):
        """验证 system/init 事件转换为 RUN_STARTED"""
        event = load_fixture("init_event")
        result = adapter.convert(event)
        
        assert result is not None
        events = parse_sse_events(result)
        assert len(events) == 1
        assert events[0]["type"] == "RUN_STARTED"
        assert events[0]["threadId"] == "test-thread"
        assert events[0]["runId"] == "test-run"

    def test_init_event_only_once(self, adapter):
        """验证 init 事件只发送一次"""
        event = load_fixture("init_event")
        
        result1 = adapter.convert(event)
        assert result1 is not None
        
        result2 = adapter.convert(event)
        assert result2 is None  # 第二次应该被忽略


class TestAssistantTextEvent:
    """测试 assistant 文本事件转换"""

    @pytest.fixture
    def adapter(self) -> CodebuddyAGUIAdapter:
        adapter = CodebuddyAGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        return adapter

    def test_convert_assistant_text(self, adapter):
        """验证 assistant text 转换为 TEXT_MESSAGE_START + CONTENT"""
        event = load_fixture("assistant_text")
        result = adapter.convert(event)
        
        assert result is not None
        events = parse_sse_events(result)
        
        # 应该有 TEXT_MESSAGE_START 和 TEXT_MESSAGE_CONTENT
        assert len(events) == 2
        assert events[0]["type"] == "TEXT_MESSAGE_START"
        assert events[0]["role"] == "assistant"
        assert "messageId" in events[0]
        assert events[0]["messageId"].startswith("codebuddy-msg-")
        
        assert events[1]["type"] == "TEXT_MESSAGE_CONTENT"
        assert "delta" in events[1]
        assert "AI 智能编程助手" in events[1]["delta"]

    def test_empty_text_ignored(self, adapter):
        """验证空文本被忽略"""
        event = {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": ""}]
            }
        }
        result = adapter.convert(event)
        assert result is None


class TestToolUseEvent:
    """测试工具调用事件转换"""

    @pytest.fixture
    def adapter(self) -> CodebuddyAGUIAdapter:
        adapter = CodebuddyAGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        return adapter

    def test_convert_tool_use(self, adapter):
        """验证 tool_use 转换为 TOOL_CALL_START + ARGS"""
        event = load_fixture("tool_use_event")
        result = adapter.convert(event)
        
        assert result is not None
        events = parse_sse_events(result)
        
        # 应该有 TOOL_CALL_START 和 TOOL_CALL_ARGS
        assert len(events) == 2
        assert events[0]["type"] == "TOOL_CALL_START"
        assert events[0]["toolCallId"] == "toolu_bdrk_01P9CDuNtb1JvRoJCf1y4RZg"
        assert events[0]["toolCallName"] == "Read"
        
        assert events[1]["type"] == "TOOL_CALL_ARGS"
        assert events[1]["toolCallId"] == "toolu_bdrk_01P9CDuNtb1JvRoJCf1y4RZg"
        # delta 应该包含序列化的参数
        args = json.loads(events[1]["delta"])
        assert args["file_path"] == "/home/ubuntu/Projects/virtual-human-sdk-feature-aionui/pyproject.toml"

    def test_tool_use_dedup(self, adapter):
        """验证同一工具调用不会重复发送 START"""
        event = load_fixture("tool_use_event")
        
        result1 = adapter.convert(event)
        events1 = parse_sse_events(result1)
        assert any(e["type"] == "TOOL_CALL_START" for e in events1)
        
        # 第二次转换同一工具
        result2 = adapter.convert(event)
        events2 = parse_sse_events(result2)
        # 应该只有 ARGS，没有 START
        assert not any(e["type"] == "TOOL_CALL_START" for e in events2)
        assert any(e["type"] == "TOOL_CALL_ARGS" for e in events2)


class TestToolResultEvent:
    """测试工具结果事件转换"""

    @pytest.fixture
    def adapter(self) -> CodebuddyAGUIAdapter:
        adapter = CodebuddyAGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        # 模拟之前有消息
        adapter.state.current_message_id = "codebuddy-msg-test"
        adapter.state.message_started = True
        return adapter

    def test_convert_tool_result(self, adapter):
        """验证 tool_result 转换为 TOOL_CALL_RESULT + END"""
        event = load_fixture("tool_result_event")
        result = adapter.convert(event)
        
        assert result is not None
        events = parse_sse_events(result)
        
        # 应该有 TOOL_CALL_RESULT 和 TOOL_CALL_END
        assert len(events) == 2
        
        result_event = events[0]
        assert result_event["type"] == "TOOL_CALL_RESULT"
        assert result_event["toolCallId"] == "toolu_bdrk_01P9CDuNtb1JvRoJCf1y4RZg"
        assert "[project]" in result_event["content"]
        
        end_event = events[1]
        assert end_event["type"] == "TOOL_CALL_END"
        assert end_event["toolCallId"] == "toolu_bdrk_01P9CDuNtb1JvRoJCf1y4RZg"


class TestErrorEvent:
    """测试错误事件转换"""

    @pytest.fixture
    def adapter(self) -> CodebuddyAGUIAdapter:
        adapter = CodebuddyAGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        return adapter

    def test_convert_error_event(self, adapter):
        """验证 error 事件转换为 RUN_ERROR"""
        event = load_fixture("error_event")
        result = adapter.convert(event)
        
        assert result is not None
        events = parse_sse_events(result)
        
        assert len(events) == 1
        assert events[0]["type"] == "RUN_ERROR"
        assert events[0]["message"] == "处理超时，请重试"


class TestResultEvent:
    """测试 result 事件转换"""

    @pytest.fixture
    def adapter(self) -> CodebuddyAGUIAdapter:
        adapter = CodebuddyAGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        return adapter

    def test_result_success_event_converted_to_text_when_no_streamed_text(self, adapter):
        """验证 result/success 在无增量文本时会补发可见文本并结束消息"""
        event = load_fixture("result_success_event")
        result = adapter.convert(event)

        assert result is not None
        events = parse_sse_events(result)
        assert len(events) == 3
        assert events[0]["type"] == "TEXT_MESSAGE_START"
        assert events[1]["type"] == "TEXT_MESSAGE_CONTENT"
        assert "pyproject.toml" in events[1]["delta"]
        assert events[2]["type"] == "TEXT_MESSAGE_END"


    def test_result_success_not_duplicated_after_streamed_text(self, adapter):
        """验证已有 TEXT_MESSAGE_CONTENT 时 result/success 不重复追加全文"""
        text_event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "hello"}
            }
        }
        _ = adapter.convert(text_event)

        result_event = load_fixture("result_success_event")
        result = adapter.convert(result_event)
        events = parse_sse_events(result)
        assert len(events) == 1
        assert events[0]["type"] == "TEXT_MESSAGE_END"


class TestMixedContentEvent:
    """测试混合内容事件（text + tool_use）"""

    @pytest.fixture
    def adapter(self) -> CodebuddyAGUIAdapter:
        adapter = CodebuddyAGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        return adapter

    def test_convert_mixed_content(self, adapter):
        """验证混合内容事件正确转换"""
        event = load_fixture("mixed_content_event")
        result = adapter.convert(event)
        
        assert result is not None
        events = parse_sse_events(result)
        
        # 应该按顺序处理：TEXT_MESSAGE_START, TEXT_MESSAGE_CONTENT, TOOL_CALL_START, TOOL_CALL_ARGS
        assert len(events) >= 3
        
        # 验证文本消息
        text_start = next((e for e in events if e["type"] == "TEXT_MESSAGE_START"), None)
        assert text_start is not None
        
        text_content = next((e for e in events if e["type"] == "TEXT_MESSAGE_CONTENT"), None)
        assert text_content is not None
        assert "read the file" in text_content["delta"]
        
        # 验证工具调用
        tool_start = next((e for e in events if e["type"] == "TOOL_CALL_START"), None)
        assert tool_start is not None
        assert tool_start["toolCallName"] == "Read"


class TestEndEvent:
    """测试结束事件生成"""

    @pytest.fixture
    def adapter(self) -> CodebuddyAGUIAdapter:
        adapter = CodebuddyAGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        adapter.state.run_started = True
        adapter.state.message_started = True
        adapter.state.current_message_id = "codebuddy-msg-test"
        return adapter

    def test_create_end_event(self, adapter):
        """验证正常结束事件"""
        result = adapter.create_end_event()
        events = parse_sse_events(result)
        
        # 应该有 TEXT_MESSAGE_END 和 RUN_FINISHED
        assert len(events) == 2
        assert events[0]["type"] == "TEXT_MESSAGE_END"
        assert events[1]["type"] == "RUN_FINISHED"

    def test_create_end_event_with_error(self, adapter):
        """验证错误结束事件"""
        result = adapter.create_end_event(is_error=True, error_msg="Test error")
        events = parse_sse_events(result)
        
        # 应该有 TEXT_MESSAGE_END, RUN_ERROR, RUN_FINISHED
        assert len(events) == 3
        assert events[0]["type"] == "TEXT_MESSAGE_END"
        assert events[1]["type"] == "RUN_ERROR"
        assert events[1]["message"] == "Test error"
        assert events[2]["type"] == "RUN_FINISHED"


class TestEdgeCases:
    """测试边界情况"""

    @pytest.fixture
    def adapter(self) -> CodebuddyAGUIAdapter:
        adapter = CodebuddyAGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        return adapter

    def test_none_event(self, adapter):
        """测试 None 事件"""
        result = adapter.convert(None)
        assert result is None

    def test_empty_dict_event(self, adapter):
        """测试空字典事件"""
        result = adapter.convert({})
        assert result is None

    def test_unknown_type_event(self, adapter):
        """测试未知类型事件"""
        result = adapter.convert({"type": "unknown_type", "data": "test"})
        assert result is None

    def test_topic_event_ignored(self, adapter):
        """测试 topic 事件被忽略"""
        result = adapter.convert({"type": "topic", "content": "some topic"})
        assert result is None

    def test_malformed_assistant_event(self, adapter):
        """测试格式错误的 assistant 事件"""
        # 缺少 message 字段
        result = adapter.convert({"type": "assistant"})
        assert result is None
        
        # message 不是字典
        result = adapter.convert({"type": "assistant", "message": "not a dict"})
        assert result is None
        
        # content 不是列表
        result = adapter.convert({"type": "assistant", "message": {"content": "not a list"}})
        assert result is None

    def test_tool_result_without_message_id(self, adapter):
        """测试没有 message_id 时的工具结果处理"""
        event = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-123",
                        "content": [{"type": "text", "text": "result"}]
                    }
                ]
            }
        }
        # 没有设置 current_message_id
        result = adapter.convert(event)
        assert result is not None
        events = parse_sse_events(result)
        # 应该自动生成 message_id
        assert any(e["type"] == "TOOL_CALL_RESULT" for e in events)


class TestLegacyMessageFormat:
    """测试旧版 message 格式兼容"""

    @pytest.fixture
    def adapter(self) -> CodebuddyAGUIAdapter:
        adapter = CodebuddyAGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        return adapter

    def test_legacy_message_format(self, adapter):
        """测试旧版 message 格式（type=message）"""
        event = {
            "type": "message",
            "role": "assistant",
            "content": "Hello, world!"
        }
        result = adapter.convert(event)
        
        assert result is not None
        events = parse_sse_events(result)
        assert len(events) == 2
        assert events[0]["type"] == "TEXT_MESSAGE_START"
        assert events[1]["type"] == "TEXT_MESSAGE_CONTENT"
        assert events[1]["delta"] == "Hello, world!"

    def test_legacy_message_user_ignored(self, adapter):
        """测试旧版 user 消息被忽略"""
        event = {
            "type": "message",
            "role": "user",
            "content": "User message"
        }
        result = adapter.convert(event)
        assert result is None


class TestSlashCommandResult:
    """测试 slash command 结果事件"""

    @pytest.fixture
    def adapter(self) -> CodebuddyAGUIAdapter:
        adapter = CodebuddyAGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        return adapter

    def test_slash_command_result(self, adapter):
        """测试 slash command 结果转换"""
        event = {
            "type": "result",
            "subtype": "slash_command",
            "content": "Help content here..."
        }
        result = adapter.convert(event)
        
        assert result is not None
        events = parse_sse_events(result)
        
        # 应该有 START, CONTENT, END
        assert len(events) == 3
        assert events[0]["type"] == "TEXT_MESSAGE_START"
        assert events[1]["type"] == "TEXT_MESSAGE_CONTENT"
        assert events[1]["delta"] == "Help content here..."
        assert events[2]["type"] == "TEXT_MESSAGE_END"

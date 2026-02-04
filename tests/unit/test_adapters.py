"""适配器单元测试"""

import pytest
import json
from src.server.adapters import (
    ProtocolType,
    AGUIAdapter,
    detect_protocol_from_body,
)
from src.runtime.events.agui import AGUIEventType


class TestProtocolDetection:
    """协议检测测试"""
    
    def test_detect_agui_from_body(self):
        """测试从请求体检测AG-UI协议"""
        agui_body = {
            "threadId": "test-thread",
            "runId": "test-run",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [],
            "context": [],
            "forwardedProps": {"username": "testuser"},
            "state": {}
        }
        assert detect_protocol_from_body(agui_body) == ProtocolType.AGUI
    
    def test_detect_agui_from_non_agui_body(self):
        """测试从非AG-UI请求体仍返回AG-UI（统一协议）"""
        non_agui_body = {
            "user": "testuser",
            "content": "hello",
            "session_id": "test-session",
            "msg_id": "test-msg"
        }
        # 现在统一返回 AGUI
        assert detect_protocol_from_body(non_agui_body) == ProtocolType.AGUI
    
    def test_detect_partial_agui(self):
        """测试部分AG-UI字段"""
        partial_body = {
            "threadId": "test-thread",
            "messages": [{"role": "user", "content": "hello"}]
        }
        assert detect_protocol_from_body(partial_body) == ProtocolType.AGUI


class TestAGUIAdapter:
    """AG-UI适配器测试"""
    
    @pytest.fixture
    def adapter(self):
        """创建适配器实例"""
        adapter = AGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        return adapter
    
    def test_create_start_event(self, adapter):
        """测试创建开始事件"""
        event = adapter.create_start_event()
        assert event is not None
        
        # 解析SSE数据
        data_line = event.strip().replace("data: ", "")
        data = json.loads(data_line)
        
        assert data["type"] == AGUIEventType.RUN_STARTED.value
        assert data["threadId"] == "test-thread"
        assert data["runId"] == "test-run"
    
    def test_create_end_event(self, adapter):
        """测试创建结束事件"""
        event = adapter.create_end_event()
        assert event is not None
        assert AGUIEventType.RUN_FINISHED.value in event
    
    def test_convert_system_init(self, adapter):
        """测试转换system init事件"""
        claude_event = {
            "type": "system",
            "subtype": "init",
            "session_id": "test-session",
            "tools": ["Bash", "Read"],
            "model": "claude-3"
        }
        
        result = adapter.convert(claude_event)
        assert result is not None
        assert "STATE_SNAPSHOT" in result
    
    def test_convert_text_delta(self, adapter):
        """测试转换文本增量"""
        claude_event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "text_delta",
                    "text": "Hello, world!"
                }
            }
        }
        
        result = adapter.convert(claude_event)
        assert result is not None
        # 应该包含 TEXT_MESSAGE_START 和 TEXT_MESSAGE_CONTENT
        assert "TEXT_MESSAGE_START" in result or "TEXT_MESSAGE_CONTENT" in result
        assert "Hello, world!" in result
    
    def test_convert_tool_use_start(self, adapter):
        """测试转换工具调用开始"""
        # Start tool use
        start_event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "tool_123",
                    "name": "Bash"
                }
            }
        }
        
        # Tool start is delayed until args are received
        result = adapter.convert(start_event)
        
        # Send args to trigger tool start
        args_event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"command": "ls"}'
                }
            }
        }
        result = adapter.convert(args_event)
        
        # Now TOOL_CALL_START should be sent
        assert result is not None
        assert "TOOL_CALL_START" in result
        assert "Bash" in result
    
    def test_convert_tool_args(self, adapter):
        """测试转换工具参数"""
        # 先开始工具调用
        start_event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "tool_123",
                    "name": "Bash"
                }
            }
        }
        adapter.convert(start_event)
        
        # 发送参数
        args_event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"command": "ls"}'
                }
            }
        }
        
        result = adapter.convert(args_event)
        assert result is not None
        assert "TOOL_CALL_ARGS" in result
    
    def test_sanitize_think_tags(self, adapter):
        """测试清理think标签"""
        claude_event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "text_delta",
                    "text": "<think>thinking...</think>Hello!"
                }
            }
        }
        
        result = adapter.convert(claude_event)
        assert result is not None
        assert "<think>" not in result
        assert "Hello!" in result
    
    def test_parse_subagent_tool_calls_simple(self, adapter):
        """测试解析简单的 subagent 工具调用"""
        text = """<tool_call>mcp__test__tool
<arg_key>param1</arg_key><arg_value>value1</arg_value>
<arg_key>param2</arg_key><arg_value>value2</arg_value>
</tool_call>"""
        
        calls, cleaned = adapter._parse_subagent_tool_calls(text)
        
        assert len(calls) == 1
        assert calls[0].tool_name == "mcp__test__tool"
        assert calls[0].arguments == {"param1": "value1", "param2": "value2"}
        assert "<tool_call>" not in cleaned
    
    def test_parse_subagent_tool_calls_multiple(self, adapter):
        """测试解析多个 subagent 工具调用"""
        text = """Some text before
<tool_call>tool1
<arg_key>key1</arg_key><arg_value>val1</arg_value>
</tool_call>
Middle text
<tool_call>tool2
<arg_key>key2</arg_key><arg_value>val2</arg_value>
</tool_call>
Some text after"""
        
        calls, cleaned = adapter._parse_subagent_tool_calls(text)
        
        assert len(calls) == 2
        assert calls[0].tool_name == "tool1"
        assert calls[0].arguments == {"key1": "val1"}
        assert calls[1].tool_name == "tool2"
        assert calls[1].arguments == {"key2": "val2"}
        assert "Some text before" in cleaned
        assert "Middle text" in cleaned
        assert "Some text after" in cleaned
        assert "<tool_call>" not in cleaned
    
    def test_parse_subagent_tool_calls_json_value(self, adapter):
        """测试解析 JSON 格式的参数值"""
        text = """<tool_call>test_tool
<arg_key>json_param</arg_key><arg_value>{"nested": "value", "num": 123}</arg_value>
<arg_key>array_param</arg_key><arg_value>[1, 2, 3]</arg_value>
</tool_call>"""
        
        calls, cleaned = adapter._parse_subagent_tool_calls(text)
        
        assert len(calls) == 1
        assert calls[0].arguments["json_param"] == {"nested": "value", "num": 123}
        assert calls[0].arguments["array_param"] == [1, 2, 3]
    
    def test_parse_subagent_tool_calls_no_tool_call(self, adapter):
        """测试没有 tool_call 标签的文本"""
        text = "Just some regular text without tool calls"
        
        calls, cleaned = adapter._parse_subagent_tool_calls(text)
        
        assert len(calls) == 0
        assert cleaned == text
    
    def test_parse_subagent_tool_calls_empty(self, adapter):
        """测试空文本"""
        calls, cleaned = adapter._parse_subagent_tool_calls("")
        
        assert len(calls) == 0
        assert cleaned == ""
    
    def test_generate_subagent_tool_events(self, adapter):
        """测试生成 subagent 工具调用事件"""
        from src.runtime.adapters import ParsedToolCall
        
        call = ParsedToolCall(
            tool_name="mcp__NOS-MCP__dify_knowledge_retrieve",
            arguments={"dataset_id": "test-id", "query": "test query"},
            tool_id="subagent_test123"
        )
        
        events = adapter._generate_subagent_tool_events(call)
        
        # 应该有 3 个事件: ToolCallStart, ToolCallArgs, ToolCallEnd
        assert len(events) == 3
        
        # 验证事件内容
        combined = "".join(events)
        assert "TOOL_CALL_START" in combined
        assert "TOOL_CALL_ARGS" in combined
        assert "TOOL_CALL_END" in combined
        assert "subagent_test123" in combined
        assert "mcp__NOS-MCP__dify_knowledge_retrieve" in combined
    
    def test_handle_user_event_with_subagent_calls(self, adapter):
        """测试处理包含 subagent 工具调用的 user 事件"""
        # 模拟 Task 工具的 tool_result，包含 subagent 的工具调用
        event = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "task_123",
                        "content": """Task completed.
<tool_call>mcp__test__search
<arg_key>query</arg_key><arg_value>test search</arg_value>
</tool_call>
Final result: success""",
                        "is_error": False
                    }
                ]
            }
        }
        
        result = adapter.convert(event)
        
        assert result is not None
        # 应该包含 subagent 的工具调用事件
        assert "TOOL_CALL_START" in result
        assert "mcp__test__search" in result
        # 应该包含主工具的结果
        assert "TOOL_CALL_RESULT" in result
        assert "TOOL_CALL_END" in result
        # 清理后的结果不应包含 tool_call 标签
        assert "<tool_call>" not in result


class TestAGUIRequest:
    """AG-UI请求模型测试"""
    
    def test_parse_agui_request(self):
        """测试解析AG-UI请求"""
        from src.runtime.events.agui import AGUIRequest
        
        data = {
            "threadId": "test-thread",
            "runId": "test-run",
            "messages": [
                {"role": "user", "content": "Hello", "id": "msg-1"}
            ],
            "tools": [],
            "context": [],
            "forwardedProps": {"username": "testuser"},
            "state": {}
        }
        
        request = AGUIRequest.model_validate(data)
        assert request.threadId == "test-thread"
        assert request.runId == "test-run"
        assert request.get_user_content() == "Hello"
        assert request.get_username() == "testuser"
    
    def test_convert_to_request_model(self):
        """测试转换为RequestModel格式"""
        from src.runtime.events.agui import AGUIRequest
        
        data = {
            "threadId": "test-thread",
            "runId": "test-run",
            "messages": [
                {"role": "user", "content": "Hello", "id": "msg-1"}
            ],
            "tools": [],
            "context": [],
            "forwardedProps": {"username": "testuser"},
            "state": {}
        }
        
        request = AGUIRequest.model_validate(data)
        request_dict = request.to_legacy_request()
        
        assert request_dict["user"] == "testuser"
        assert request_dict["content"] == "Hello"
        assert request_dict["session_id"] == "test-thread"
        assert request_dict["msg_id"] == "test-run"
    
    def test_get_response_url(self):
        """测试从rawCallback提取response_url"""
        from src.runtime.events.agui import AGUIRequest
        
        data = {
            "threadId": "test-thread",
            "runId": "test-run",
            "messages": [{"role": "user", "content": "Hello"}],
            "forwardedProps": {
                "username": "testuser",
                "rawCallback": {
                    "msgid": "msg-123",
                    "response_url": "https://example.com/callback"
                }
            }
        }
        
        request = AGUIRequest.model_validate(data)
        assert request.get_response_url() == "https://example.com/callback"
        assert request.get_msg_id() == "msg-123"
    
    def test_get_response_url_missing(self):
        """测试无rawCallback时返回None"""
        from src.runtime.events.agui import AGUIRequest
        
        data = {
            "threadId": "test-thread",
            "runId": "test-run",
            "messages": [{"role": "user", "content": "Hello"}],
            "forwardedProps": {"username": "testuser"}
        }
        
        request = AGUIRequest.model_validate(data)
        assert request.get_response_url() is None
        assert request.get_msg_id() is None
    
    def test_to_request_model_with_response_url(self):
        """测试转换RequestModel格式时包含response_url"""
        from src.runtime.events.agui import AGUIRequest
        
        data = {
            "threadId": "test-thread",
            "runId": "test-run",
            "messages": [{"role": "user", "content": "Hello"}],
            "forwardedProps": {
                "username": "testuser",
                "rawCallback": {
                    "msgid": "msg-123",
                    "response_url": "https://example.com/callback"
                }
            }
        }
        
        request = AGUIRequest.model_validate(data)
        request_dict = request.to_legacy_request()
        
        assert request_dict["response_url"] == "https://example.com/callback"
        assert request_dict["msg_id"] == "msg-123"


class TestCallbackHandler:
    """回调处理器测试"""
    
    def test_agui_events_to_markdown(self):
        """测试AG-UI事件转markdown"""
        from src.server.services.callback_handler import CallbackHandler
        
        handler = CallbackHandler()
        
        events = [
            'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg-1","delta":"Hello "}\n\n',
            'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg-1","delta":"World!"}\n\n',
            'data: {"type":"TOOL_CALL_START","toolCallId":"tool-1","toolCallName":"Bash"}\n\n',
            'data: {"type":"TOOL_CALL_RESULT","toolCallId":"tool-1","content":"result"}\n\n',
        ]
        
        markdown_parts = handler.agui_events_to_markdown(events)
        
        assert len(markdown_parts) == 4
        assert markdown_parts[0] == "Hello "
        assert markdown_parts[1] == "World!"
        assert "Bash" in markdown_parts[2]
        assert "result" in markdown_parts[3]
    
    def test_agui_events_to_markdown_empty(self):
        """测试空事件列表"""
        from src.server.services.callback_handler import CallbackHandler
        
        handler = CallbackHandler()
        markdown_parts = handler.agui_events_to_markdown([])
        
        assert markdown_parts == []

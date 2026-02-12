"""Provider 路由集成测试

覆盖当前已存在的能力：在 `/chat/stream/{agent}` 中可通过 provider 选择不同后端。
这些用例会在重构（core + provider registry）前后保持不变，用于防止路由行为漂移。
"""

import json
from unittest.mock import patch

import pytest

from src.runtime.stores.session_storage import get_session_storage

# All test session IDs used in this module — cleaned up after each test.
_TEST_SESSION_IDS = [
    "t-gem", "t-gem-int", "t-codex-int", "t-cb", "t-cla", "t-cla-int",
    "t-meta", "t-cb-init", "t-cb-tool", "t-cb-err", "t-cb-mix", "t-cb-slash",
]


@pytest.fixture(autouse=True)
def _cleanup_test_sessions():
    """Clean up test session data from Redis before and after each test."""
    storage = get_session_storage()
    for sid in _TEST_SESSION_IDS:
        storage.delete_session(sid)
    yield
    for sid in _TEST_SESSION_IDS:
        storage.delete_session(sid)


def _agui_body(thread_id: str, run_id: str, provider: str | None = None):
    body = {
        "threadId": thread_id,
        "runId": run_id,
        "messages": [{"id": "u1", "role": "user", "content": "hi"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
        "state": {},
    }
    if provider:
        body["provider"] = provider
        body["forwardedProps"]["provider"] = provider
    return body


async def _collect_agui_events(response):
    events = []
    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue
        payload = line.replace("data:", "", 1).strip()
        if not payload:
            continue
        try:
            events.append(json.loads(payload))
        except Exception:
            continue
    return events


class TestProviderRouting:
    @pytest.mark.asyncio
    async def test_agui_provider_gemini_uses_gemini_adapter(self, client):
        async def gemini_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            # GeminiAGUIAdapter expects event.type == "message"
            yield json.dumps({"type": "message", "role": "assistant", "content": "Hello"})

        async def claude_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            raise AssertionError("CLIExecutor.execute should not be used when provider=gemini")

        with patch(
            "src.server.services.stream_handler.GeminiExecutor.execute",
            new=gemini_execute,
        ), patch(
            "src.server.services.stream_handler.CLIExecutor.execute",
            new=claude_execute,
        ):
            body = _agui_body("t-gem", "r-gem", provider="gemini")
            async with client.stream("POST", "/chat/stream/ubuntu", json=body) as resp:
                assert resp.status_code == 200
                events = await _collect_agui_events(resp)

        # Gemini adapter 生成的 messageId 以 gemini-msg- 开头
        message_ids = [e.get("messageId") for e in events if isinstance(e, dict) and "messageId" in e]
        assert any(isinstance(mid, str) and mid.startswith("gemini-msg-") for mid in message_ids)

    @pytest.mark.asyncio
    async def test_agui_provider_gemini_internal_uses_gemini_adapter(self, client):
        async def gemini_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            yield json.dumps({"type": "message", "role": "assistant", "content": "Hello"})

        async def claude_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            raise AssertionError("CLIExecutor.execute should not be used when provider=gemini-internal")

        async def codex_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            raise AssertionError("CodexCLIExecutor.execute should not be used when provider=gemini-internal")

        with patch(
            "src.server.services.stream_handler.GeminiExecutor.execute",
            new=gemini_execute,
        ), patch(
            "src.server.services.stream_handler.CLIExecutor.execute",
            new=claude_execute,
        ), patch(
            "src.server.services.stream_handler.CodexCLIExecutor.execute",
            new=codex_execute,
        ):
            body = _agui_body("t-gem-int", "r-gem-int", provider="gemini-internal")
            async with client.stream("POST", "/chat/stream/ubuntu", json=body) as resp:
                assert resp.status_code == 200
                events = await _collect_agui_events(resp)

        message_ids = [e.get("messageId") for e in events if isinstance(e, dict) and "messageId" in e]
        assert any(isinstance(mid, str) and mid.startswith("gemini-msg-") for mid in message_ids)

    @pytest.mark.asyncio
    async def test_agui_provider_codex_internal_uses_codex_adapter(self, client):
        async def codex_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            yield json.dumps({"type": "thread.started", "thread_id": "t-123"})
            yield json.dumps({
                "type": "item.completed",
                "item": {"id": "item-1", "type": "agent_message", "text": "Hello"},
            })

        async def claude_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            raise AssertionError("CLIExecutor.execute should not be used when provider=codex-internal")

        async def gemini_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            raise AssertionError("GeminiExecutor.execute should not be used when provider=codex-internal")

        with patch(
            "src.server.services.stream_handler.CodexCLIExecutor.execute",
            new=codex_execute,
        ), patch(
            "src.server.services.stream_handler.CLIExecutor.execute",
            new=claude_execute,
        ), patch(
            "src.server.services.stream_handler.GeminiExecutor.execute",
            new=gemini_execute,
        ):
            body = _agui_body("t-codex-int", "r-codex-int", provider="codex-internal")
            async with client.stream("POST", "/chat/stream/ubuntu", json=body) as resp:
                assert resp.status_code == 200
                events = await _collect_agui_events(resp)

        message_ids = [e.get("messageId") for e in events if isinstance(e, dict) and "messageId" in e]
        assert any(isinstance(mid, str) and mid.startswith("codex-msg-") for mid in message_ids)

    @pytest.mark.asyncio
    async def test_agui_provider_codebuddy_uses_codebuddy_adapter(self, client):
        async def codebuddy_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            # CodebuddyAGUIAdapter expects event.type == "message"
            yield json.dumps({"type": "message", "role": "assistant", "content": "Hello"})

        async def claude_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            raise AssertionError("CLIExecutor.execute should not be used when provider=codebuddy")

        with patch(
            "src.server.services.stream_handler.CodebuddyCLIExecutor.execute",
            new=codebuddy_execute,
        ), patch(
            "src.server.services.stream_handler.CLIExecutor.execute",
            new=claude_execute,
        ):
            body = _agui_body("t-cb", "r-cb", provider="codebuddy")
            async with client.stream("POST", "/chat/stream/ubuntu", json=body) as resp:
                assert resp.status_code == 200
                events = await _collect_agui_events(resp)

        message_ids = [e.get("messageId") for e in events if isinstance(e, dict) and "messageId" in e]
        assert any(isinstance(mid, str) and mid.startswith("codebuddy-msg-") for mid in message_ids)

    @pytest.mark.asyncio
    async def test_agui_default_provider_uses_claude_executor(self, client):
        async def gemini_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            raise AssertionError("GeminiExecutor.execute should not be used by default")

        async def claude_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            # Claude adapter expects CLI stream_event shape
            yield json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "Hello"},
                    },
                }
            )
            yield json.dumps({"type": "stream_event", "event": {"type": "message_stop"}})

        with patch(
            "src.server.services.stream_handler.GeminiExecutor.execute",
            new=gemini_execute,
        ), patch(
            "src.server.services.stream_handler.CLIExecutor.execute",
            new=claude_execute,
        ):
            body = _agui_body("t-cla", "r-cla", provider=None)
            async with client.stream("POST", "/chat/stream/ubuntu", json=body) as resp:
                assert resp.status_code == 200
                events = await _collect_agui_events(resp)

        # 默认 claude 不应生成 gemini-msg- 前缀
        message_ids = [e.get("messageId") for e in events if isinstance(e, dict) and "messageId" in e]
        assert not any(isinstance(mid, str) and mid.startswith("gemini-msg-") for mid in message_ids)

    @pytest.mark.asyncio
    async def test_agui_provider_claude_internal_uses_claude_executor(self, client):
        async def gemini_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            raise AssertionError("GeminiExecutor.execute should not be used when provider=claude-internal")

        async def codex_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            raise AssertionError("CodexCLIExecutor.execute should not be used when provider=claude-internal")

        async def claude_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            yield json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "Hello"},
                    },
                }
            )
            yield json.dumps({"type": "stream_event", "event": {"type": "message_stop"}})

        with patch(
            "src.server.services.stream_handler.GeminiExecutor.execute",
            new=gemini_execute,
        ), patch(
            "src.server.services.stream_handler.CodexCLIExecutor.execute",
            new=codex_execute,
        ), patch(
            "src.server.services.stream_handler.CLIExecutor.execute",
            new=claude_execute,
        ):
            body = _agui_body("t-cla-int", "r-cla-int", provider="claude-internal")
            async with client.stream("POST", "/chat/stream/ubuntu", json=body) as resp:
                assert resp.status_code == 200
                events = await _collect_agui_events(resp)

        event_types = [e.get("type") for e in events]
        assert "TEXT_MESSAGE_CONTENT" in event_types

    @pytest.mark.asyncio
    async def test_provider_falls_back_to_session_meta(self, client):
        class _Meta:
            def __init__(self, provider: str):
                self.provider = provider

        class _Storage:
            def get_session_meta(self, session_id: str):
                if session_id == "t-meta":
                    return _Meta("gemini")
                return None

        async def gemini_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            yield json.dumps({"type": "message", "role": "assistant", "content": "FromMeta"})

        async def claude_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            raise AssertionError("CLIExecutor.execute should not be used when session meta provider=gemini")

        with patch(
            "src.server.providers.registry.get_session_storage",
            return_value=_Storage(),
        ), patch(
            "src.server.services.stream_handler.GeminiExecutor.execute",
            new=gemini_execute,
        ), patch(
            "src.server.services.stream_handler.CLIExecutor.execute",
            new=claude_execute,
        ):
            body = _agui_body("t-meta", "r-meta", provider=None)
            async with client.stream("POST", "/chat/stream/ubuntu", json=body) as resp:
                assert resp.status_code == 200
                events = await _collect_agui_events(resp)

        message_ids = [e.get("messageId") for e in events if isinstance(e, dict) and "messageId" in e]
        assert any(isinstance(mid, str) and mid.startswith("gemini-msg-") for mid in message_ids)


class TestCodebuddyProvider:
    """Codebuddy Provider 集成测试"""

    @pytest.mark.asyncio
    async def test_codebuddy_init_event(self, client):
        """测试 Codebuddy system/init 事件转换"""
        async def codebuddy_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            yield json.dumps({
                "type": "system",
                "subtype": "init",
                "session_id": "test-session",
                "model": "claude-4.5"
            })
            yield json.dumps({
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "Hello"}]
                }
            })

        with patch(
            "src.server.services.stream_handler.CodebuddyCLIExecutor.execute",
            new=codebuddy_execute,
        ):
            body = _agui_body("t-cb-init", "r-cb-init", provider="codebuddy")
            async with client.stream("POST", "/chat/stream/ubuntu", json=body) as resp:
                assert resp.status_code == 200
                events = await _collect_agui_events(resp)

        # 应该有 RUN_STARTED 事件
        assert any(e.get("type") == "RUN_STARTED" for e in events)
        # 应该有 TEXT_MESSAGE_START 事件
        assert any(e.get("type") == "TEXT_MESSAGE_START" for e in events)

    @pytest.mark.asyncio
    async def test_codebuddy_tool_use_flow(self, client):
        """测试 Codebuddy 工具调用流程"""
        async def codebuddy_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            yield json.dumps({
                "type": "system",
                "subtype": "init",
                "session_id": "test-session"
            })
            yield json.dumps({
                "type": "assistant",
                "message": {
                    "content": [{
                        "type": "tool_use",
                        "id": "tool_123",
                        "name": "Read",
                        "input": {"file_path": "/test/file.txt"}
                    }]
                }
            })
            yield json.dumps({
                "type": "user",
                "message": {
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": "tool_123",
                        "content": [{"type": "text", "text": "file content"}]
                    }]
                }
            })
            yield json.dumps({
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "Done reading"}]
                }
            })

        with patch(
            "src.server.services.stream_handler.CodebuddyCLIExecutor.execute",
            new=codebuddy_execute,
        ):
            body = _agui_body("t-cb-tool", "r-cb-tool", provider="codebuddy")
            async with client.stream("POST", "/chat/stream/ubuntu", json=body) as resp:
                assert resp.status_code == 200
                events = await _collect_agui_events(resp)

        # 验证工具调用事件序列
        event_types = [e.get("type") for e in events]
        assert "TOOL_CALL_START" in event_types
        assert "TOOL_CALL_ARGS" in event_types
        assert "TOOL_CALL_RESULT" in event_types
        assert "TOOL_CALL_END" in event_types

        # 验证工具调用 ID
        tool_start = next((e for e in events if e.get("type") == "TOOL_CALL_START"), None)
        assert tool_start is not None
        assert tool_start.get("toolCallId") == "tool_123"
        assert tool_start.get("toolCallName") == "Read"

    @pytest.mark.asyncio
    async def test_codebuddy_error_handling(self, client):
        """测试 Codebuddy 错误事件处理"""
        async def codebuddy_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            yield json.dumps({
                "type": "system",
                "subtype": "init",
                "session_id": "test-session"
            })
            yield json.dumps({
                "type": "error",
                "message": "Test error message"
            })

        with patch(
            "src.server.services.stream_handler.CodebuddyCLIExecutor.execute",
            new=codebuddy_execute,
        ):
            body = _agui_body("t-cb-err", "r-cb-err", provider="codebuddy")
            async with client.stream("POST", "/chat/stream/ubuntu", json=body) as resp:
                assert resp.status_code == 200
                events = await _collect_agui_events(resp)

        # 应该有 RUN_ERROR 事件
        error_event = next((e for e in events if e.get("type") == "RUN_ERROR"), None)
        assert error_event is not None
        assert error_event.get("message") == "Test error message"

    @pytest.mark.asyncio
    async def test_codebuddy_mixed_content(self, client):
        """测试 Codebuddy 混合内容（text + tool_use）"""
        async def codebuddy_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            yield json.dumps({
                "type": "system",
                "subtype": "init",
                "session_id": "test-session"
            })
            yield json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Let me read that file"},
                        {
                            "type": "tool_use",
                            "id": "tool_mixed_001",
                            "name": "Read",
                            "input": {"file_path": "/test.txt"}
                        }
                    ]
                }
            })

        with patch(
            "src.server.services.stream_handler.CodebuddyCLIExecutor.execute",
            new=codebuddy_execute,
        ):
            body = _agui_body("t-cb-mix", "r-cb-mix", provider="codebuddy")
            async with client.stream("POST", "/chat/stream/ubuntu", json=body) as resp:
                assert resp.status_code == 200
                events = await _collect_agui_events(resp)

        event_types = [e.get("type") for e in events]
        # 应该按顺序有文本消息和工具调用
        assert "TEXT_MESSAGE_START" in event_types
        assert "TEXT_MESSAGE_CONTENT" in event_types
        assert "TOOL_CALL_START" in event_types

    @pytest.mark.asyncio
    async def test_codebuddy_slash_command_result(self, client):
        """测试 Codebuddy slash command 结果"""
        async def codebuddy_execute(self, request_model, exec_user: str, output_format: str = "raw"):
            yield json.dumps({
                "type": "system",
                "subtype": "init",
                "session_id": "test-session"
            })
            yield json.dumps({
                "type": "result",
                "subtype": "slash_command",
                "content": "Help content here"
            })

        with patch(
            "src.server.services.stream_handler.CodebuddyCLIExecutor.execute",
            new=codebuddy_execute,
        ):
            body = _agui_body("t-cb-slash", "r-cb-slash", provider="codebuddy")
            async with client.stream("POST", "/chat/stream/ubuntu", json=body) as resp:
                assert resp.status_code == 200
                events = await _collect_agui_events(resp)

        event_types = [e.get("type") for e in events]
        # slash command 结果应该生成完整的消息序列
        assert "TEXT_MESSAGE_START" in event_types
        assert "TEXT_MESSAGE_CONTENT" in event_types
        assert "TEXT_MESSAGE_END" in event_types

        # 验证内容
        content_event = next((e for e in events if e.get("type") == "TEXT_MESSAGE_CONTENT"), None)
        assert content_event is not None
        assert content_event.get("delta") == "Help content here"

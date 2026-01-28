"""Provider 路由集成测试

覆盖当前已存在的能力：在 `/chat/stream/{agent}` 中可通过 provider 选择不同后端。
这些用例会在重构（core + provider registry）前后保持不变，用于防止路由行为漂移。
"""

import json
from unittest.mock import patch

import pytest


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
        async def gemini_execute(self, request_model, agent_name: str, output_format: str = "raw"):
            # GeminiAGUIAdapter expects event.type == "message"
            yield json.dumps({"type": "message", "role": "assistant", "content": "Hello"})

        async def claude_execute(self, request_model, agent_name: str, output_format: str = "raw"):
            raise AssertionError("CCRExecutor.execute should not be used when provider=gemini")

        with patch(
            "src.providers.claude_code_api.services.stream_handler.GeminiExecutor.execute",
            new=gemini_execute,
        ), patch(
            "src.providers.claude_code_api.services.stream_handler.CCRExecutor.execute",
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
    async def test_agui_default_provider_uses_claude_executor(self, client):
        async def gemini_execute(self, request_model, agent_name: str, output_format: str = "raw"):
            raise AssertionError("GeminiExecutor.execute should not be used by default")

        async def claude_execute(self, request_model, agent_name: str, output_format: str = "raw"):
            # Claude adapter expects CCR stream_event shape
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
            "src.providers.claude_code_api.services.stream_handler.GeminiExecutor.execute",
            new=gemini_execute,
        ), patch(
            "src.providers.claude_code_api.services.stream_handler.CCRExecutor.execute",
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
    async def test_provider_falls_back_to_session_meta(self, client):
        class _Meta:
            def __init__(self, provider: str):
                self.provider = provider

        class _Storage:
            def get_session_meta(self, session_id: str):
                if session_id == "t-meta":
                    return _Meta("gemini")
                return None

        async def gemini_execute(self, request_model, agent_name: str, output_format: str = "raw"):
            yield json.dumps({"type": "message", "role": "assistant", "content": "FromMeta"})

        async def claude_execute(self, request_model, agent_name: str, output_format: str = "raw"):
            raise AssertionError("CCRExecutor.execute should not be used when session meta provider=gemini")

        with patch(
            "src.providers.claude_code_api.services.stream_handler.get_session_storage",
            return_value=_Storage(),
        ), patch(
            "src.providers.claude_code_api.services.stream_handler.GeminiExecutor.execute",
            new=gemini_execute,
        ), patch(
            "src.providers.claude_code_api.services.stream_handler.CCRExecutor.execute",
            new=claude_execute,
        ):
            body = _agui_body("t-meta", "r-meta", provider=None)
            async with client.stream("POST", "/chat/stream/ubuntu", json=body) as resp:
                assert resp.status_code == 200
                events = await _collect_agui_events(resp)

        message_ids = [e.get("messageId") for e in events if isinstance(e, dict) and "messageId" in e]
        assert any(isinstance(mid, str) and mid.startswith("gemini-msg-") for mid in message_ids)

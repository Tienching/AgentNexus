"""流式响应集成测试"""

import pytest
import json
import asyncio
import warnings
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient


class TestStreamResponse:
    """流式响应测试"""

    @pytest.mark.asyncio
    async def test_stream_response_format(self, client: AsyncClient, sample_request):
        """测试流式响应格式"""
        # 模拟CLI执行器输出
        mock_cli_output = [
            json.dumps({
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "你好"}
                }
            }),
            json.dumps({
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "，"}
                }
            }),
            json.dumps({
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "世界"}
                }
            }),
            json.dumps({
                "type": "stream_event",
                "event": {"type": "message_stop"}
            })
        ]

        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = AsyncMock()
            # CLIExecutor._process_stream() uses stdout.readline(), not __aiter__
            mock_process.stdout.readline = AsyncMock(
                side_effect=[(line + "\n").encode() for line in mock_cli_output] + [b""]
            )
            mock_process.stderr.read = AsyncMock(return_value=b"")
            mock_process.wait.return_value = None
            mock_subprocess.return_value = mock_process

            async with client.stream("POST", "/chat/stream/testuser", json=sample_request) as response:
                assert response.status_code == 200

                events = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str:
                            events.append(json.loads(data_str))

                # 验证事件格式（AG-UI）
                assert len(events) > 0
                types = [e.get("type") for e in events if isinstance(e, dict)]
                assert "RUN_STARTED" in types
                assert "RUN_FINISHED" in types
                assert "TEXT_MESSAGE_START" in types
                assert "TEXT_MESSAGE_CONTENT" in types

                deltas = [e.get("delta", "") for e in events if e.get("type") == "TEXT_MESSAGE_CONTENT"]
                assert "".join(deltas) == "你好，世界"

    @pytest.mark.asyncio
    async def test_stream_with_thinking_tags(self, client: AsyncClient, sample_request):
        """测试包含思考标签的流式响应"""
        mock_cli_output = [
            json.dumps({
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "<think>"}
                }
            }),
            json.dumps({
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "思考中..."}
                }
            }),
            json.dumps({
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "</think>"}
                }
            }),
            json.dumps({
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "实际响应"}
                }
            }),
            json.dumps({
                "type": "stream_event",
                "event": {"type": "message_stop"}
            })
        ]

        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = AsyncMock()
            # CLIExecutor._process_stream() uses stdout.readline(), not __aiter__
            mock_process.stdout.readline = AsyncMock(
                side_effect=[(line + "\n").encode() for line in mock_cli_output] + [b""]
            )
            mock_process.stderr.read = AsyncMock(return_value=b"")
            mock_process.wait.return_value = None
            mock_subprocess.return_value = mock_process

            async with client.stream("POST", "/chat/stream/testuser", json=sample_request) as response:
                assert response.status_code == 200

                events = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str:
                            events.append(json.loads(data_str))

                # 验证思考标签被剥离（AG-UI 内容中不应出现）
                content = "".join(
                    e.get("delta", "") for e in events if e.get("type") == "TEXT_MESSAGE_CONTENT"
                )
                assert "<think>" not in content
                assert "</think>" not in content
                assert "实际响应" in content

    @pytest.mark.asyncio
    async def test_stream_error_handling(self, client: AsyncClient, sample_request):
        """测试流式响应的错误处理"""
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            # 模拟子进程错误
            mock_subprocess.side_effect = Exception("Process failed")

            async with client.stream("POST", "/chat/stream/testuser", json=sample_request) as response:
                assert response.status_code == 200

                events = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str:
                            events.append(json.loads(data_str))

                # 应该至少有一个错误事件（AG-UI RUN_ERROR）
                assert len(events) > 0
                types = [e.get("type") for e in events if isinstance(e, dict)]
                assert "RUN_ERROR" in types
                error_events = [e for e in events if e.get("type") == "RUN_ERROR"]
                assert any("Process failed" in (e.get("message", "")) for e in error_events)

    @pytest.mark.asyncio
    async def test_stream_timeout_handling(self, client: AsyncClient, sample_request):
        """测试流式响应的超时处理"""
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = AsyncMock()

            # 模拟超时（触发 execute() 对 process.wait 的 timeout 分支）
            async def mock_wait():
                await asyncio.sleep(200)  # 超过配置的超时时间

            mock_process.wait = mock_wait
            # _process_stream uses stdout.readline(); return EOF immediately so it reaches wait()
            mock_process.stdout.readline = AsyncMock(side_effect=[b""])
            mock_process.stderr.read = AsyncMock(return_value=b"")
            mock_subprocess.return_value = mock_process

            # 需要设置较短的超时以便测试
            with patch('src.server.config.settings.cli_timeout', 0.1):
                async with client.stream("POST", "/chat/stream/testuser", json=sample_request) as response:
                    assert response.status_code == 200

                    events = []
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if data_str:
                                events.append(json.loads(data_str))

                    # 验证超时响应（AG-UI）
                    assert len(events) > 0
                    types = [e.get("type") for e in events if isinstance(e, dict)]
                    assert "RUN_ERROR" in types
                    assert "RUN_FINISHED" in types
                    error_events = [e for e in events if e.get("type") == "RUN_ERROR"]
                    assert any("超时" in (e.get("message", "")) for e in error_events)

    @pytest.mark.asyncio
    async def test_agui_request_missing_content_does_not_emit_422_deprecation_warning(self, client: AsyncClient):
        """测试 AG-UI 缺少内容时不会触发废弃 422 常量警告"""
        agui_request = {
            "threadId": "test-thread",
            "runId": "test-run",
            "messages": [],
        }

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            response = await client.post("/chat/stream/testuser", json=agui_request)

        assert response.status_code == 422
        assert response.json()["detail"] == "Missing required field: content (or messages for AG-UI)"
        assert not any(
            "HTTP_422_UNPROCESSABLE_ENTITY" in str(warning.message)
            for warning in caught
        )

    @pytest.mark.asyncio
    async def test_agui_multimodal_content_array_streams_without_legacy_422(self, client: AsyncClient):
        """AG-UI 多模态 content 数组应被按顺序送入执行器，而不是被 legacy RequestModel 拒绝"""
        image_url = "https://example.com/case.png"
        agui_request = {
            "threadId": "thread-multimodal",
            "runId": "run-multimodal",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "介绍一下这张图片"},
                        {"type": "binary", "mimeType": "image/png", "url": image_url},
                    ],
                }
            ],
            "forwardedProps": {
                "username": "jonaszchen",
                "provider": "codebuddy",
            },
        }
        mock_cli_output = [
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "这是一张测试图片"}
                    ]
                },
            }),
            json.dumps({"type": "result", "subtype": "success"}),
        ]

        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.stdout.readline = AsyncMock(
                side_effect=[(line + "\n").encode() for line in mock_cli_output] + [b""]
            )
            mock_process.stderr.read = AsyncMock(return_value=b"")
            mock_process.wait.return_value = None
            mock_subprocess.return_value = mock_process

            async with client.stream("POST", "/chat/stream/testuser", json=agui_request) as response:
                assert response.status_code == 200

                events = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str:
                            events.append(json.loads(data_str))

        command = " ".join(str(arg) for arg in mock_subprocess.call_args.args)
        assert "介绍一下这张图片" in command
        assert f"{{image: {image_url}}}" in command
        assert any(event.get("type") == "RUN_FINISHED" for event in events)

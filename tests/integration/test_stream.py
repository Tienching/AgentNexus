"""流式响应集成测试"""

import pytest
import json
import asyncio
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient


class TestStreamResponse:
    """流式响应测试"""

    @pytest.mark.asyncio
    async def test_stream_response_format(self, client: AsyncClient, sample_request):
        """测试流式响应格式"""
        # 模拟CCR输出
        mock_ccr_output = [
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
            # CCRExecutor._process_stream() uses stdout.readline(), not __aiter__
            mock_process.stdout.readline = AsyncMock(
                side_effect=[(line + "\n").encode() for line in mock_ccr_output] + [b""]
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

                # 验证事件格式
                assert len(events) > 0
                for event in events[:-1]:  # 除了最后一个事件
                    assert "response" in event
                    assert "finished" in event
                    assert "global_output" in event
                    assert event["finished"] == False

                # 验证最后一个事件
                last_event = events[-1]
                assert last_event["finished"] == True
                assert last_event["global_output"]["answer_success"] == 1

    @pytest.mark.asyncio
    async def test_stream_with_thinking_tags(self, client: AsyncClient, sample_request):
        """测试包含思考标签的流式响应"""
        mock_ccr_output = [
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
            # CCRExecutor._process_stream() uses stdout.readline(), not __aiter__
            mock_process.stdout.readline = AsyncMock(
                side_effect=[(line + "\n").encode() for line in mock_ccr_output] + [b""]
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

                # 验证思考标签
                responses = [e["response"] for e in events if "response" in e]
                assert "<think>" in responses
                assert "</think>" in responses

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

                # 应该至少有一个错误事件
                assert len(events) > 0
                last_event = events[-1]
                assert last_event["finished"] == True
                # 错误情况下answer_success应该为0
                assert last_event["global_output"]["answer_success"] == 0

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
            with patch('src.providers.claude_code_api.config.settings.ccr_timeout', 0.1):
                async with client.stream("POST", "/chat/stream/testuser", json=sample_request) as response:
                    assert response.status_code == 200

                    events = []
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if data_str:
                                events.append(json.loads(data_str))

                    # 验证超时响应
                    assert len(events) > 0
                    last_event = events[-1]
                    assert last_event["finished"] == True
                    assert "超时" in last_event["response"] or last_event["global_output"]["answer_success"] == 0
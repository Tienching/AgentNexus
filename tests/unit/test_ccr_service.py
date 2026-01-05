"""CCR服务单元测试"""

import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
from src.claude_code_api.ccr_service import CCRCodeService
from src.claude_code_api.models import RequestModel


class TestCCRCodeService:
    """CCRCodeService测试"""

    @pytest.fixture
    def service(self):
        """创建服务实例"""
        return CCRCodeService()

    @pytest.fixture
    def sample_request(self):
        """创建示例请求"""
        return RequestModel(
            user="test_user",
            content="Hello, how are you?",
            msg_id="test_001",
            session_id="session_001",
        )

    def test_build_command(self, service):
        """测试命令构建"""
        content = "Test content"
        cmd = service._build_command(content)

        # 现在cmd是字符串而不是列表
        assert isinstance(cmd, str)
        assert "ccr code" in cmd
        assert "-p" in cmd
        assert "--output-format stream-json" in cmd
        assert "--include-partial-messages" in cmd
        assert "--verbose" in cmd

        # 验证content有正确的引号
        assert "'Test content'" in cmd or '"Test content"' in cmd

        # 验证系统提示词参数
        assert "--append-system-prompt" in cmd

        # 验证allowedTools参数
        assert "--allowedTools" in cmd

    def test_format_sse(self, service):
        """测试SSE格式化"""
        data = {
            "response": "Hello",
            "finished": False,
            "global_output": {"context": "", "answer_success": 0, "docs": []},
        }
        result = service._format_sse(data)

        assert result.startswith("event:delta\n")
        assert "data:" in result
        assert result.endswith("\n\n")

        # 验证数据部分是有效的JSON
        data_part = result.split("data:")[1].strip()
        parsed = json.loads(data_part)
        assert parsed["response"] == "Hello"
        assert parsed["finished"] == False

    def test_format_sse_with_unicode(self, service):
        """测试包含Unicode字符的SSE格式化"""
        data = {
            "response": "你好，世界",
            "finished": False,
            "global_output": {"context": "", "answer_success": 0, "docs": []},
        }
        result = service._format_sse(data)

        # 验证中文字符正确编码
        data_part = result.split("data:")[1].strip()
        parsed = json.loads(data_part)
        assert parsed["response"] == "你好，世界"

    def test_format_sse_with_thinking_tags(self, service):
        """测试思考标签的SSE格式化"""
        data = {
            "response": "<think>",
            "finished": False,
            "global_output": {"context": "", "answer_success": 0, "docs": []},
        }
        result = service._format_sse(data)

        data_part = result.split("data:")[1].strip()
        parsed = json.loads(data_part)
        assert parsed["response"] == "<think>"

    def test_format_sse_finished(self, service):
        """测试完成状态的SSE格式化"""
        data = {
            "response": "",
            "finished": True,
            "global_output": {
                "context": "",
                "answer_success": 1,
                "docs": [
                    {
                        "doc_id": "123",
                        "space_id": "456",
                        "title": "Test Doc",
                        "url": "http://example.com",
                        "score": 0.9,
                    }
                ],
            },
        }
        result = service._format_sse(data)

        data_part = result.split("data:")[1].strip()
        parsed = json.loads(data_part)
        assert parsed["finished"] == True
        assert parsed["global_output"]["answer_success"] == 1
        assert len(parsed["global_output"]["docs"]) == 1

    @pytest.mark.asyncio
    async def test_extract_documents(self, service):
        """测试文档提取（当前为空实现）"""
        docs = await service.extract_documents("Some text with documents")
        assert docs == []

    @pytest.mark.asyncio
    async def test_process_request_with_mock_ccr(self, service, sample_request):
        """测试处理请求（使用模拟的ccr输出）"""
        # 模拟ccr命令的输出
        mock_output = [
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "Hello"},
                    },
                }
            ),
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": " world"},
                    },
                }
            ),
            json.dumps({"type": "stream_event", "event": {"type": "message_stop"}}),
        ]

        with patch("asyncio.create_subprocess_shell") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.stdout.__aiter__.return_value = [
                (line + "\n").encode() for line in mock_output
            ]
            mock_process.wait.return_value = None
            mock_subprocess.return_value = mock_process

            # 收集所有响应
            responses = []
            async for response in service.process_request(sample_request):
                responses.append(response)

            assert len(responses) > 0
            # 验证至少有一个包含"Hello"的响应
            assert any("Hello" in r for r in responses)

    def test_clean_content_enter_chat_event(self, service):
        """测试过滤enter_chat事件"""
        # 测试单独的enter_chat事件
        content = '{"event_type": "enter_chat"}'
        result = service._clean_content(content)
        assert result == ""

    def test_clean_content_normal_message(self, service):
        """测试正常消息不受影响"""
        content = "你好"
        result = service._clean_content(content)
        assert result == "你好"

    def test_clean_content_mixed_content(self, service):
        """测试混合内容正确过滤"""
        content = '{"event_type": "enter_chat"}你好'
        result = service._clean_content(content)
        assert result == "你好"
"""数据模型单元测试"""

import pytest
from pydantic import ValidationError
from src.claude_code_api.models import (
    RequestModel,
    Document,
    GlobalOutput,
    StreamResponse,
    HealthResponse,
    MetricsResponse,
)


class TestRequestModel:
    """RequestModel测试"""

    def test_valid_request_model(self):
        """测试有效的请求模型"""
        data = {
            "user": "test_user",
            "msg_type": "text",
            "content": "Hello",
            "msg_id": "msg_001",
            "raw_msg": "<xml>test</xml>",
            "session_id": "session_001",
            "business_keys": ["key1", "key2"],
        }
        model = RequestModel(**data)
        assert model.user == "test_user"
        assert model.msg_type == "text"
        assert model.content == "Hello"
        assert model.msg_id == "msg_001"
        assert model.session_id == "session_001"
        assert len(model.business_keys) == 2

    def test_minimal_request_model(self):
        """测试最小必需字段的请求模型"""
        data = {
            "user": "test_user",
            "content": "Hello",
        }
        model = RequestModel(**data)
        assert model.user == "test_user"
        assert model.content == "Hello"
        assert model.msg_type == "text"  # 默认值
        assert model.msg_id == ""  # 默认值
        assert model.business_keys == []  # 默认值

    def test_invalid_request_model(self):
        """测试缺少必需字段的请求模型"""
        with pytest.raises(ValidationError):
            RequestModel(user="test_user")  # 缺少content字段


class TestDocument:
    """Document模型测试"""

    def test_valid_document(self):
        """测试有效的文档模型"""
        data = {
            "doc_id": "12345",
            "space_id": "67890",
            "title": "测试文档",
            "url": "http://example.com/doc",
            "score": 0.95,
        }
        doc = Document(**data)
        assert doc.doc_id == "12345"
        assert doc.space_id == "67890"
        assert doc.title == "测试文档"
        assert doc.url == "http://example.com/doc"
        assert doc.score == 0.95

    def test_invalid_document(self):
        """测试缺少必需字段的文档模型"""
        with pytest.raises(ValidationError):
            Document(doc_id="12345", space_id="67890")  # 缺少其他必需字段


class TestGlobalOutput:
    """GlobalOutput模型测试"""

    def test_valid_global_output(self):
        """测试有效的全局输出模型"""
        doc_data = {
            "doc_id": "12345",
            "space_id": "67890",
            "title": "测试文档",
            "url": "http://example.com/doc",
            "score": 0.95,
        }
        data = {
            "context": "测试上下文",
            "answer_success": 1,
            "docs": [doc_data],
        }
        output = GlobalOutput(**data)
        assert output.context == "测试上下文"
        assert output.answer_success == 1
        assert len(output.docs) == 1
        assert output.docs[0].doc_id == "12345"

    def test_default_global_output(self):
        """测试默认值的全局输出模型"""
        output = GlobalOutput()
        assert output.context == ""
        assert output.answer_success == 0
        assert output.docs == []


class TestStreamResponse:
    """StreamResponse模型测试"""

    def test_valid_stream_response(self):
        """测试有效的流响应模型"""
        data = {
            "response": "这是响应内容",
            "finished": False,
            "global_output": {
                "context": "",
                "answer_success": 0,
                "docs": [],
            },
        }
        response = StreamResponse(**data)
        assert response.response == "这是响应内容"
        assert response.finished == False
        assert isinstance(response.global_output, GlobalOutput)

    def test_finished_stream_response(self):
        """测试完成的流响应模型"""
        data = {
            "response": "",
            "finished": True,
            "global_output": {
                "context": "完成",
                "answer_success": 1,
                "docs": [],
            },
        }
        response = StreamResponse(**data)
        assert response.response == ""
        assert response.finished == True
        assert response.global_output.answer_success == 1


class TestHealthResponse:
    """HealthResponse模型测试"""

    def test_valid_health_response(self):
        """测试有效的健康检查响应"""
        data = {
            "status": "healthy",
            "service": "claude-code-api",
            "version": "0.1.0",
        }
        response = HealthResponse(**data)
        assert response.status == "healthy"
        assert response.service == "claude-code-api"
        assert response.version == "0.1.0"


class TestMetricsResponse:
    """MetricsResponse模型测试"""

    def test_valid_metrics_response(self):
        """测试有效的指标响应"""
        data = {
            "version": "0.1.0",
            "ccr_command": "ccr",
            "requests_total": 100,
            "requests_active": 5,
        }
        response = MetricsResponse(**data)
        assert response.version == "0.1.0"
        assert response.ccr_command == "ccr"
        assert response.requests_total == 100
        assert response.requests_active == 5

    def test_default_metrics_response(self):
        """测试默认值的指标响应"""
        data = {
            "version": "0.1.0",
            "ccr_command": "ccr",
        }
        response = MetricsResponse(**data)
        assert response.requests_total == 0
        assert response.requests_active == 0
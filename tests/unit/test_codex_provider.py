"""Codex Provider 单元测试

测试 Codex CLI Executor 和 AG-UI Adapter
"""

import json
import pytest
from unittest.mock import Mock, AsyncMock, patch

from src.providers.codex import CodexExecutor, CodexExecutorConfig, CodexConnection
from src.runtime.adapters.codex import CodexAGUIAdapter


class TestCodexExecutorConfig:
    """CodexExecutorConfig 测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = CodexExecutorConfig()
        assert config.timeout == 120.0
        assert config.codex_command == "codex"
        assert config.mcp_server_mode == "auto"

    def test_custom_config(self):
        """测试自定义配置"""
        config = CodexExecutorConfig(
            timeout=60.0,
            codex_command="/usr/local/bin/codex",
            mcp_server_mode="mcp-server",
        )
        assert config.timeout == 60.0
        assert config.codex_command == "/usr/local/bin/codex"
        assert config.mcp_server_mode == "mcp-server"


class TestCodexConnection:
    """CodexConnection MCP 通信测试"""

    def test_build_mcp_request(self):
        """测试构建 MCP JSON-RPC 请求"""
        conn = CodexConnection()
        
        # 测试请求构建
        request = conn._build_request("test_method", {"key": "value"})
        
        assert request["jsonrpc"] == "2.0"
        assert request["method"] == "test_method"
        assert request["params"] == {"key": "value"}
        assert "id" in request

    def test_build_mcp_notification(self):
        """测试构建 MCP JSON-RPC 通知"""
        conn = CodexConnection()
        
        notification = conn._build_notification("notify_method", {"data": "test"})
        
        assert notification["jsonrpc"] == "2.0"
        assert notification["method"] == "notify_method"
        assert notification["params"] == {"data": "test"}
        assert "id" not in notification


class TestCodexAGUIAdapter:
    """CodexAGUIAdapter 事件转换测试"""

    @pytest.fixture
    def adapter(self):
        """创建适配器实例"""
        adapter = CodexAGUIAdapter()
        adapter.init_state(thread_id="test-thread", run_id="test-run")
        return adapter

    def test_create_start_event(self, adapter):
        """测试创建开始事件"""
        event = adapter.create_start_event()
        assert event is not None
        assert "RUN_STARTED" in event
        assert "test-thread" in event
        assert "test-run" in event

    def test_create_end_event(self, adapter):
        """测试创建结束事件"""
        event = adapter.create_end_event()
        assert event is not None
        assert "RUN_FINISHED" in event

    def test_convert_task_started(self, adapter):
        """测试转换 task_started 事件"""
        codex_event = {
            "type": "task_started",
            "task_id": "task-123",
        }
        
        result = adapter.convert(codex_event)
        # task_started 仅更新内部状态，不直接产生输出
        # 具体行为取决于实现

    def test_convert_agent_message_delta(self, adapter):
        """测试转换 agent_message_delta 事件"""
        codex_event = {
            "type": "agent_message_delta",
            "delta": "Hello, world!",
        }
        
        result = adapter.convert(codex_event)
        assert result is not None
        assert "Hello, world!" in result
        assert "TEXT_MESSAGE" in result

    def test_convert_exec_command_begin(self, adapter):
        """测试转换 exec_command_begin 事件"""
        codex_event = {
            "type": "exec_command_begin",
            "call_id": "cmd-1",
            "command": ["ls", "-la"],
        }
        
        result = adapter.convert(codex_event)
        assert result is not None
        assert "TOOL_CALL_START" in result
        assert "shell" in result.lower() or "exec" in result.lower()

    def test_convert_exec_command_end(self, adapter):
        """测试转换 exec_command_end 事件"""
        # 先开始命令
        adapter.convert({
            "type": "exec_command_begin",
            "call_id": "cmd-1",
            "command": ["ls"],
        })
        
        codex_event = {
            "type": "exec_command_end",
            "call_id": "cmd-1",
            "exit_code": 0,
            "stdout": "file1.txt\nfile2.txt",
        }
        
        result = adapter.convert(codex_event)
        assert result is not None
        assert "TOOL_CALL_RESULT" in result or "TOOL_CALL_END" in result

    def test_convert_patch_apply_begin(self, adapter):
        """测试转换 patch_apply_begin 事件"""
        codex_event = {
            "type": "patch_apply_begin",
            "call_id": "patch-1",
            "file_path": "/path/to/file.py",
        }
        
        result = adapter.convert(codex_event)
        assert result is not None
        assert "TOOL_CALL_START" in result

    def test_convert_patch_apply_end(self, adapter):
        """测试转换 patch_apply_end 事件"""
        # 先开始 patch
        adapter.convert({
            "type": "patch_apply_begin",
            "call_id": "patch-1",
            "file_path": "/path/to/file.py",
        })
        
        codex_event = {
            "type": "patch_apply_end",
            "call_id": "patch-1",
            "success": True,
        }
        
        result = adapter.convert(codex_event)
        assert result is not None
        assert "TOOL_CALL" in result

    def test_convert_task_complete(self, adapter):
        """测试转换 task_complete 事件"""
        codex_event = {
            "type": "task_complete",
            "task_id": "task-123",
            "status": "success",
        }
        
        result = adapter.convert(codex_event)
        # task_complete 通常在流结束时处理

    def test_convert_error_event(self, adapter):
        """测试转换错误事件"""
        codex_event = {
            "type": "error",
            "message": "Something went wrong",
        }
        
        result = adapter.convert(codex_event)
        assert result is not None
        assert "Something went wrong" in result

    def test_create_error_event(self, adapter):
        """测试创建错误事件"""
        event = adapter.create_error_event("Test error message")
        assert event is not None
        assert "RUN_ERROR" in event
        assert "Test error message" in event

    def test_convert_unknown_event_type(self, adapter):
        """测试转换未知事件类型"""
        codex_event = {
            "type": "unknown_event_type",
            "data": "some data",
        }
        
        # 未知事件应该被安全处理
        result = adapter.convert(codex_event)
        # 可能返回 None 或空字符串


class TestCodexExecutor:
    """CodexExecutor 测试"""

    def test_executor_initialization(self):
        """测试 Executor 初始化"""
        config = CodexExecutorConfig(timeout=60.0)
        executor = CodexExecutor(config=config)
        
        assert executor.config.timeout == 60.0

    def test_build_mcp_server_command(self):
        """测试构建 MCP 服务器启动命令"""
        config = CodexExecutorConfig(
            codex_command="codex",
            mcp_server_mode="mcp-server",
        )
        executor = CodexExecutor(config=config)
        
        cmd = executor._build_mcp_server_command()
        
        assert "codex" in cmd
        assert "mcp-server" in cmd or "mcp" in cmd

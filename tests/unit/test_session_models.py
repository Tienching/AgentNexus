# -*- coding: utf-8 -*-
"""Session Models Unit Tests"""

import pytest
import json
import time

from src.claude_code_api.models.session import (
    SessionStatus,
    SessionMeta,
    MessageStatus,
    StoredMessage,
    ToolCallStatus,
    StoredToolCall,
    SessionListResponse,
    SessionMessagesResponse,
)


class TestSessionStatus:
    """SessionStatus enum tests"""

    def test_status_values(self):
        """Test all status values exist"""
        assert SessionStatus.IDLE.value == "idle"
        assert SessionStatus.RUNNING.value == "running"
        assert SessionStatus.COMPLETED.value == "completed"
        assert SessionStatus.ERROR.value == "error"

    def test_status_from_string(self):
        """Test creating status from string"""
        assert SessionStatus("idle") == SessionStatus.IDLE
        assert SessionStatus("running") == SessionStatus.RUNNING
        assert SessionStatus("completed") == SessionStatus.COMPLETED
        assert SessionStatus("error") == SessionStatus.ERROR


class TestSessionMeta:
    """SessionMeta model tests"""

    def test_create_session_meta(self):
        """Test creating session metadata"""
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            run_id="run-456",
            title="Test Session",
            username="testuser",
            agent_name="test-agent",
        )
        
        assert meta.id == "session-123"
        assert meta.thread_id == "thread-123"
        assert meta.run_id == "run-456"
        assert meta.title == "Test Session"
        assert meta.username == "testuser"
        assert meta.agent_name == "test-agent"
        assert meta.status == SessionStatus.IDLE
        assert meta.message_count == 0
        assert meta.created_at > 0
        assert meta.updated_at > 0

    def test_session_meta_defaults(self):
        """Test session metadata default values"""
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="testuser",
        )
        
        assert meta.run_id is None
        assert meta.title == "New Session"
        assert meta.agent_name is None
        assert meta.status == SessionStatus.IDLE
        assert meta.message_count == 0

    def test_session_meta_to_redis_hash(self):
        """Test converting session metadata to Redis hash"""
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            run_id="run-456",
            title="Test Session",
            username="testuser",
            agent_name="test-agent",
            created_at=1704067200000,
            updated_at=1704067200000,
            message_count=5,
            status=SessionStatus.RUNNING,
        )
        
        hash_data = meta.to_redis_hash()
        
        assert hash_data["id"] == "session-123"
        assert hash_data["thread_id"] == "thread-123"
        assert hash_data["run_id"] == "run-456"
        assert hash_data["title"] == "Test Session"
        assert hash_data["username"] == "testuser"
        assert hash_data["agent_name"] == "test-agent"
        assert hash_data["created_at"] == "1704067200000"
        assert hash_data["updated_at"] == "1704067200000"
        assert hash_data["message_count"] == "5"
        assert hash_data["status"] == "running"

    def test_session_meta_to_redis_hash_with_none_values(self):
        """Test Redis hash with None values"""
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="testuser",
        )
        
        hash_data = meta.to_redis_hash()
        
        assert hash_data["run_id"] == ""
        assert hash_data["agent_name"] == ""

    def test_session_meta_from_redis_hash(self):
        """Test creating session metadata from Redis hash"""
        hash_data = {
            "id": "session-123",
            "thread_id": "thread-123",
            "run_id": "run-456",
            "title": "Test Session",
            "username": "testuser",
            "agent_name": "test-agent",
            "created_at": "1704067200000",
            "updated_at": "1704067200000",
            "message_count": "5",
            "status": "running",
        }
        
        meta = SessionMeta.from_redis_hash(hash_data)
        
        assert meta.id == "session-123"
        assert meta.thread_id == "thread-123"
        assert meta.run_id == "run-456"
        assert meta.title == "Test Session"
        assert meta.username == "testuser"
        assert meta.agent_name == "test-agent"
        assert meta.created_at == 1704067200000
        assert meta.updated_at == 1704067200000
        assert meta.message_count == 5
        assert meta.status == SessionStatus.RUNNING

    def test_session_meta_from_redis_hash_with_empty_values(self):
        """Test creating session metadata from Redis hash with empty values"""
        hash_data = {
            "id": "session-123",
            "thread_id": "thread-123",
            "run_id": "",
            "title": "Test Session",
            "username": "testuser",
            "agent_name": "",
            "created_at": "1704067200000",
            "updated_at": "1704067200000",
            "message_count": "0",
            "status": "idle",
        }
        
        meta = SessionMeta.from_redis_hash(hash_data)
        
        assert meta.run_id is None
        assert meta.agent_name is None

    def test_session_meta_roundtrip(self):
        """Test roundtrip conversion to/from Redis hash"""
        original = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            run_id="run-456",
            title="Test Session",
            username="testuser",
            agent_name="test-agent",
            created_at=1704067200000,
            updated_at=1704067200000,
            message_count=5,
            status=SessionStatus.COMPLETED,
        )
        
        hash_data = original.to_redis_hash()
        restored = SessionMeta.from_redis_hash(hash_data)
        
        assert restored.id == original.id
        assert restored.thread_id == original.thread_id
        assert restored.run_id == original.run_id
        assert restored.title == original.title
        assert restored.username == original.username
        assert restored.agent_name == original.agent_name
        assert restored.created_at == original.created_at
        assert restored.updated_at == original.updated_at
        assert restored.message_count == original.message_count
        assert restored.status == original.status


class TestMessageStatus:
    """MessageStatus enum tests"""

    def test_message_status_values(self):
        """Test all message status values"""
        assert MessageStatus.PENDING.value == "pending"
        assert MessageStatus.STREAMING.value == "streaming"
        assert MessageStatus.COMPLETE.value == "complete"
        assert MessageStatus.ERROR.value == "error"


class TestStoredMessage:
    """StoredMessage model tests"""

    def test_create_stored_message(self):
        """Test creating stored message"""
        msg = StoredMessage(
            id="msg-123",
            role="user",
            content="Hello, world!",
        )
        
        assert msg.id == "msg-123"
        assert msg.role == "user"
        assert msg.content == "Hello, world!"
        assert msg.status == MessageStatus.PENDING
        assert msg.tool_call_ids is None
        assert msg.timestamp > 0

    def test_stored_message_with_tool_calls(self):
        """Test stored message with tool calls"""
        msg = StoredMessage(
            id="msg-123",
            role="assistant",
            content="Let me check that for you.",
            status=MessageStatus.COMPLETE,
            tool_call_ids=["tool-1", "tool-2"],
        )
        
        assert msg.tool_call_ids == ["tool-1", "tool-2"]

    def test_stored_message_to_json(self):
        """Test serializing message to JSON"""
        msg = StoredMessage(
            id="msg-123",
            role="user",
            content="Hello, world!",
            timestamp=1704067200000,
            status=MessageStatus.COMPLETE,
        )
        
        json_str = msg.to_json()
        data = json.loads(json_str)
        
        assert data["id"] == "msg-123"
        assert data["role"] == "user"
        assert data["content"] == "Hello, world!"
        assert data["timestamp"] == 1704067200000
        assert data["status"] == "complete"

    def test_stored_message_from_json(self):
        """Test deserializing message from JSON"""
        json_str = json.dumps({
            "id": "msg-123",
            "role": "user",
            "content": "Hello, world!",
            "timestamp": 1704067200000,
            "status": "complete",
            "tool_call_ids": None,
        })
        
        msg = StoredMessage.from_json(json_str)
        
        assert msg.id == "msg-123"
        assert msg.role == "user"
        assert msg.content == "Hello, world!"
        assert msg.timestamp == 1704067200000
        assert msg.status == MessageStatus.COMPLETE

    def test_stored_message_roundtrip(self):
        """Test roundtrip conversion to/from JSON"""
        original = StoredMessage(
            id="msg-123",
            role="assistant",
            content="Test content",
            timestamp=1704067200000,
            status=MessageStatus.STREAMING,
            tool_call_ids=["tool-1"],
        )
        
        json_str = original.to_json()
        restored = StoredMessage.from_json(json_str)
        
        assert restored.id == original.id
        assert restored.role == original.role
        assert restored.content == original.content
        assert restored.timestamp == original.timestamp
        assert restored.status == original.status
        assert restored.tool_call_ids == original.tool_call_ids

    def test_stored_message_unicode_content(self):
        """Test message with unicode content"""
        msg = StoredMessage(
            id="msg-123",
            role="user",
            content="你好，世界！🌍",
        )
        
        json_str = msg.to_json()
        restored = StoredMessage.from_json(json_str)
        
        assert restored.content == "你好，世界！🌍"


class TestToolCallStatus:
    """ToolCallStatus enum tests"""

    def test_tool_call_status_values(self):
        """Test all tool call status values"""
        assert ToolCallStatus.PENDING.value == "pending"
        assert ToolCallStatus.EXECUTING.value == "executing"
        assert ToolCallStatus.COMPLETED.value == "completed"
        assert ToolCallStatus.FAILED.value == "failed"


class TestStoredToolCall:
    """StoredToolCall model tests"""

    def test_create_stored_tool_call(self):
        """Test creating stored tool call"""
        tool_call = StoredToolCall(
            id="tool-123",
            tool_name="read_file",
            args={"path": "/tmp/test.txt"},
        )
        
        assert tool_call.id == "tool-123"
        assert tool_call.tool_name == "read_file"
        assert tool_call.args == {"path": "/tmp/test.txt"}
        assert tool_call.status == ToolCallStatus.PENDING
        assert tool_call.result is None
        assert tool_call.error is None
        assert tool_call.start_time > 0
        assert tool_call.end_time is None

    def test_stored_tool_call_with_result(self):
        """Test stored tool call with result"""
        tool_call = StoredToolCall(
            id="tool-123",
            tool_name="read_file",
            args={"path": "/tmp/test.txt"},
            args_string='{"path": "/tmp/test.txt"}',
            status=ToolCallStatus.COMPLETED,
            result="File contents here",
            start_time=1704067200000,
            end_time=1704067201000,
            parent_message_id="msg-123",
        )
        
        assert tool_call.result == "File contents here"
        assert tool_call.end_time == 1704067201000
        assert tool_call.parent_message_id == "msg-123"

    def test_stored_tool_call_with_error(self):
        """Test stored tool call with error"""
        tool_call = StoredToolCall(
            id="tool-123",
            tool_name="read_file",
            args={"path": "/nonexistent"},
            status=ToolCallStatus.FAILED,
            error="File not found",
        )
        
        assert tool_call.status == ToolCallStatus.FAILED
        assert tool_call.error == "File not found"

    def test_stored_tool_call_to_json(self):
        """Test serializing tool call to JSON"""
        tool_call = StoredToolCall(
            id="tool-123",
            tool_name="read_file",
            args={"path": "/tmp/test.txt"},
            args_string='{"path": "/tmp/test.txt"}',
            status=ToolCallStatus.COMPLETED,
            result="File contents",
            start_time=1704067200000,
            end_time=1704067201000,
        )
        
        json_str = tool_call.to_json()
        data = json.loads(json_str)
        
        assert data["id"] == "tool-123"
        assert data["tool_name"] == "read_file"
        assert data["args"] == {"path": "/tmp/test.txt"}
        assert data["status"] == "completed"
        assert data["result"] == "File contents"

    def test_stored_tool_call_from_json(self):
        """Test deserializing tool call from JSON"""
        json_str = json.dumps({
            "id": "tool-123",
            "tool_name": "read_file",
            "args": {"path": "/tmp/test.txt"},
            "args_string": '{"path": "/tmp/test.txt"}',
            "status": "completed",
            "result": "File contents",
            "error": None,
            "start_time": 1704067200000,
            "end_time": 1704067201000,
            "parent_message_id": "msg-123",
        })
        
        tool_call = StoredToolCall.from_json(json_str)
        
        assert tool_call.id == "tool-123"
        assert tool_call.tool_name == "read_file"
        assert tool_call.args == {"path": "/tmp/test.txt"}
        assert tool_call.status == ToolCallStatus.COMPLETED
        assert tool_call.result == "File contents"
        assert tool_call.parent_message_id == "msg-123"

    def test_stored_tool_call_roundtrip(self):
        """Test roundtrip conversion to/from JSON"""
        original = StoredToolCall(
            id="tool-123",
            tool_name="execute_command",
            args={"command": "ls -la"},
            args_string='{"command": "ls -la"}',
            status=ToolCallStatus.EXECUTING,
            start_time=1704067200000,
            parent_message_id="msg-123",
        )
        
        json_str = original.to_json()
        restored = StoredToolCall.from_json(json_str)
        
        assert restored.id == original.id
        assert restored.tool_name == original.tool_name
        assert restored.args == original.args
        assert restored.args_string == original.args_string
        assert restored.status == original.status
        assert restored.start_time == original.start_time
        assert restored.parent_message_id == original.parent_message_id


class TestSessionListResponse:
    """SessionListResponse model tests"""

    def test_create_session_list_response(self):
        """Test creating session list response"""
        sessions = [
            SessionMeta(
                id="session-1",
                thread_id="thread-1",
                username="testuser",
            ),
            SessionMeta(
                id="session-2",
                thread_id="thread-2",
                username="testuser",
            ),
        ]
        
        response = SessionListResponse(
            total=2,
            page=1,
            page_size=20,
            sessions=sessions,
        )
        
        assert response.total == 2
        assert response.page == 1
        assert response.page_size == 20
        assert len(response.sessions) == 2

    def test_empty_session_list_response(self):
        """Test empty session list response"""
        response = SessionListResponse(
            total=0,
            page=1,
            page_size=20,
            sessions=[],
        )
        
        assert response.total == 0
        assert len(response.sessions) == 0


class TestSessionMessagesResponse:
    """SessionMessagesResponse model tests"""

    def test_create_session_messages_response(self):
        """Test creating session messages response"""
        messages = [
            StoredMessage(id="msg-1", role="user", content="Hello"),
            StoredMessage(id="msg-2", role="assistant", content="Hi there!"),
        ]
        
        tool_calls = [
            StoredToolCall(id="tool-1", tool_name="read_file", args={}),
        ]
        
        response = SessionMessagesResponse(
            session_id="session-123",
            messages=messages,
            tool_calls=tool_calls,
        )
        
        assert response.session_id == "session-123"
        assert len(response.messages) == 2
        assert len(response.tool_calls) == 1

    def test_empty_session_messages_response(self):
        """Test empty session messages response"""
        response = SessionMessagesResponse(
            session_id="session-123",
            messages=[],
            tool_calls=[],
        )
        
        assert response.session_id == "session-123"
        assert len(response.messages) == 0
        assert len(response.tool_calls) == 0

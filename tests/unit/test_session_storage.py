# -*- coding: utf-8 -*-
"""Session Storage Unit Tests with Mock Redis"""

import pytest
import json
import time
from unittest.mock import MagicMock, patch

from src.providers.claude_code_api.services.session_storage import SessionStorage, SESSION_TTL
from src.providers.claude_code_api.models import (
    SessionMeta,
    SessionStatus,
    StoredMessage,
    MessageStatus,
    StoredToolCall,
    ToolCallStatus,
)


class MockRedisClient:
    """Mock Redis client for testing SessionStorage"""
    
    def __init__(self):
        self._data = {}  # key -> value
        self._hashes = {}  # key -> {field: value}
        self._sets = {}  # key -> set
        self._sorted_sets = {}  # key -> {member: score}
        self._lists = {}  # key -> list
        self._prefix = "aona:"
        self._ttls = {}  # key -> ttl
        self.client = self  # For expire() calls
    
    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"
    
    def ping(self) -> bool:
        return True
    
    def get(self, key: str):
        return self._data.get(self._key(key))
    
    def set(self, key: str, value: str, ex=None):
        self._data[self._key(key)] = value
        if ex:
            self._ttls[self._key(key)] = ex
        return True
    
    def delete(self, *keys):
        count = 0
        for k in keys:
            full_key = self._key(k)
            if full_key in self._data:
                del self._data[full_key]
                count += 1
            if full_key in self._hashes:
                del self._hashes[full_key]
                count += 1
            if full_key in self._lists:
                del self._lists[full_key]
                count += 1
        return count
    
    def exists(self, key: str) -> bool:
        return self._key(key) in self._data or self._key(key) in self._hashes
    
    def expire(self, key: str, ttl: int) -> bool:
        """Set TTL on a key"""
        self._ttls[key] = ttl
        return True
    
    # Hash operations
    def hset(self, name: str, mapping: dict):
        full_key = self._key(name)
        if full_key not in self._hashes:
            self._hashes[full_key] = {}
        self._hashes[full_key].update(mapping)
        return len(mapping)
    
    def hget(self, name: str, key: str):
        full_key = self._key(name)
        return self._hashes.get(full_key, {}).get(key)
    
    def hgetall(self, name: str):
        full_key = self._key(name)
        return self._hashes.get(full_key, {})
    
    def hdel(self, name: str, *keys):
        full_key = self._key(name)
        if full_key not in self._hashes:
            return 0
        count = 0
        for k in keys:
            if k in self._hashes[full_key]:
                del self._hashes[full_key][k]
                count += 1
        return count
    
    # Sorted set operations
    def zadd(self, name: str, mapping: dict):
        full_key = self._key(name)
        if full_key not in self._sorted_sets:
            self._sorted_sets[full_key] = {}
        added = 0
        for member, score in mapping.items():
            if member not in self._sorted_sets[full_key]:
                added += 1
            self._sorted_sets[full_key][member] = score
        return added
    
    def zrem(self, name: str, *values):
        full_key = self._key(name)
        if full_key not in self._sorted_sets:
            return 0
        removed = 0
        for v in values:
            if v in self._sorted_sets[full_key]:
                del self._sorted_sets[full_key][v]
                removed += 1
        return removed
    
    def zrange(self, name: str, start: int, end: int, withscores: bool = False):
        full_key = self._key(name)
        items = self._sorted_sets.get(full_key, {})
        sorted_items = sorted(items.items(), key=lambda x: x[1])
        
        length = len(sorted_items)
        if start < 0:
            start = max(0, length + start)
        if end < 0:
            end = length + end
        
        result = sorted_items[start:end + 1]
        if withscores:
            return result
        return [item[0] for item in result]
    
    def zrevrange(self, name: str, start: int, end: int, withscores: bool = False):
        """Get range in reverse order (highest to lowest score)"""
        full_key = name  # Note: already has prefix when called via client
        if full_key not in self._sorted_sets:
            return []
        items = self._sorted_sets.get(full_key, {})
        sorted_items = sorted(items.items(), key=lambda x: x[1], reverse=True)
        
        length = len(sorted_items)
        if end == -1:
            end = length - 1
        
        result = sorted_items[start:end + 1]
        if withscores:
            return result
        return [item[0] for item in result]
    
    def zcard(self, name: str) -> int:
        full_key = self._key(name)
        return len(self._sorted_sets.get(full_key, {}))
    
    # List operations
    def lpush(self, name: str, *values):
        full_key = self._key(name)
        if full_key not in self._lists:
            self._lists[full_key] = []
        for v in reversed(values):
            self._lists[full_key].insert(0, v)
        return len(self._lists[full_key])
    
    def rpush(self, name: str, *values):
        full_key = self._key(name)
        if full_key not in self._lists:
            self._lists[full_key] = []
        self._lists[full_key].extend(values)
        return len(self._lists[full_key])
    
    def lrange(self, name: str, start: int, end: int):
        full_key = self._key(name)
        lst = self._lists.get(full_key, [])
        if end == -1:
            end = len(lst)
        return lst[start:end + 1]
    
    def llen(self, name: str) -> int:
        full_key = self._key(name)
        return len(self._lists.get(full_key, []))
    
    def lset(self, name: str, index: int, value: str):
        """Set value at index in list"""
        if name not in self._lists:
            return False
        if 0 <= index < len(self._lists[name]):
            self._lists[name][index] = value
            return True
        return False


@pytest.fixture
def mock_redis():
    """Create mock Redis client"""
    return MockRedisClient()


@pytest.fixture
def session_storage(mock_redis):
    """Create SessionStorage instance with mock Redis"""
    storage = SessionStorage(redis_client=mock_redis)
    return storage


class TestSessionMetadataOperations:
    """Test session metadata CRUD operations"""

    def test_save_session_meta(self, session_storage, mock_redis):
        """Test saving session metadata"""
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            run_id="run-456",
            title="Test Session",
            username="testuser",
            agent_name="test-agent",
            status=SessionStatus.RUNNING,
        )
        
        result = session_storage.save_session_meta(meta)
        
        assert result is True
        
        # Verify hash was saved
        hash_key = mock_redis._key("session:session-123:meta")
        assert hash_key in mock_redis._hashes
        assert mock_redis._hashes[hash_key]["id"] == "session-123"
        assert mock_redis._hashes[hash_key]["status"] == "running"
        
        # Verify user index was updated
        user_key = mock_redis._key("user:testuser:sessions")
        assert user_key in mock_redis._sorted_sets
        assert "session-123" in mock_redis._sorted_sets[user_key]

    def test_get_session_meta(self, session_storage):
        """Test getting session metadata"""
        # First save a session
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="testuser",
            title="Test Session",
        )
        session_storage.save_session_meta(meta)
        
        # Then retrieve it
        retrieved = session_storage.get_session_meta("session-123")
        
        assert retrieved is not None
        assert retrieved.id == "session-123"
        assert retrieved.thread_id == "thread-123"
        assert retrieved.username == "testuser"
        assert retrieved.title == "Test Session"

    def test_get_session_meta_not_found(self, session_storage):
        """Test getting non-existent session metadata"""
        result = session_storage.get_session_meta("nonexistent")
        assert result is None

    def test_get_user_sessions(self, session_storage):
        """Test getting user's sessions"""
        # Create multiple sessions
        for i in range(5):
            meta = SessionMeta(
                id=f"session-{i}",
                thread_id=f"thread-{i}",
                username="testuser",
                title=f"Session {i}",
                updated_at=1704067200000 + i * 1000,  # Increasing timestamps
            )
            session_storage.save_session_meta(meta)
        
        # Get sessions
        sessions, total = session_storage.get_user_sessions("testuser")
        
        assert total == 5
        assert len(sessions) == 5
        # Should be sorted by updated_at descending
        assert sessions[0].id == "session-4"
        assert sessions[4].id == "session-0"

    def test_get_user_sessions_with_pagination(self, session_storage):
        """Test getting user's sessions with pagination"""
        # Create 10 sessions
        for i in range(10):
            meta = SessionMeta(
                id=f"session-{i}",
                thread_id=f"thread-{i}",
                username="testuser",
                title=f"Session {i}",
                updated_at=1704067200000 + i * 1000,
            )
            session_storage.save_session_meta(meta)
        
        # Get page 1
        sessions, total = session_storage.get_user_sessions(
            "testuser", page=1, page_size=3
        )
        
        assert total == 10
        assert len(sessions) == 3
        
        # Get page 2
        sessions, total = session_storage.get_user_sessions(
            "testuser", page=2, page_size=3
        )
        
        assert total == 10
        assert len(sessions) == 3

    def test_get_user_sessions_with_search(self, session_storage):
        """Test getting user's sessions with search filter"""
        # Create sessions with different titles
        titles = ["Hello World", "Goodbye World", "Test Session", "Another Test"]
        for i, title in enumerate(titles):
            meta = SessionMeta(
                id=f"session-{i}",
                thread_id=f"thread-{i}",
                username="testuser",
                title=title,
            )
            session_storage.save_session_meta(meta)
        
        # Search for "World"
        sessions, total = session_storage.get_user_sessions(
            "testuser", search="World"
        )
        
        assert total == 2
        assert all("World" in s.title for s in sessions)

    def test_get_user_sessions_with_status_filter(self, session_storage):
        """Test getting user's sessions with status filter"""
        # Create sessions with different statuses
        statuses = [
            SessionStatus.IDLE,
            SessionStatus.RUNNING,
            SessionStatus.COMPLETED,
            SessionStatus.RUNNING,
        ]
        for i, status in enumerate(statuses):
            meta = SessionMeta(
                id=f"session-{i}",
                thread_id=f"thread-{i}",
                username="testuser",
                status=status,
            )
            session_storage.save_session_meta(meta)
        
        # Filter by RUNNING status
        sessions, total = session_storage.get_user_sessions(
            "testuser", status_filter=SessionStatus.RUNNING
        )
        
        assert total == 2
        assert all(s.status == SessionStatus.RUNNING for s in sessions)

    def test_get_user_sessions_empty(self, session_storage):
        """Test getting sessions for user with no sessions"""
        sessions, total = session_storage.get_user_sessions("nonexistent")
        
        assert total == 0
        assert len(sessions) == 0

    def test_update_session_status(self, session_storage):
        """Test updating session status"""
        # Create session
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="testuser",
            status=SessionStatus.IDLE,
        )
        session_storage.save_session_meta(meta)
        
        # Update status
        result = session_storage.update_session_status(
            "session-123", SessionStatus.RUNNING
        )
        
        assert result is True
        
        # Verify status was updated
        updated = session_storage.get_session_meta("session-123")
        assert updated.status == SessionStatus.RUNNING

    def test_delete_session(self, session_storage, mock_redis):
        """Test deleting session"""
        # Create session with messages and tool calls
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="testuser",
        )
        session_storage.save_session_meta(meta)
        
        msg = StoredMessage(id="msg-1", role="user", content="Hello")
        session_storage.add_session_message("session-123", msg)
        
        tool = StoredToolCall(id="tool-1", tool_name="test", args={})
        session_storage.save_tool_call("session-123", tool)
        
        # Delete session
        result = session_storage.delete_session("session-123", "testuser")
        
        assert result is True
        
        # Verify session is deleted
        assert session_storage.get_session_meta("session-123") is None
        
        # Verify messages are deleted
        assert session_storage.get_session_messages("session-123") == []
        
        # Verify removed from user index
        user_key = mock_redis._key("user:testuser:sessions")
        assert "session-123" not in mock_redis._sorted_sets.get(user_key, {})


class TestMessageOperations:
    """Test message CRUD operations"""

    def test_add_session_message(self, session_storage):
        """Test adding message to session"""
        # Create session first
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="testuser",
        )
        session_storage.save_session_meta(meta)
        
        # Add message
        msg = StoredMessage(
            id="msg-1",
            role="user",
            content="Hello, world!",
        )
        result = session_storage.add_session_message("session-123", msg)
        
        assert result is True
        
        # Verify message was added
        messages = session_storage.get_session_messages("session-123")
        assert len(messages) == 1
        assert messages[0].id == "msg-1"
        assert messages[0].content == "Hello, world!"

    def test_add_multiple_messages(self, session_storage):
        """Test adding multiple messages to session"""
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="testuser",
        )
        session_storage.save_session_meta(meta)
        
        # Add multiple messages
        for i in range(3):
            msg = StoredMessage(
                id=f"msg-{i}",
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}",
            )
            session_storage.add_session_message("session-123", msg)
        
        messages = session_storage.get_session_messages("session-123")
        assert len(messages) == 3
        
        # Verify order is preserved
        assert messages[0].id == "msg-0"
        assert messages[1].id == "msg-1"
        assert messages[2].id == "msg-2"

    def test_get_session_messages_empty(self, session_storage):
        """Test getting messages from session with no messages"""
        messages = session_storage.get_session_messages("nonexistent")
        assert messages == []

    def test_update_message(self, session_storage, mock_redis):
        """Test updating an existing message"""
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="testuser",
        )
        session_storage.save_session_meta(meta)
        
        # Add initial message
        msg = StoredMessage(
            id="msg-1",
            role="assistant",
            content="Initial content",
            status=MessageStatus.STREAMING,
        )
        session_storage.add_session_message("session-123", msg)
        
        # Update message
        updated_msg = StoredMessage(
            id="msg-1",
            role="assistant",
            content="Updated content",
            status=MessageStatus.COMPLETE,
        )
        result = session_storage.update_message("session-123", updated_msg)
        
        assert result is True
        
        # Verify message was updated
        messages = session_storage.get_session_messages("session-123")
        assert len(messages) == 1
        assert messages[0].content == "Updated content"
        assert messages[0].status == MessageStatus.COMPLETE

    def test_update_message_not_found(self, session_storage):
        """Test updating non-existent message"""
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="testuser",
        )
        session_storage.save_session_meta(meta)
        
        msg = StoredMessage(
            id="nonexistent",
            role="assistant",
            content="Content",
        )
        result = session_storage.update_message("session-123", msg)
        
        assert result is False

    def test_get_message_by_id(self, session_storage):
        """Test getting specific message by ID"""
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="testuser",
        )
        session_storage.save_session_meta(meta)
        
        # Add multiple messages
        for i in range(3):
            msg = StoredMessage(id=f"msg-{i}", role="user", content=f"Message {i}")
            session_storage.add_session_message("session-123", msg)
        
        # Get specific message
        msg = session_storage.get_message_by_id("session-123", "msg-1")
        
        assert msg is not None
        assert msg.id == "msg-1"
        assert msg.content == "Message 1"

    def test_get_message_by_id_not_found(self, session_storage):
        """Test getting non-existent message by ID"""
        msg = session_storage.get_message_by_id("session-123", "nonexistent")
        assert msg is None


class TestToolCallOperations:
    """Test tool call CRUD operations"""

    def test_save_tool_call(self, session_storage):
        """Test saving tool call"""
        tool_call = StoredToolCall(
            id="tool-123",
            tool_name="read_file",
            args={"path": "/tmp/test.txt"},
            status=ToolCallStatus.EXECUTING,
        )
        
        result = session_storage.save_tool_call("session-123", tool_call)
        
        assert result is True
        
        # Verify tool call was saved
        retrieved = session_storage.get_tool_call("session-123", "tool-123")
        assert retrieved is not None
        assert retrieved.id == "tool-123"
        assert retrieved.tool_name == "read_file"

    def test_get_tool_call(self, session_storage):
        """Test getting tool call by ID"""
        tool_call = StoredToolCall(
            id="tool-123",
            tool_name="read_file",
            args={"path": "/tmp/test.txt"},
        )
        session_storage.save_tool_call("session-123", tool_call)
        
        retrieved = session_storage.get_tool_call("session-123", "tool-123")
        
        assert retrieved is not None
        assert retrieved.id == "tool-123"
        assert retrieved.tool_name == "read_file"
        assert retrieved.args == {"path": "/tmp/test.txt"}

    def test_get_tool_call_not_found(self, session_storage):
        """Test getting non-existent tool call"""
        result = session_storage.get_tool_call("session-123", "nonexistent")
        assert result is None

    def test_get_session_tool_calls(self, session_storage):
        """Test getting all tool calls for session"""
        # Save multiple tool calls
        for i in range(3):
            tool_call = StoredToolCall(
                id=f"tool-{i}",
                tool_name=f"tool_{i}",
                args={},
                start_time=1704067200000 + i * 1000,
            )
            session_storage.save_tool_call("session-123", tool_call)
        
        tool_calls = session_storage.get_session_tool_calls("session-123")
        
        assert len(tool_calls) == 3
        # Should be sorted by start_time
        assert tool_calls[0].id == "tool-0"
        assert tool_calls[1].id == "tool-1"
        assert tool_calls[2].id == "tool-2"

    def test_get_session_tool_calls_empty(self, session_storage):
        """Test getting tool calls from session with no tool calls"""
        tool_calls = session_storage.get_session_tool_calls("nonexistent")
        assert tool_calls == []

    def test_update_tool_call(self, session_storage):
        """Test updating tool call"""
        # Save initial tool call
        tool_call = StoredToolCall(
            id="tool-123",
            tool_name="read_file",
            args={"path": "/tmp/test.txt"},
            status=ToolCallStatus.EXECUTING,
        )
        session_storage.save_tool_call("session-123", tool_call)
        
        # Update tool call
        tool_call.status = ToolCallStatus.COMPLETED
        tool_call.result = "File contents"
        tool_call.end_time = int(time.time() * 1000)
        
        result = session_storage.update_tool_call("session-123", tool_call)
        
        assert result is True
        
        # Verify update
        retrieved = session_storage.get_tool_call("session-123", "tool-123")
        assert retrieved.status == ToolCallStatus.COMPLETED
        assert retrieved.result == "File contents"


class TestStreamingContentOperations:
    """Test streaming content temporary storage"""

    def test_save_streaming_content(self, session_storage):
        """Test saving streaming content"""
        result = session_storage.save_streaming_content(
            "session-123", "msg-1", "Partial content..."
        )
        
        assert result is True
        
        # Verify content was saved
        content = session_storage.get_streaming_content("session-123", "msg-1")
        assert content == "Partial content..."

    def test_get_streaming_content(self, session_storage):
        """Test getting streaming content"""
        session_storage.save_streaming_content(
            "session-123", "msg-1", "Streaming..."
        )
        
        content = session_storage.get_streaming_content("session-123", "msg-1")
        
        assert content == "Streaming..."

    def test_get_streaming_content_not_found(self, session_storage):
        """Test getting non-existent streaming content"""
        content = session_storage.get_streaming_content("session-123", "nonexistent")
        assert content is None

    def test_delete_streaming_content(self, session_storage):
        """Test deleting streaming content"""
        session_storage.save_streaming_content(
            "session-123", "msg-1", "Content"
        )
        
        result = session_storage.delete_streaming_content("session-123", "msg-1")
        
        assert result is True
        
        # Verify content was deleted
        content = session_storage.get_streaming_content("session-123", "msg-1")
        assert content is None


class TestSessionStorageEdgeCases:
    """Test edge cases and error handling"""

    def test_session_meta_with_unicode(self, session_storage):
        """Test session metadata with unicode characters"""
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="用户名",
            title="你好，世界！🌍",
        )
        session_storage.save_session_meta(meta)
        
        retrieved = session_storage.get_session_meta("session-123")
        
        assert retrieved.username == "用户名"
        assert retrieved.title == "你好，世界！🌍"

    def test_message_with_large_content(self, session_storage):
        """Test message with large content"""
        meta = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="testuser",
        )
        session_storage.save_session_meta(meta)
        
        # Create message with large content
        large_content = "x" * 100000  # 100KB
        msg = StoredMessage(
            id="msg-1",
            role="assistant",
            content=large_content,
        )
        session_storage.add_session_message("session-123", msg)
        
        messages = session_storage.get_session_messages("session-123")
        assert len(messages) == 1
        assert len(messages[0].content) == 100000

    def test_tool_call_with_complex_args(self, session_storage):
        """Test tool call with complex nested arguments"""
        complex_args = {
            "nested": {
                "array": [1, 2, 3],
                "object": {"key": "value"},
            },
            "unicode": "你好",
            "special": "line1\nline2\ttab",
        }
        
        tool_call = StoredToolCall(
            id="tool-123",
            tool_name="complex_tool",
            args=complex_args,
            args_string=json.dumps(complex_args, ensure_ascii=False),
        )
        session_storage.save_tool_call("session-123", tool_call)
        
        retrieved = session_storage.get_tool_call("session-123", "tool-123")
        
        assert retrieved.args == complex_args
        assert retrieved.args["nested"]["array"] == [1, 2, 3]
        assert retrieved.args["unicode"] == "你好"

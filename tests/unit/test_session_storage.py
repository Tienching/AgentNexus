# -*- coding: utf-8 -*-
"""Session Storage Unit Tests with Mock Redis"""

import pytest
import json
import time
from unittest.mock import MagicMock, patch

from src.server.services.session_storage import SessionStorage, SESSION_TTL
from src.server.models import (
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
            exec_user="test-agent",
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

    def test_save_session_meta_rejects_empty_id(self, session_storage, mock_redis):
        """Empty session_id should be rejected to avoid undeletable sessions"""
        meta = SessionMeta(
            id="",
            thread_id="",
            username="testuser",
            title="New Session",
        )

        result = session_storage.save_session_meta(meta)

        assert result is False
        assert mock_redis._key("session::meta") not in mock_redis._hashes

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

    def test_get_session_meta_merges_cli_session_id_from_execution_binding(self, session_storage):
        """Reading a bound history/runtime session should not fail when binding carries cli_session_id."""
        meta = SessionMeta(
            id="session-bound",
            thread_id="thread-bound",
            username="testuser",
            title="Bound Session",
            source="history",
        )
        assert session_storage.save_session_meta(meta) is True
        assert session_storage.bind_execution_context(
            "session-bound",
            cli_session_id="cli-hist-001",
            provider="codebuddy",
            alias="codebuddy",
            work_dir="/tmp/demo",
            source_type="history",
            source_session_id="hist-001",
            session_kind="chat",
        ) is True

        retrieved = session_storage.get_session_meta("session-bound")

        assert retrieved is not None
        assert retrieved.cli_session_id == "cli-hist-001"
        assert retrieved.claude_session_id == "cli-hist-001"
        assert retrieved.execution_binding is not None
        assert retrieved.execution_binding.cli_session_id == "cli-hist-001"

    def test_save_session_meta_preserves_existing_execution_binding_context(self, session_storage):
        meta = SessionMeta(
            id="session-preserve-binding",
            thread_id="thread-preserve-binding",
            username="testuser",
            title="Bound Session",
        )
        assert session_storage.bind_execution_context(
            "session-preserve-binding",
            cli_session_id="cli-001",
            provider="codebuddy",
            alias="codebuddy",
            exec_user="ubuntu",
            work_dir="/tmp/demo",
            source_type="chat",
            session_kind="chat",
        ) is True

        assert session_storage.save_session_meta(meta) is True

        binding = session_storage.get_execution_binding("session-preserve-binding")
        assert binding is not None
        assert binding.cli_session_id == "cli-001"
        assert binding.provider == "codebuddy"
        assert binding.alias == "codebuddy"
        assert binding.exec_user == "ubuntu"
        assert binding.work_dir == "/tmp/demo"
        assert binding.source_type == "chat"
        assert binding.session_kind == "chat"

    def test_clear_helpers_clear_execution_binding_fallback_fields(self, session_storage):
        meta = SessionMeta(
            id="session-clear-binding",
            thread_id="thread-clear-binding",
            username="testuser",
            title="Clear Binding Session",
        )
        assert session_storage.save_session_meta(meta) is True
        assert session_storage.set_inherited_session("session-clear-binding", "history:codebuddy:hist-001") is True
        assert session_storage.set_exec_dir_override("session-clear-binding", "/tmp/work") is True
        assert session_storage.set_workspace_provider("session-clear-binding", "codebuddy") is True
        assert session_storage.set_workspace_alias("session-clear-binding", "cb") is True
        assert session_storage.set_cli_session_id("session-clear-binding", "cli-001") is True
        assert session_storage.set_task_id("session-clear-binding", "task-001") is True

        assert session_storage.clear_inherited_session("session-clear-binding") is True
        assert session_storage.clear_exec_dir_override("session-clear-binding") is True
        assert session_storage.clear_workspace_provider("session-clear-binding") is True
        assert session_storage.clear_workspace_alias("session-clear-binding") is True
        assert session_storage.clear_cli_session_id("session-clear-binding") is True
        assert session_storage.clear_task_id("session-clear-binding") is True

        binding = session_storage.get_execution_binding("session-clear-binding")
        assert binding is not None
        assert binding.source_session_id is None
        assert binding.source_type is None
        assert binding.work_dir is None
        assert binding.provider is None
        assert binding.alias is None
        assert binding.cli_session_id is None
        assert binding.task_id is None
        assert session_storage.get_inherited_session("session-clear-binding") is None
        assert session_storage.get_exec_dir_override("session-clear-binding") is None
        assert session_storage.get_workspace_provider("session-clear-binding") is None
        assert session_storage.get_workspace_alias("session-clear-binding") is None
        assert session_storage.get_cli_session_id("session-clear-binding") is None
        assert session_storage.get_task_id("session-clear-binding") is None

    def test_get_session_meta_not_found(self, session_storage):
        """Test getting non-existent session metadata"""
        result = session_storage.get_session_meta("nonexistent")
        assert result is None

    def test_get_session_meta_self_heals_missing_id_fields(self, session_storage, mock_redis):
        """Partial meta hash should be auto-healed with id/thread_id from key."""
        mock_redis.hset("session:sess1:meta", {
            "title": "New Session",
            "username": "",
            "status": "error",
            "created_at": "0",
            "updated_at": "1704067200000",
            "message_count": "0",
        })

        meta = session_storage.get_session_meta("sess1")

        assert meta is not None
        assert meta.id == "sess1"
        assert meta.thread_id == "sess1"

        saved = mock_redis.hgetall("session:sess1:meta")
        assert saved.get("id") == "sess1"
        assert saved.get("thread_id") == "sess1"

    def test_save_session_meta_moves_user_index_when_username_changes(self, session_storage, mock_redis):
        first = SessionMeta(
            id="session-move",
            thread_id="thread-move",
            username="ubuntu",
            exec_user="ubuntu",
            title="Move Session",
            updated_at=1704067200000,
        )
        second = SessionMeta(
            id="session-move",
            thread_id="thread-move",
            username="tswitch",
            exec_user="tswitch",
            title="Move Session",
            updated_at=1704067205000,
        )

        session_storage.save_session_meta(first)
        session_storage.save_session_meta(second)

        old_user_key = mock_redis._key("user:ubuntu:sessions")
        new_user_key = mock_redis._key("user:tswitch:sessions")
        assert "session-move" not in mock_redis._sorted_sets.get(old_user_key, {})
        assert "session-move" in mock_redis._sorted_sets.get(new_user_key, {})

    def test_set_session_exec_user_updates_meta_and_switch_flag(self, session_storage):
        meta = SessionMeta(
            id="session-exec",
            thread_id="thread-exec",
            username="ubuntu",
            exec_user="ubuntu",
            title="Exec Session",
            exec_dir="/home/ubuntu/.nexus/sessions/session-exec",
        )
        session_storage.save_session_meta(meta)

        ok = session_storage.set_session_exec_user(
            "session-exec",
            "tswitch",
            user_home_base="/home",
        )

        assert ok is True
        updated = session_storage.get_session_meta("session-exec")
        assert updated is not None
        assert updated.username == "tswitch"
        assert updated.exec_user == "tswitch"
        assert updated.exec_dir == "/home/tswitch/.nexus/sessions/session-exec"
        assert session_storage.get_session_exec_user("session-exec") == "tswitch"

        assert session_storage.set_exec_user_switched("session-exec") is True
        assert session_storage.consume_exec_user_switched("session-exec") is True
        assert session_storage.consume_exec_user_switched("session-exec") is False

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

    def test_get_all_sessions_self_heals_empty_session_id(self, session_storage, mock_redis):
        """Invalid empty session_id should be auto-cleaned and excluded from list."""
        good_meta = SessionMeta(
            id="session-valid",
            thread_id="thread-valid",
            username="testuser",
            title="Valid",
            updated_at=1704067201000,
        )
        session_storage.save_session_meta(good_meta)

        # Inject a malformed empty-id record and index entry
        global_key = mock_redis._key("sessions:all")
        mock_redis._sorted_sets[global_key][""] = 1704067202000
        mock_redis.hset("session::meta", {
            "id": "",
            "thread_id": "",
            "username": "",
            "title": "New Session",
            "status": "error",
            "created_at": "0",
            "updated_at": "1704067202000",
            "message_count": "0",
            "run_id": "",
            "exec_user": "",
            "provider": "",
            "alias": "",
            "exec_dir": "",
        })

        sessions, total = session_storage.get_all_sessions()

        assert total == 1
        assert len(sessions) == 1
        assert sessions[0].id == "session-valid"
        assert "" not in mock_redis._sorted_sets.get(global_key, {})
        assert mock_redis._key("session::meta") not in mock_redis._hashes

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

# -*- coding: utf-8 -*-
"""Stream Archiver Unit Tests"""

import pytest
import time

from src.server.services.stream_archiver import StreamArchiver, create_archiver
from src.server.models import (
    SessionMeta,
    SessionStatus,
    StoredMessage,
    MessageStatus,
    StoredToolCall,
    ToolCallStatus,
)


class MockSessionStorage:
    """Mock SessionStorage for testing StreamArchiver"""
    
    def __init__(self):
        self.sessions = {}  # session_id -> SessionMeta
        self.messages = {}  # session_id -> [StoredMessage]
        self.tool_calls = {}  # session_id -> {tool_id: StoredToolCall}
        self.streaming_content = {}  # (session_id, msg_id) -> content
        
        # Track method calls
        self.call_log = []
    
    def save_session_meta(self, meta: SessionMeta) -> bool:
        self.call_log.append(("save_session_meta", meta.id))
        self.sessions[meta.id] = meta
        return True
    
    def get_session_meta(self, session_id: str):
        self.call_log.append(("get_session_meta", session_id))
        return self.sessions.get(session_id)
    
    def update_session_status(self, session_id: str, status: SessionStatus, update_timestamp: bool = True) -> bool:
        self.call_log.append(("update_session_status", session_id, status))
        if session_id in self.sessions:
            self.sessions[session_id].status = status
            if update_timestamp:
                self.sessions[session_id].updated_at = int(time.time() * 1000)
            return True
        return False
    
    def add_session_message(self, session_id: str, message: StoredMessage) -> bool:
        self.call_log.append(("add_session_message", session_id, message.id))
        if session_id not in self.messages:
            self.messages[session_id] = []
        self.messages[session_id].append(message)
        return True
    
    def update_message(self, session_id: str, message: StoredMessage) -> bool:
        self.call_log.append(("update_message", session_id, message.id))
        if session_id in self.messages:
            for i, msg in enumerate(self.messages[session_id]):
                if msg.id == message.id:
                    self.messages[session_id][i] = message
                    return True
        return False
    
    def get_session_messages(self, session_id: str):
        return self.messages.get(session_id, [])

    def get_message_by_id(self, session_id: str, message_id: str):
        for message in self.messages.get(session_id, []):
            if message.id == message_id:
                return message
        return None

    def append_agui_event(self, session_id: str, event_data: dict) -> bool:
        self.call_log.append(("append_agui_event", session_id, event_data.get("type")))
        return True
    
    def save_tool_call(self, session_id: str, tool_call: StoredToolCall) -> bool:
        self.call_log.append(("save_tool_call", session_id, tool_call.id))
        if session_id not in self.tool_calls:
            self.tool_calls[session_id] = {}
        self.tool_calls[session_id][tool_call.id] = tool_call
        return True
    
    def get_tool_call(self, session_id: str, tool_call_id: str):
        self.call_log.append(("get_tool_call", session_id, tool_call_id))
        return self.tool_calls.get(session_id, {}).get(tool_call_id)
    
    def update_tool_call(self, session_id: str, tool_call: StoredToolCall) -> bool:
        return self.save_tool_call(session_id, tool_call)
    
    def save_streaming_content(self, session_id: str, message_id: str, content: str) -> bool:
        self.call_log.append(("save_streaming_content", session_id, message_id))
        self.streaming_content[(session_id, message_id)] = content
        return True
    
    def get_streaming_content(self, session_id: str, message_id: str):
        return self.streaming_content.get((session_id, message_id))
    
    def delete_streaming_content(self, session_id: str, message_id: str) -> bool:
        self.call_log.append(("delete_streaming_content", session_id, message_id))
        key = (session_id, message_id)
        if key in self.streaming_content:
            del self.streaming_content[key]
        return True


@pytest.fixture
def mock_storage():
    """Create mock storage"""
    return MockSessionStorage()


@pytest.fixture
def archiver(mock_storage):
    """Create StreamArchiver with mock storage"""
    return StreamArchiver(
        session_id="session-123",
        thread_id="thread-123",
        run_id="run-456",
        username="testuser",
        exec_user="test-agent",
        storage=mock_storage,
    )


class TestStreamArchiverInit:
    """Test StreamArchiver initialization"""

    def test_create_archiver(self):
        """Test creating archiver with factory function"""
        archiver = create_archiver(
            thread_id="thread-123",
            run_id="run-456",
            username="testuser",
            exec_user="test-agent",
        )
        
        assert archiver.session_id == "thread-123"  # Uses thread_id as session_id
        assert archiver.thread_id == "thread-123"
        assert archiver.run_id == "run-456"
        assert archiver.username == "testuser"
        assert archiver.exec_user == "test-agent"

    def test_create_archiver_minimal(self):
        """Test creating archiver with minimal parameters"""
        archiver = create_archiver(
            thread_id="thread-123",
            run_id=None,
            username="testuser",
        )
        
        assert archiver.session_id == "thread-123"
        assert archiver.run_id is None
        assert archiver.exec_user is None

    def test_archiver_initial_state(self, archiver):
        """Test archiver initial state"""
        assert archiver._current_message_id is None
        assert archiver._current_message_content == ""
        assert archiver._current_tool_call_id is None
        assert archiver._current_tool_args == ""
        assert archiver._pending_tool_calls == []
        assert archiver._first_user_message is None
        assert archiver._initialized is False


class TestOnRunStarted:
    """Test on_run_started method"""

    @pytest.mark.asyncio
    async def test_on_run_started_new_session(self, archiver, mock_storage):
        """Test starting a new session"""
        initial_messages = [
            {"id": "msg-1", "role": "user", "content": "Hello, how are you?"},
        ]
        
        await archiver.on_run_started(initial_messages)
        
        assert archiver._initialized is True
        
        # Verify session was created
        session = mock_storage.get_session_meta("session-123")
        assert session is not None
        assert session.status == SessionStatus.RUNNING
        assert session.title == "Hello, how are you?"
        assert session.username == "testuser"
        assert session.exec_user == "test-agent"
        
        # Verify initial message was stored
        messages = mock_storage.get_session_messages("session-123")
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content == "Hello, how are you?"

    @pytest.mark.asyncio
    async def test_on_run_started_long_title(self, archiver, mock_storage):
        """Test that long titles are truncated"""
        long_content = "A" * 100  # 100 characters
        initial_messages = [
            {"id": "msg-1", "role": "user", "content": long_content},
        ]
        
        await archiver.on_run_started(initial_messages)
        
        session = mock_storage.get_session_meta("session-123")
        assert len(session.title) == 53  # 50 chars + "..."

    @pytest.mark.asyncio
    async def test_on_run_started_existing_session(self, archiver, mock_storage):
        """Test starting with existing session"""
        # Create existing session
        existing = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="testuser",
            status=SessionStatus.COMPLETED,
        )
        mock_storage.save_session_meta(existing)
        
        await archiver.on_run_started()
        
        # Verify status was updated to RUNNING
        session = mock_storage.get_session_meta("session-123")
        assert session.status == SessionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_on_run_started_existing_session_updates_exec_user(self, archiver, mock_storage):
        existing = SessionMeta(
            id="session-123",
            thread_id="thread-123",
            username="ubuntu",
            exec_user="ubuntu",
            provider="claude",
            alias="claude",
            status=SessionStatus.COMPLETED,
        )
        mock_storage.save_session_meta(existing)

        archiver.username = "tswitch"
        archiver.exec_user = "tswitch"
        archiver.provider = "codex"
        archiver.alias = "codex"

        await archiver.on_run_started()

        session = mock_storage.get_session_meta("session-123")
        assert session is not None
        assert session.username == "tswitch"
        assert session.exec_user == "tswitch"
        assert session.provider == "codex"
        assert session.alias == "codex"

    @pytest.mark.asyncio
    async def test_on_run_started_no_messages(self, archiver, mock_storage):
        """Test starting without initial messages"""
        await archiver.on_run_started()
        
        session = mock_storage.get_session_meta("session-123")
        assert session is not None
        assert session.title == "New Session"

    @pytest.mark.asyncio
    async def test_on_run_started_multiple_messages(self, archiver, mock_storage):
        """Test starting with multiple initial messages"""
        initial_messages = [
            {"id": "msg-1", "role": "system", "content": "You are an assistant"},
            {"id": "msg-2", "role": "user", "content": "Hello!"},
            {"id": "msg-3", "role": "assistant", "content": "Hi there!"},
        ]
        
        await archiver.on_run_started(initial_messages)
        
        # Title should come from first user message
        session = mock_storage.get_session_meta("session-123")
        assert session.title == "Hello!"
        
        # All messages should be stored
        messages = mock_storage.get_session_messages("session-123")
        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_on_run_started_stores_multimodal_user_content_as_text(self, archiver, mock_storage):
        """AG-UI 多模态用户消息归档时应落成字符串，不能把 content list 传给 StoredMessage。"""
        initial_messages = [
            {
                "id": "msg-image",
                "role": "user",
                "content": [
                    {"type": "text", "text": "介绍一下这张图片"},
                    {
                        "type": "binary",
                        "mimeType": "image/png",
                        "url": "https://example.com/case.png",
                    },
                ],
            }
        ]

        await archiver.on_run_started(initial_messages)

        session = mock_storage.get_session_meta("session-123")
        messages = mock_storage.get_session_messages("session-123")
        assert session.title == "介绍一下这张图片\n{image: https://example.com/case.png}"
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content == "介绍一下这张图片\n{image: https://example.com/case.png}"


class TestOnRunFinished:
    """Test on_run_finished method"""

    @pytest.mark.asyncio
    async def test_on_run_finished(self, archiver, mock_storage):
        """Test finishing a run"""
        # Start run first
        await archiver.on_run_started([{"id": "msg-1", "role": "user", "content": "Hi"}])
        
        await archiver.on_run_finished()
        
        session = mock_storage.get_session_meta("session-123")
        assert session.status == SessionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_on_run_finished_with_pending_message(self, archiver, mock_storage):
        """Test finishing with pending message content"""
        await archiver.on_run_started()
        
        # Simulate text event
        archiver._current_message_id = "msg-assistant"
        archiver._current_message_content = "Hello, I'm the assistant!"
        
        # Add initial message to storage
        msg = StoredMessage(
            id="msg-assistant",
            role="assistant",
            content="",
            status=MessageStatus.STREAMING,
        )
        mock_storage.add_session_message("session-123", msg)
        
        await archiver.on_run_finished()
        
        # Verify message was finalized
        messages = mock_storage.get_session_messages("session-123")
        assert len(messages) == 1
        assert messages[0].content == "Hello, I'm the assistant!"
        assert messages[0].status == MessageStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_on_run_finished_does_not_overwrite_prior_run_error(self, archiver, mock_storage):
        await archiver.on_run_started([{"id": "msg-1", "role": "user", "content": "Hi"}])
        await archiver.archive_event({"type": "RUN_ERROR", "message": "处理超时，请重试"})

        await archiver.on_run_finished()

        session = mock_storage.get_session_meta("session-123")
        assert session.status == SessionStatus.ERROR
        assert ("append_agui_event", "session-123", "RUN_FINISHED") not in mock_storage.call_log


class TestOnRunError:
    """Test on_run_error method"""

    @pytest.mark.asyncio
    async def test_on_run_error(self, archiver, mock_storage):
        """Test handling run error"""
        await archiver.on_run_started()
        
        await archiver.on_run_error("Something went wrong")
        
        session = mock_storage.get_session_meta("session-123")
        assert session.status == SessionStatus.ERROR

    @pytest.mark.asyncio
    async def test_on_run_error_with_pending_message(self, archiver, mock_storage):
        """Test error with pending message"""
        await archiver.on_run_started()
        
        # Simulate pending message
        archiver._current_message_id = "msg-assistant"
        archiver._current_message_content = "Partial response..."
        
        # Add initial message
        msg = StoredMessage(
            id="msg-assistant",
            role="assistant",
            content="",
            status=MessageStatus.STREAMING,
        )
        mock_storage.add_session_message("session-123", msg)
        
        await archiver.on_run_error("Connection lost")
        
        # Verify message has error status
        messages = mock_storage.get_session_messages("session-123")
        assert messages[0].status == MessageStatus.ERROR


class TestArchiveEvent:
    """Test archive_event method"""

    @pytest.mark.asyncio
    async def test_archive_text_event(self, archiver, mock_storage):
        """Test archiving text event"""
        await archiver.on_run_started()
        
        event = {"type": "text", "content": "Hello, "}
        await archiver.archive_event(event)
        
        assert archiver._current_message_id is not None
        assert archiver._current_message_content == "Hello, "
        
        # Verify streaming content was saved
        content = mock_storage.get_streaming_content(
            "session-123", archiver._current_message_id
        )
        assert content == "Hello, "

    @pytest.mark.asyncio
    async def test_archive_multiple_text_events(self, archiver, mock_storage):
        """Test archiving multiple text events"""
        await archiver.on_run_started()
        
        events = [
            {"type": "text", "content": "Hello, "},
            {"type": "text", "content": "how are "},
            {"type": "text", "content": "you?"},
        ]
        
        for event in events:
            await archiver.archive_event(event)
        
        assert archiver._current_message_content == "Hello, how are you?"

    @pytest.mark.asyncio
    async def test_archive_tool_use_event(self, archiver, mock_storage):
        """Test archiving tool use event"""
        await archiver.on_run_started()
        
        event = {
            "type": "tool_use",
            "id": "tool-123",
            "name": "read_file",
            "input": {"path": "/tmp/test.txt"},
        }
        await archiver.archive_event(event)
        
        # Verify tool call was saved
        tool_call = mock_storage.get_tool_call("session-123", "tool-123")
        assert tool_call is not None
        assert tool_call.tool_name == "read_file"
        assert tool_call.args == {"path": "/tmp/test.txt"}
        assert tool_call.status == ToolCallStatus.EXECUTING
        
        # Verify tracking
        assert "tool-123" in archiver._pending_tool_calls
        assert archiver._current_tool_call_id == "tool-123"

    @pytest.mark.asyncio
    async def test_agui_tool_call_after_text_end_attaches_to_last_assistant_message(self, archiver, mock_storage):
        await archiver.on_run_started()
        await archiver.archive_event({"type": "TEXT_MESSAGE_START", "messageId": "assistant-1"})
        await archiver.archive_event({"type": "TEXT_MESSAGE_CONTENT", "messageId": "assistant-1", "delta": "Working..."})
        await archiver.archive_event({"type": "TEXT_MESSAGE_END", "messageId": "assistant-1"})

        await archiver.archive_event({
            "type": "TOOL_CALL_START",
            "toolCallId": "tool-late",
            "toolCallName": "Glob: *",
        })

        message = mock_storage.get_message_by_id("session-123", "assistant-1")
        assert message is not None
        assert "tool-late" in (message.tool_call_ids or [])
        assert any(
            segment.type == "tool_call" and segment.tool_call_id == "tool-late"
            for segment in (message.content_segments or [])
        )
        tool_call = mock_storage.get_tool_call("session-123", "tool-late")
        assert tool_call.parent_message_id == "assistant-1"

    @pytest.mark.asyncio
    async def test_archive_tool_result_event(self, archiver, mock_storage):
        """Test archiving tool result event"""
        await archiver.on_run_started()
        
        # First, archive tool use
        tool_use_event = {
            "type": "tool_use",
            "id": "tool-123",
            "name": "read_file",
            "input": {"path": "/tmp/test.txt"},
        }
        await archiver.archive_event(tool_use_event)
        
        # Then, archive tool result
        result_event = {
            "type": "tool_result",
            "tool_use_id": "tool-123",
            "content": "File contents here",
        }
        await archiver.archive_event(result_event)
        
        # Verify tool call was updated
        tool_call = mock_storage.get_tool_call("session-123", "tool-123")
        assert tool_call.status == ToolCallStatus.COMPLETED
        assert tool_call.result == "File contents here"
        assert tool_call.end_time is not None

    @pytest.mark.asyncio
    async def test_archive_tool_result_error(self, archiver, mock_storage):
        """Test archiving tool result with error"""
        await archiver.on_run_started()
        
        # Archive tool use
        await archiver.archive_event({
            "type": "tool_use",
            "id": "tool-123",
            "name": "read_file",
            "input": {"path": "/nonexistent"},
        })
        
        # Archive error result
        await archiver.archive_event({
            "type": "tool_result",
            "tool_use_id": "tool-123",
            "content": "File not found",
            "is_error": True,
        })
        
        tool_call = mock_storage.get_tool_call("session-123", "tool-123")
        assert tool_call.status == ToolCallStatus.FAILED
        assert tool_call.error == "File not found"

    @pytest.mark.asyncio
    async def test_archive_result_event(self, archiver, mock_storage):
        """Test archiving result event finalizes message"""
        await archiver.on_run_started()
        
        # Add some text
        await archiver.archive_event({"type": "text", "content": "Response content"})
        
        # Add message to storage
        msg = StoredMessage(
            id=archiver._current_message_id,
            role="assistant",
            content="",
            status=MessageStatus.STREAMING,
        )
        mock_storage.add_session_message("session-123", msg)
        
        # Archive result event
        await archiver.archive_event({"type": "result"})
        
        # Verify message was finalized
        assert archiver._current_message_id is None
        assert archiver._current_message_content == ""

    @pytest.mark.asyncio
    async def test_archive_system_event(self, archiver, mock_storage):
        """Test archiving system event (should be logged but not stored)"""
        await archiver.on_run_started()
        
        event = {"type": "system", "subtype": "init"}
        await archiver.archive_event(event)
        
        # System events don't create messages
        messages = mock_storage.get_session_messages("session-123")
        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_archive_unknown_event(self, archiver, mock_storage):
        """Test archiving unknown event type"""
        await archiver.on_run_started()
        
        event = {"type": "unknown_type", "data": "something"}
        await archiver.archive_event(event)
        
        # Should not raise error, just be ignored
        messages = mock_storage.get_session_messages("session-123")
        assert len(messages) == 0


class TestAguiSegmentCoalescing:
    """Test AG-UI text segment coalescing and ordering"""

    @pytest.mark.asyncio
    async def test_agui_text_deltas_are_coalesced_into_one_segment(self, archiver, mock_storage):
        await archiver.on_run_started()

        await archiver.archive_event({"type": "TEXT_MESSAGE_START", "messageId": "msg-123"})
        await archiver.archive_event({"type": "TEXT_MESSAGE_CONTENT", "messageId": "msg-123", "delta": "你"})
        await archiver.archive_event({"type": "TEXT_MESSAGE_CONTENT", "messageId": "msg-123", "delta": "刚刚"})
        await archiver.archive_event({"type": "TEXT_MESSAGE_CONTENT", "messageId": "msg-123", "delta": "问我的问题"})
        await archiver.archive_event({"type": "TEXT_MESSAGE_END", "messageId": "msg-123"})

        messages = mock_storage.get_session_messages("session-123")
        assert len(messages) == 1
        assert messages[0].content == "你刚刚问我的问题"
        assert messages[0].content_segments is not None
        assert len(messages[0].content_segments) == 1
        assert messages[0].content_segments[0].type == "text"
        assert messages[0].content_segments[0].content == "你刚刚问我的问题"

    @pytest.mark.asyncio
    async def test_agui_text_and_tool_segments_keep_order(self, archiver, mock_storage):
        await archiver.on_run_started()

        await archiver.archive_event({"type": "TEXT_MESSAGE_START", "messageId": "msg-456"})
        await archiver.archive_event({"type": "TEXT_MESSAGE_CONTENT", "messageId": "msg-456", "delta": "先读文件，"})
        await archiver.archive_event({
            "type": "TOOL_CALL_START",
            "toolCallId": "tool-read",
            "toolCallName": "read_file",
            "parentMessageId": "msg-456",
        })
        await archiver.archive_event({
            "type": "TOOL_CALL_RESULT",
            "messageId": "msg-456",
            "toolCallId": "tool-read",
            "content": "hello",
        })
        await archiver.archive_event({"type": "TEXT_MESSAGE_CONTENT", "messageId": "msg-456", "delta": "再总结结果。"})
        await archiver.archive_event({"type": "TEXT_MESSAGE_END", "messageId": "msg-456"})

        messages = mock_storage.get_session_messages("session-123")
        assert len(messages) == 1
        assert messages[0].content == "先读文件，再总结结果。"
        assert messages[0].tool_call_ids == ["tool-read"]
        assert messages[0].content_segments is not None
        assert [segment.type for segment in messages[0].content_segments] == ["text", "tool_call", "text"]
        assert messages[0].content_segments[0].content == "先读文件，"
        assert messages[0].content_segments[1].tool_call_id == "tool-read"
        assert messages[0].content_segments[2].content == "再总结结果。"


class TestFinalizeCurrentMessage:
    """Test _finalize_current_message method"""

    @pytest.mark.asyncio
    async def test_finalize_with_content(self, archiver, mock_storage):
        """Test finalizing message with content"""
        await archiver.on_run_started()
        
        # Set up current message
        archiver._current_message_id = "msg-123"
        archiver._current_message_content = "Final content"
        archiver._pending_tool_calls = ["tool-1", "tool-2"]
        
        # Add initial message
        msg = StoredMessage(
            id="msg-123",
            role="assistant",
            content="",
            status=MessageStatus.STREAMING,
        )
        mock_storage.add_session_message("session-123", msg)
        
        await archiver._finalize_current_message()
        
        # Verify message was updated
        messages = mock_storage.get_session_messages("session-123")
        assert messages[0].content == "Final content"
        assert messages[0].status == MessageStatus.COMPLETE
        assert messages[0].tool_call_ids == ["tool-1", "tool-2"]
        
        # Verify state was reset
        assert archiver._current_message_id is None
        assert archiver._current_message_content == ""
        assert archiver._pending_tool_calls == []

    @pytest.mark.asyncio
    async def test_finalize_no_current_message(self, archiver, mock_storage):
        """Test finalizing when no current message"""
        await archiver.on_run_started()
        
        # Should not raise error
        await archiver._finalize_current_message()
        
        # State should remain unchanged
        assert archiver._current_message_id is None

    @pytest.mark.asyncio
    async def test_finalize_recovers_from_streaming_content(self, archiver, mock_storage):
        """Test finalizing recovers content from streaming storage"""
        await archiver.on_run_started()
        
        # Set up message with empty content but streaming content saved
        archiver._current_message_id = "msg-123"
        archiver._current_message_content = ""  # Empty
        mock_storage.save_streaming_content("session-123", "msg-123", "Recovered content")
        
        # Add initial message
        msg = StoredMessage(
            id="msg-123",
            role="assistant",
            content="",
            status=MessageStatus.STREAMING,
        )
        mock_storage.add_session_message("session-123", msg)
        
        await archiver._finalize_current_message()
        
        # Verify content was recovered
        messages = mock_storage.get_session_messages("session-123")
        assert messages[0].content == "Recovered content"


class TestCompleteFlow:
    """Test complete archiving flows"""

    @pytest.mark.asyncio
    async def test_complete_conversation_flow(self, archiver, mock_storage):
        """Test complete conversation with text and tool calls"""
        # Start run
        await archiver.on_run_started([
            {"id": "msg-1", "role": "user", "content": "Read the file /tmp/test.txt"},
        ])
        
        # Assistant starts responding
        await archiver.archive_event({"type": "text", "content": "I'll read that file for you. "})
        
        # Add the message to storage for update
        msg = StoredMessage(
            id=archiver._current_message_id,
            role="assistant",
            content="",
            status=MessageStatus.STREAMING,
        )
        mock_storage.add_session_message("session-123", msg)
        
        # Tool use
        await archiver.archive_event({
            "type": "tool_use",
            "id": "tool-read",
            "name": "read_file",
            "input": {"path": "/tmp/test.txt"},
        })
        
        # Tool result
        await archiver.archive_event({
            "type": "tool_result",
            "tool_use_id": "tool-read",
            "content": "Hello from file!",
        })
        
        # More text
        await archiver.archive_event({"type": "text", "content": "The file contains: Hello from file!"})
        
        # Finish
        await archiver.archive_event({"type": "result"})
        await archiver.on_run_finished()
        
        # Verify final state
        session = mock_storage.get_session_meta("session-123")
        assert session.status == SessionStatus.COMPLETED
        
        # Verify tool call
        tool_call = mock_storage.get_tool_call("session-123", "tool-read")
        assert tool_call.status == ToolCallStatus.COMPLETED
        assert tool_call.result == "Hello from file!"

    @pytest.mark.asyncio
    async def test_error_during_conversation(self, archiver, mock_storage):
        """Test error handling during conversation"""
        await archiver.on_run_started([
            {"id": "msg-1", "role": "user", "content": "Do something complex"},
        ])
        
        # Start responding
        await archiver.archive_event({"type": "text", "content": "Working on it..."})
        
        # Add message to storage
        msg = StoredMessage(
            id=archiver._current_message_id,
            role="assistant",
            content="",
            status=MessageStatus.STREAMING,
        )
        mock_storage.add_session_message("session-123", msg)
        
        # Error occurs
        await archiver.on_run_error("Connection timeout")
        
        # Verify error state
        session = mock_storage.get_session_meta("session-123")
        assert session.status == SessionStatus.ERROR

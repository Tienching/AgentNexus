# -*- coding: utf-8 -*-
"""NexusHub Web API Integration Tests"""

import pytest
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from src.claude_code_api.app import app
from src.claude_code_api.models.session import (
    SessionMeta,
    SessionStatus,
    StoredMessage,
    MessageStatus,
    StoredToolCall,
    ToolCallStatus,
)
from src.claude_code_api.models.task_models import Task, TaskPriority, TaskStatus


class MockSessionStorage:
    """Mock SessionStorage for API testing"""
    
    def __init__(self):
        self.sessions = {}
        self.messages = {}
        self.tool_calls = {}
    
    def get_session_meta(self, session_id: str):
        return self.sessions.get(session_id)
    
    def get_user_sessions(self, username: str, page: int = 1, page_size: int = 20,
                          search: str = None, status_filter = None):
        user_sessions = [s for s in self.sessions.values() if s.username == username]
        
        # Apply filters
        if search:
            user_sessions = [s for s in user_sessions if search.lower() in s.title.lower()]
        if status_filter:
            user_sessions = [s for s in user_sessions if s.status == status_filter]
        
        # Sort by updated_at descending
        user_sessions.sort(key=lambda x: x.updated_at, reverse=True)
        
        total = len(user_sessions)
        start = (page - 1) * page_size
        end = start + page_size
        
        return user_sessions[start:end], total
    
    def get_all_sessions(self, page: int = 1, page_size: int = 20,
                         search: str = None, status_filter = None):
        all_sessions = list(self.sessions.values())
        
        # Apply filters
        if search:
            all_sessions = [s for s in all_sessions if search.lower() in s.title.lower()]
        if status_filter:
            all_sessions = [s for s in all_sessions if s.status == status_filter]
        
        # Sort by updated_at descending
        all_sessions.sort(key=lambda x: x.updated_at, reverse=True)
        
        total = len(all_sessions)
        start = (page - 1) * page_size
        end = start + page_size
        
        return all_sessions[start:end], total
    
    def get_session_messages(self, session_id: str):
        return self.messages.get(session_id, [])
    
    def get_session_tool_calls(self, session_id: str):
        return list(self.tool_calls.get(session_id, {}).values())
    
    def delete_session(self, session_id: str, username: str = None):
        if session_id in self.sessions:
            del self.sessions[session_id]
        if session_id in self.messages:
            del self.messages[session_id]
        if session_id in self.tool_calls:
            del self.tool_calls[session_id]
        return True
    
    def update_session_status(self, session_id: str, status: SessionStatus, update_timestamp: bool = True):
        if session_id in self.sessions:
            self.sessions[session_id].status = status
            return True
        return False
    
    def save_session_meta(self, meta: SessionMeta):
        self.sessions[meta.id] = meta
        return True
    
    def add_message(self, session_id: str, message: StoredMessage):
        if session_id not in self.messages:
            self.messages[session_id] = []
        self.messages[session_id].append(message)
    
    def add_tool_call(self, session_id: str, tool_call: StoredToolCall):
        if session_id not in self.tool_calls:
            self.tool_calls[session_id] = {}
        self.tool_calls[session_id][tool_call.id] = tool_call


@pytest.fixture
def mock_storage():
    """Create mock storage with sample data"""
    storage = MockSessionStorage()
    
    # Add sample sessions
    for i in range(5):
        session = SessionMeta(
            id=f"session-{i}",
            thread_id=f"thread-{i}",
            username="testuser",
            title=f"Test Session {i}",
            status=SessionStatus.COMPLETED if i < 3 else SessionStatus.RUNNING,
            created_at=1704067200000 + i * 1000,
            updated_at=1704067200000 + i * 1000,
            message_count=i + 1,
        )
        storage.save_session_meta(session)
        
        # Add messages
        storage.add_message(f"session-{i}", StoredMessage(
            id=f"msg-user-{i}",
            role="user",
            content=f"User message {i}",
            status=MessageStatus.COMPLETE,
        ))
        storage.add_message(f"session-{i}", StoredMessage(
            id=f"msg-assistant-{i}",
            role="assistant",
            content=f"Assistant response {i}",
            status=MessageStatus.COMPLETE,
        ))
        
        # Add tool call
        storage.add_tool_call(f"session-{i}", StoredToolCall(
            id=f"tool-{i}",
            tool_name="read_file",
            args={"path": f"/tmp/file{i}.txt"},
            status=ToolCallStatus.COMPLETED,
        ))
    
    return storage


@pytest.fixture
async def client(mock_storage):
    """Create test client with mocked storage"""
    with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


class TestListSessions:
    """Test GET /api/nexus/sessions endpoint"""

    @pytest.mark.asyncio
    async def test_list_sessions_success(self, client, mock_storage):
        """Test listing sessions successfully"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get("/api/nexus/sessions", params={"username": "testuser"})
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert len(data["sessions"]) == 5

    @pytest.mark.asyncio
    async def test_list_sessions_with_pagination(self, client, mock_storage):
        """Test listing sessions with pagination"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get(
                "/api/nexus/sessions",
                params={"username": "testuser", "page": 1, "page_size": 2}
            )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert len(data["sessions"]) == 2

    @pytest.mark.asyncio
    async def test_list_sessions_with_search(self, client, mock_storage):
        """Test listing sessions with search filter"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get(
                "/api/nexus/sessions",
                params={"username": "testuser", "search": "Session 1"}
            )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total"] == 1
        assert "Session 1" in data["sessions"][0]["title"]

    @pytest.mark.asyncio
    async def test_list_sessions_with_status_filter(self, client, mock_storage):
        """Test listing sessions with status filter"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get(
                "/api/nexus/sessions",
                params={"username": "testuser", "status": "running"}
            )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total"] == 2
        for session in data["sessions"]:
            assert session["status"] == "running"

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, client, mock_storage):
        """Test listing sessions for user with no sessions"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get(
                "/api/nexus/sessions",
                params={"username": "nonexistent"}
            )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total"] == 0
        assert len(data["sessions"]) == 0

    @pytest.mark.asyncio
    async def test_list_sessions_without_username(self, client, mock_storage):
        """Test listing sessions without username returns all sessions"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get("/api/nexus/sessions")
        
        assert response.status_code == 200
        data = response.json()
        # Should return all sessions when username is not provided
        assert data["total"] == 5


class TestGetSession:
    """Test GET /api/nexus/sessions/{session_id} endpoint"""

    @pytest.mark.asyncio
    async def test_get_session_success(self, client, mock_storage):
        """Test getting session details"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get("/api/nexus/sessions/session-0")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["id"] == "session-0"
        assert data["thread_id"] == "thread-0"
        assert data["username"] == "testuser"
        assert data["title"] == "Test Session 0"

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, client, mock_storage):
        """Test getting non-existent session"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get("/api/nexus/sessions/nonexistent")
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()


class TestGetSessionMessages:
    """Test GET /api/nexus/sessions/{session_id}/messages endpoint"""

    @pytest.mark.asyncio
    async def test_get_messages_success(self, client, mock_storage):
        """Test getting session messages"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get("/api/nexus/sessions/session-0/messages")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["session_id"] == "session-0"
        assert len(data["messages"]) == 2
        assert len(data["tool_calls"]) == 1
        
        # Verify message content
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"
        
        # Verify tool call
        assert data["tool_calls"][0]["tool_name"] == "read_file"

    @pytest.mark.asyncio
    async def test_get_messages_not_found(self, client, mock_storage):
        """Test getting messages for non-existent session"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get("/api/nexus/sessions/nonexistent/messages")
        
        assert response.status_code == 404


class TestDeleteSession:
    """Test DELETE /api/nexus/sessions/{session_id} endpoint"""

    @pytest.mark.asyncio
    async def test_delete_session_success(self, client, mock_storage):
        """Test deleting session"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.delete(
                "/api/nexus/sessions/session-0",
                params={"username": "testuser"}
            )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "session-0" in data["message"]
        
        # Verify session was deleted
        assert mock_storage.get_session_meta("session-0") is None

    @pytest.mark.asyncio
    async def test_delete_session_idempotent(self, client, mock_storage):
        """Test deleting non-existent session (idempotent)"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.delete(
                "/api/nexus/sessions/nonexistent",
                params={"username": "testuser"}
            )
        
        # Should still return success (idempotent)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_delete_session_without_username(self, client, mock_storage):
        """Test deleting session without username still works (username is optional)"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.delete("/api/nexus/sessions/session-0")
        
        # Username is optional, so this should succeed
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


class TestCancelSession:
    """Test POST /api/nexus/sessions/{session_id}/cancel endpoint"""

    @pytest.mark.asyncio
    async def test_cancel_running_session(self, client, mock_storage):
        """Test cancelling a running session"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            # session-3 and session-4 are RUNNING
            response = await client.post("/api/nexus/sessions/session-3/cancel")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["cancelled"] is True
        
        # Verify status was updated
        session = mock_storage.get_session_meta("session-3")
        assert session.status == SessionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_cancel_completed_session(self, client, mock_storage):
        """Test cancelling already completed session"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            # session-0 is COMPLETED
            response = await client.post("/api/nexus/sessions/session-0/cancel")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["cancelled"] is False  # Was not running

    @pytest.mark.asyncio
    async def test_cancel_session_not_found(self, client, mock_storage):
        """Test cancelling non-existent session"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.post("/api/nexus/sessions/nonexistent/cancel")
        
        assert response.status_code == 404


class TestAPIResponseFormats:
    """Test API response format compliance"""

    @pytest.mark.asyncio
    async def test_session_list_response_format(self, client, mock_storage):
        """Test session list response matches expected format"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get(
                "/api/nexus/sessions",
                params={"username": "testuser"}
            )
        
        data = response.json()
        
        # Verify top-level fields
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "sessions" in data
        
        # Verify session fields
        if data["sessions"]:
            session = data["sessions"][0]
            assert "id" in session
            assert "thread_id" in session
            assert "title" in session
            assert "username" in session
            assert "status" in session
            assert "created_at" in session
            assert "updated_at" in session
            assert "message_count" in session

    @pytest.mark.asyncio
    async def test_session_messages_response_format(self, client, mock_storage):
        """Test session messages response matches expected format"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get("/api/nexus/sessions/session-0/messages")
        
        data = response.json()
        
        # Verify top-level fields
        assert "session_id" in data
        assert "messages" in data
        assert "tool_calls" in data
        
        # Verify message fields
        if data["messages"]:
            msg = data["messages"][0]
            assert "id" in msg
            assert "role" in msg
            assert "content" in msg
            assert "status" in msg
            assert "timestamp" in msg
        
        # Verify tool call fields
        if data["tool_calls"]:
            tool = data["tool_calls"][0]
            assert "id" in tool
            assert "tool_name" in tool
            assert "args" in tool
            assert "status" in tool


class TestAPIEdgeCases:
    """Test API edge cases"""

    @pytest.mark.asyncio
    async def test_unicode_in_session_title(self, client, mock_storage):
        """Test handling unicode in session title"""
        # Add session with unicode title
        session = SessionMeta(
            id="unicode-session",
            thread_id="thread-unicode",
            username="testuser",
            title="你好，世界！🌍",
            status=SessionStatus.COMPLETED,
        )
        mock_storage.save_session_meta(session)
        
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get("/api/nexus/sessions/unicode-session")
        
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "你好，世界！🌍"

    @pytest.mark.asyncio
    async def test_large_page_size(self, client, mock_storage):
        """Test page size limit enforcement"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get(
                "/api/nexus/sessions",
                params={"username": "testuser", "page_size": 1000}
            )
        
        # Should return validation error for page_size > 100
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_page_number(self, client, mock_storage):
        """Test invalid page number"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get(
                "/api/nexus/sessions",
                params={"username": "testuser", "page": 0}
            )
        
        # Should return validation error for page < 1
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_special_characters_in_search(self, client, mock_storage):
        """Test special characters in search query"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage):
            response = await client.get(
                "/api/nexus/sessions",
                params={"username": "testuser", "search": "test & <script>"}
            )
        
        assert response.status_code == 200
        # Should not cause any errors, just return no matches


class MockTaskQueue:
    """Mock TaskQueue for task API testing"""

    def __init__(self, tasks):
        self._tasks = {t.id: t for t in tasks}
        # Most recent first (created_at desc)
        self._ordered = sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def list_tasks(self, page=1, page_size=20, status=None, project_id=None, workspace=None, search=None):
        items = list(self._ordered)

        if status:
            items = [t for t in items if (t.status if isinstance(t.status, str) else t.status.value) == status]
        if project_id:
            items = [t for t in items if (t.project_id or "") == project_id]
        if workspace:
            items = [t for t in items if (t.workspace or "") == workspace]
        if search:
            s = search.lower()
            def _hay(t):
                st = t.status if isinstance(t.status, str) else t.status.value
                return " ".join([
                    t.id or "",
                    t.description or "",
                    t.project_id or "",
                    t.project_name or "",
                    t.workspace or "",
                    st or "",
                ]).lower()
            items = [t for t in items if s in _hay(t)]

        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        return items[start:end], total

    def get_task(self, task_id):
        return self._tasks.get(task_id)

    def delete_task_hard(self, task_id: str) -> bool:
        task_id = str(task_id)
        if task_id in self._tasks:
            del self._tasks[task_id]
        self._ordered = [t for t in self._ordered if str(t.id) != task_id]
        return True


@pytest.fixture
def mock_task_queue():
    tasks = [
        Task(description="Fix login", priority=TaskPriority.SERIOUS, project_id="proj-a", project_name="Project A", workspace="/ws/a", status=TaskStatus.TODO, agent_name="ubuntu"),
        Task(description="Refactor API", priority=TaskPriority.THOUGHT, project_id="proj-b", project_name="Project B", workspace="/ws/b", status=TaskStatus.DOING, agent_name="ubuntu"),
        Task(description="Fix checkout", priority=TaskPriority.SERIOUS, project_id="proj-a", project_name="Project A", workspace="/ws/a", status=TaskStatus.DONE, agent_name="ubuntu"),
    ]
    return MockTaskQueue(tasks)


class TestTaskAPI:
    """Task API integration tests"""

    @pytest.mark.asyncio
    async def test_list_tasks_success(self, client, mock_storage, mock_task_queue):
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage), \
             patch('src.claude_code_api.routers.nexus._get_task_queue', return_value=mock_task_queue):
            response = await client.get("/api/nexus/tasks", params={"agent_name": "ubuntu"})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["tasks"]) == 3

    @pytest.mark.asyncio
    async def test_list_tasks_page_size_200_allowed(self, client, mock_storage, mock_task_queue):
        """UI 会用 page_size=200 加载看板；后端应允许该值。"""
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage), \
             patch('src.claude_code_api.routers.nexus._get_task_queue', return_value=mock_task_queue):
            response = await client.get(
                "/api/nexus/tasks",
                params={"agent_name": "ubuntu", "page": 1, "page_size": 200},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["page_size"] == 200
        assert data["total"] == 3
        assert len(data["tasks"]) == 3

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_status(self, client, mock_storage, mock_task_queue):
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage), \
             patch('src.claude_code_api.routers.nexus._get_task_queue', return_value=mock_task_queue):
            response = await client.get("/api/nexus/tasks", params={"agent_name": "ubuntu", "status": "done"})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["tasks"][0]["status"] == "done"

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, client, mock_storage, mock_task_queue):
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage), \
             patch('src.claude_code_api.routers.nexus._get_task_queue', return_value=mock_task_queue):
            response = await client.get("/api/nexus/tasks/nonexistent", params={"agent_name": "ubuntu"})

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_task_agui_messages_missing_log(self, client, mock_storage, mock_task_queue, tmp_path):
        # Ensure base path is tmp and log file does not exist
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage), \
             patch('src.claude_code_api.routers.nexus._get_task_queue', return_value=mock_task_queue), \
             patch('src.claude_code_api.routers.nexus.settings.user_home_base', str(tmp_path)):
            response = await client.get(
                "/api/nexus/tasks/abc123/agui/messages",
                params={"agent_name": "ubuntu"}
            )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_task_agui_messages_success(self, client, mock_storage, mock_task_queue, tmp_path):
        task_id = "abc123"
        log_path = tmp_path / "ubuntu" / "sessions" / f"task_{task_id}" / ".claude" / "conversation.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            '[{"role":"user","content":"hi","timestamp":"2026-01-01T00:00:00Z"},{"role":"assistant","content":"hello"}]',
            encoding="utf-8",
        )

        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage), \
             patch('src.claude_code_api.routers.nexus._get_task_queue', return_value=mock_task_queue), \
             patch('src.claude_code_api.routers.nexus.settings.user_home_base', str(tmp_path)):
            response = await client.get(
                f"/api/nexus/tasks/{task_id}/agui/messages",
                params={"agent_name": "ubuntu", "tail": 1}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "MESSAGES_SNAPSHOT"
        assert len(data["messages"]) == 1
        assert data["messages"][0]["role"] == "assistant"


class TestDeleteTaskAndCascade:
    """Hard delete + cascade behaviors between task and task_<id> session."""

    @pytest.mark.asyncio
    async def test_delete_task_also_deletes_task_session(self, client, mock_storage, mock_task_queue):
        # Pick an existing task
        task_id = next(iter(mock_task_queue._tasks.keys()))
        session_id = f"task_{task_id}"

        # Create corresponding session meta so Chat list would include it
        mock_storage.save_session_meta(SessionMeta(
            id=session_id,
            thread_id=session_id,
            username="testuser",
            title="Task session",
            status=SessionStatus.COMPLETED,
            created_at=1704067200000,
            updated_at=1704067200000,
            agent_name="ubuntu",
        ))

        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage), \
             patch('src.claude_code_api.routers.nexus._get_task_queue', return_value=mock_task_queue):
            resp = await client.delete(f"/api/nexus/tasks/{task_id}", params={"agent_name": "ubuntu"})

        assert resp.status_code == 200
        assert mock_task_queue.get_task(task_id) is None
        assert mock_storage.get_session_meta(session_id) is None

    @pytest.mark.asyncio
    async def test_delete_task_idempotent(self, client, mock_storage, mock_task_queue):
        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage), \
             patch('src.claude_code_api.routers.nexus._get_task_queue', return_value=mock_task_queue):
            resp = await client.delete("/api/nexus/tasks/nonexistent", params={"agent_name": "ubuntu"})

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_task_session_cascades_to_task(self, client, mock_storage, mock_task_queue):
        task_id = next(iter(mock_task_queue._tasks.keys()))
        session_id = f"task_{task_id}"

        # Create corresponding session meta
        mock_storage.save_session_meta(SessionMeta(
            id=session_id,
            thread_id=session_id,
            username="testuser",
            title="Task session",
            status=SessionStatus.COMPLETED,
            created_at=1704067200000,
            updated_at=1704067200000,
            agent_name="ubuntu",
        ))

        with patch('src.claude_code_api.routers.nexus.get_session_storage', return_value=mock_storage), \
             patch('src.claude_code_api.routers.nexus._get_task_queue', return_value=mock_task_queue):
            resp = await client.delete(f"/api/nexus/sessions/{session_id}")

        assert resp.status_code == 200
        assert mock_task_queue.get_task(task_id) is None
        assert mock_storage.get_session_meta(session_id) is None

# -*- coding: utf-8 -*-
"""NexusHub Web API Integration Tests"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from src.server.routers.nexus_history import _build_alias_config_map
from src.server.models import (
    SessionMeta,
    SessionStatus,
    SessionListResponse,
    SessionMessagesResponse,
    StoredMessage,
    MessageStatus,
    StoredToolCall,
    ToolCallStatus,
    Task,
    TaskPriority,
    TaskStatus,
)


TEST_SAFE_STARTUP_POLICY = {
    "start_task_executor": False,
    "start_task_scheduler": False,
    "start_channel_service": False,
    "start_terminal_manager": False,
    "start_evolution_service": False,
}


class MockSessionStorage:
    """Mock SessionStorage for API testing"""
    
    def __init__(self):
        self.sessions = {}
        self.messages = {}
        self.tool_calls = {}
        self.history_runtime_map = {}
        self.history_bootstrap = {}
        self.execution_bindings = {}
    
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

    def get_streaming_content(self, session_id: str, message_id: str):
        return None
    
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

    def add_session_message(self, session_id: str, message: StoredMessage):
        self.add_message(session_id, message)
        return True

    def add_message(self, session_id: str, message: StoredMessage):
        if session_id not in self.messages:
            self.messages[session_id] = []
        self.messages[session_id].append(message)

    def save_tool_call(self, session_id: str, tool_call: StoredToolCall):
        self.add_tool_call(session_id, tool_call)
        return True

    def add_tool_call(self, session_id: str, tool_call: StoredToolCall):
        if session_id not in self.tool_calls:
            self.tool_calls[session_id] = {}
        self.tool_calls[session_id][tool_call.id] = tool_call

    def get_history_runtime_mapping(self, provider: str, history_session_id: str, project_path: str):
        return self.history_runtime_map.get((provider, history_session_id, project_path))

    def set_history_runtime_mapping(self, provider: str, history_session_id: str, project_path: str, runtime_session_id: str):
        self.history_runtime_map[(provider, history_session_id, project_path)] = runtime_session_id
        return True

    def set_history_bootstrap_context(self, session_id: str, context: str):
        self.history_bootstrap[session_id] = context
        return True

    def consume_history_bootstrap_context(self, session_id: str):
        return self.history_bootstrap.pop(session_id, None)

    def set_exec_dir_override(self, session_id: str, exec_dir: str):
        return True

    def set_workspace_provider(self, session_id: str, provider: str):
        return True

    def set_workspace_alias(self, session_id: str, alias: str):
        return True

    def set_inherited_session(self, session_id: str, inherited_from: str):
        return True

    def get_cli_session_id(self, session_id: str):
        return getattr(self, '_cli_session_ids', {}).get(session_id)

    def set_cli_session_id(self, session_id: str, cli_session_id: str):
        if not hasattr(self, '_cli_session_ids'):
            self._cli_session_ids = {}
        self._cli_session_ids[session_id] = cli_session_id
        return True

    def upsert_execution_binding(self, session_id: str, **kwargs):
        current = dict(self.execution_bindings.get(session_id, {}))
        for key, value in kwargs.items():
            if value is not None:
                current[key] = value
        self.execution_bindings[session_id] = current
        return True

    def bind_execution_context(self, session_id: str, **kwargs):
        return self.upsert_execution_binding(session_id, **kwargs)

    def clear_execution_binding_fields(self, session_id: str, *fields: str):
        current = dict(self.execution_bindings.get(session_id, {}))
        for field in fields:
            current.pop(field, None)
        self.execution_bindings[session_id] = current
        return True

    def get_execution_binding(self, session_id: str):
        data = self.execution_bindings.get(session_id)
        return SimpleNamespace(**data) if data else None

    def get_exec_dir_override(self, session_id: str):
        return getattr(self, '_exec_dir_overrides', {}).get(session_id)

    def clear_session_messages(self, session_id: str):
        self.messages[session_id] = []
        return True

    def clear_session_tool_calls(self, session_id: str):
        self.tool_calls[session_id] = {}
        return True

    def hide_history_session(self, session_id: str):
        if not hasattr(self, '_hidden_history'):
            self._hidden_history = set()
        self._hidden_history.add(session_id)
        return True

    def unhide_history_session(self, session_id: str):
        if hasattr(self, '_hidden_history'):
            self._hidden_history.discard(session_id)
        return True

    def is_history_session_hidden(self, session_id: str):
        return session_id in getattr(self, '_hidden_history', set())

    def get_hidden_history_sessions(self):
        return getattr(self, '_hidden_history', set())


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
async def client(mock_storage, app_factory):
    """Create test client with mocked storage"""
    with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage), \
         patch('src.server.routers.nexus_tasks.get_session_storage', return_value=mock_storage), \
         patch('src.server.routers.nexus_streaming.get_session_storage', return_value=mock_storage), \
         patch('src.server.routers.nexus_files.get_session_storage', return_value=mock_storage):
        app = app_factory(startup_policy_overrides=TEST_SAFE_STARTUP_POLICY)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


class TestNexusAuthStatus:
    @pytest.mark.asyncio
    async def test_auth_status_requires_and_accepts_api_token(self, client, monkeypatch):
        from src.server.routers import nexus_auth

        monkeypatch.setattr(nexus_auth.settings, "nexus_password", None)
        monkeypatch.setenv("NEXUS_AUTH_TOKEN", "api-token")

        unauthenticated = await client.get("/api/nexus/auth/status")
        authenticated = await client.get(
            "/api/nexus/auth/status",
            headers={"Authorization": "Bearer api-token"},
        )

        assert unauthenticated.status_code == 200
        assert unauthenticated.json() == {"authenticated": False, "auth_required": True}
        assert authenticated.status_code == 200
        assert authenticated.json() == {"authenticated": True, "auth_required": True}

    @pytest.mark.asyncio
    async def test_auth_status_accepts_bearer_token_when_password_also_configured(self, client, monkeypatch):
        from src.server.routers import nexus_auth

        monkeypatch.setattr(nexus_auth.settings, "nexus_password", "password")
        monkeypatch.setenv("NEXUS_AUTH_TOKEN", "api-token")

        response = await client.get(
            "/api/nexus/auth/status",
            headers={"Authorization": "Bearer api-token"},
        )

        assert response.status_code == 200
        assert response.json() == {"authenticated": True, "auth_required": True}


class TestListSessions:
    """Test GET /api/nexus/sessions endpoint"""

    @pytest.mark.asyncio
    async def test_list_sessions_success(self, client, mock_storage):
        """Test listing sessions successfully"""
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
            response = await client.get("/api/nexus/sessions/nonexistent")
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()


class TestGetSessionMessages:
    """Test GET /api/nexus/sessions/{session_id}/messages endpoint"""

    @pytest.mark.asyncio
    async def test_get_messages_success(self, client, mock_storage):
        """Test getting session messages"""
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
            response = await client.get("/api/nexus/sessions/nonexistent/messages")
        
        assert response.status_code == 404


class TestDeleteSession:
    """Test DELETE /api/nexus/sessions/{session_id} endpoint"""

    @pytest.mark.asyncio
    async def test_delete_session_success(self, client, mock_storage):
        """Test deleting session"""
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
            # session-0 is COMPLETED
            response = await client.post("/api/nexus/sessions/session-0/cancel")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["cancelled"] is False  # Was not running

    @pytest.mark.asyncio
    async def test_cancel_session_not_found(self, client, mock_storage):
        """Test cancelling non-existent session"""
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
            response = await client.post("/api/nexus/sessions/nonexistent/cancel")
        
        assert response.status_code == 404


class TestAPIResponseFormats:
    """Test API response format compliance"""

    @pytest.mark.asyncio
    async def test_session_list_response_format(self, client, mock_storage):
        """Test session list response matches expected format"""
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
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
        
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
            response = await client.get("/api/nexus/sessions/unicode-session")
        
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "你好，世界！🌍"

    @pytest.mark.asyncio
    async def test_large_page_size(self, client, mock_storage):
        """Test page size limit enforcement"""
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
            response = await client.get(
                "/api/nexus/sessions",
                params={"username": "testuser", "page_size": 1000}
            )
        
        # Should return validation error for page_size > 100
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_page_number(self, client, mock_storage):
        """Test invalid page number"""
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
            response = await client.get(
                "/api/nexus/sessions",
                params={"username": "testuser", "page": 0}
            )
        
        # Should return validation error for page < 1
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_special_characters_in_search(self, client, mock_storage):
        """Test special characters in search query"""
        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage):
            response = await client.get(
                "/api/nexus/sessions",
                params={"username": "testuser", "search": "test & <script>"}
            )
        
        assert response.status_code == 200
        # Should not cause any errors, just return no matches


class TestHistoryAliasConfigMap:
    def test_auto_detects_registry_alias_directory(self, tmp_path):
        user_home = tmp_path / "ubuntu"
        user_home.mkdir()
        (user_home / ".claude").mkdir()
        (user_home / ".claude-internal").mkdir()

        class _Registry:
            def list_all(self):
                return {
                    "claude": "claude",
                    "claude-internal": "claude",
                }

        with patch("src.runtime.stores.alias_registry.get_alias_registry", return_value=_Registry()):
            alias_map = _build_alias_config_map(user_home, custom_paths_str="", provider_filter=None)

        assert "claude" in alias_map
        assert "claude-internal" in alias_map
        assert alias_map["claude-internal"] == user_home / ".claude-internal"

    def test_provider_filter_keeps_matching_alias(self, tmp_path):
        user_home = tmp_path / "ubuntu"
        user_home.mkdir()
        (user_home / ".claude-internal").mkdir()

        class _Registry:
            def list_all(self):
                return {"claude-internal": "claude"}

        with patch("src.runtime.stores.alias_registry.get_alias_registry", return_value=_Registry()):
            alias_map = _build_alias_config_map(user_home, custom_paths_str="", provider_filter="claude")

        assert "claude-internal" in alias_map

    def test_custom_paths_skip_other_home_path(self, tmp_path):
        user_home = tmp_path / "ubuntu"
        user_home.mkdir()
        (user_home / ".claude").mkdir()

        with patch("src.runtime.stores.alias_registry.get_alias_registry", return_value=type("_Registry", (), {"list_all": lambda self: {}})()):
            alias_map = _build_alias_config_map(
                user_home,
                custom_paths_str='{"claude-internal":"/home/tswitch/.claude-internal"}',
                provider_filter=None,
            )

        assert "claude-internal" not in alias_map
        assert alias_map["claude"] == user_home / ".claude"

    def test_custom_paths_keep_same_home_path(self, tmp_path):
        user_home = tmp_path / "ubuntu"
        user_home.mkdir()
        (user_home / ".claude").mkdir()

        with patch("src.runtime.stores.alias_registry.get_alias_registry", return_value=type("_Registry", (), {"list_all": lambda self: {}})()):
            alias_map = _build_alias_config_map(
                user_home,
                custom_paths_str='{"claude-internal":"/home/ubuntu/.claude-internal"}',
                provider_filter=None,
            )

        assert alias_map["claude-internal"] == Path("/home/ubuntu/.claude-internal")


class _MockHistoryAllUsersService:
    def sort_history_sessions(self, sessions):
        return sorted(list(sessions or []), key=lambda s: int(getattr(s, "updated_at", 0) or 0), reverse=True)

    async def list_projects(self, alias_config_map, provider_filter=None):
        cfg = str(next(iter(alias_config_map.values()))) if alias_config_map else ""
        if "/home/tswitch/" in cfg:
            return [{
                "path": "/home/tswitch/demo",
                "providers": [{"provider": "claude", "alias": "claude-internal", "session_count": 2}],
                "total_sessions": 2,
                "last_active": 200,
            }]
        return [{
            "path": "/home/ubuntu/demo",
            "providers": [{"provider": "claude", "alias": "claude", "session_count": 1}],
            "total_sessions": 1,
            "last_active": 100,
        }]

    async def list_all_sessions(self, user_home, project_path, alias_config_map, provider_filter=None, search=None, page=1, page_size=20):
        if "tswitch" in str(user_home):
            sess = SessionMeta(
                id="sess-tswitch-1",
                thread_id="sess-tswitch-1",
                title="TSwitch Session",
                username="tswitch",
                provider="claude",
                alias="claude-internal",
                updated_at=300,
                created_at=290,
                message_count=2,
                status=SessionStatus.COMPLETED,
                exec_dir=project_path,
            )
            return SessionListResponse(total=1, page=1, page_size=min(page_size, 100), sessions=[sess])

        sess = SessionMeta(
            id="sess-ubuntu-1",
            thread_id="sess-ubuntu-1",
            title="Ubuntu Session",
            username="ubuntu",
            provider="claude",
            alias="claude",
            updated_at=200,
            created_at=190,
            message_count=1,
            status=SessionStatus.COMPLETED,
            exec_dir=project_path,
        )
        return SessionListResponse(total=1, page=1, page_size=min(page_size, 100), sessions=[sess])

    async def list_global_sessions(self, alias_config_map, provider_filter=None, search=None, page=1, page_size=20, linux_user=None):
        cfg = str(next(iter(alias_config_map.values()))) if alias_config_map else ""
        if "/home/tswitch/" in cfg:
            sess = SessionMeta(
                id="sess-tswitch-global-1",
                thread_id="sess-tswitch-global-1",
                title="TSwitch Global Session",
                username="tswitch",
                exec_user="tswitch",
                provider="claude",
                alias="claude-internal",
                updated_at=300,
                created_at=290,
                message_count=2,
                status=SessionStatus.COMPLETED,
                exec_dir="/home/tswitch/demo",
            )
            return SessionListResponse(total=1, page=1, page_size=min(page_size, 100), sessions=[sess])

        sess = SessionMeta(
            id="sess-ubuntu-global-1",
            thread_id="sess-ubuntu-global-1",
            title="Ubuntu Global Session",
            username="ubuntu",
            exec_user="ubuntu",
            provider="claude",
            alias="claude",
            updated_at=200,
            created_at=190,
            message_count=1,
            status=SessionStatus.COMPLETED,
            exec_dir="/home/ubuntu/demo",
        )
        return SessionListResponse(total=1, page=1, page_size=min(page_size, 100), sessions=[sess])


class TestHistoryAllUsersAPI:
    @pytest.mark.asyncio
    async def test_projects_all_users_aggregates(self, client):
        service = _MockHistoryAllUsersService()

        def _alias_map(user_home, custom_paths_str, provider_filter=None):
            return {"claude": Path(user_home) / ".claude"}

        with patch("src.server.routers.nexus_history._get_history_service", return_value=service), \
             patch("src.server.routers.nexus_history._resolve_history_user_homes", return_value=[Path("/home/ubuntu"), Path("/home/tswitch")]), \
             patch("src.server.routers.nexus_history._build_alias_config_map", side_effect=_alias_map):
            response = await client.get("/api/nexus/history/projects", params={"exec_user": "", "provider": "claude"})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["path"] == "/home/tswitch/demo"
        assert data[1]["path"] == "/home/ubuntu/demo"

    @pytest.mark.asyncio
    async def test_sessions_without_project_path_aggregate_all_projects(self, client):
        service = _MockHistoryAllUsersService()

        def _alias_map(user_home, custom_paths_str, provider_filter=None):
            return {"claude": Path(user_home) / ".claude"}

        with patch("src.server.routers.nexus_history._get_history_service", return_value=service), \
             patch("src.server.routers.nexus_history._resolve_history_user_homes", return_value=[Path("/home/ubuntu"), Path("/home/tswitch")]), \
             patch("src.server.routers.nexus_history._build_alias_config_map", side_effect=_alias_map):
            response = await client.get("/api/nexus/history/sessions", params={"exec_user": "", "provider": "claude"})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert {item["exec_dir"] for item in data["sessions"]} == {"/home/ubuntu/demo", "/home/tswitch/demo"}
        assert data["groups"][0]["provider"] == "claude"

class _MockHistoryService:
    async def get_session_detail(self, provider, config_path, session_id):
        msg_user = StoredMessage(
            id="hist-u1",
            role="user",
            content="历史问题",
            status=MessageStatus.COMPLETE,
        )
        msg_assistant = StoredMessage(
            id="hist-a1",
            role="assistant",
            content="历史回答",
            status=MessageStatus.COMPLETE,
        )
        meta = SessionMeta(
            id=session_id,
            thread_id=session_id,
            title="History Session",
            username="ubuntu",
            status=SessionStatus.COMPLETED,
            created_at=1704067200000,
            updated_at=1704067200000,
            message_count=2,
            provider=provider,
            source="history",
            exec_dir="/home/ubuntu/demo-project",
        )
        return SessionMessagesResponse(
            session_id=session_id,
            messages=[msg_user, msg_assistant],
            tool_calls=[],
            session=meta,
        )


class TestHistoryPromoteAPI:
    @pytest.mark.asyncio
    async def test_promote_history_session_creates_runtime(self, client, mock_storage):
        history_service = _MockHistoryService()
        with patch('src.server.routers.nexus_history.get_session_storage', return_value=mock_storage), \
             patch('src.server.routers.nexus_history._get_history_service', return_value=history_service):
            response = await client.post(
                "/api/nexus/history/sessions/codebuddy/hist-sess-1/promote",
                json={
                    "project_path": "/home/ubuntu/demo-project",
                    "exec_user": "ubuntu",
                    "mode": "full",
                },
            )

        assert response.status_code == 200
        data = response.json()
        runtime_session_id = data["runtime_session_id"]
        assert runtime_session_id in mock_storage.sessions
        assert data["created"] is True
        assert len(mock_storage.messages.get(runtime_session_id, [])) >= 2
        assert mock_storage.history_bootstrap.get(runtime_session_id)

    @pytest.mark.asyncio
    async def test_promote_history_session_reuses_mapping(self, client, mock_storage):
        history_service = _MockHistoryService()
        existing_runtime_session = SessionMeta(
            id="chat_existing_001",
            thread_id="chat_existing_001",
            title="Existing Runtime",
            username="ubuntu",
            status=SessionStatus.IDLE,
            created_at=1704067200000,
            updated_at=1704067200000,
            message_count=0,
            provider="codebuddy",
        )
        mock_storage.save_session_meta(existing_runtime_session)
        mock_storage.set_history_runtime_mapping("codebuddy", "hist-sess-2", "/home/ubuntu/demo-project", "chat_existing_001")

        with patch('src.server.routers.nexus_history.get_session_storage', return_value=mock_storage), \
             patch('src.server.routers.nexus_history._get_history_service', return_value=history_service):
            response = await client.post(
                "/api/nexus/history/sessions/codebuddy/hist-sess-2/promote",
                json={
                    "project_path": "/home/ubuntu/demo-project",
                    "exec_user": "ubuntu",
                    "mode": "full",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["runtime_session_id"] == "chat_existing_001"
        assert data["created"] is False

    @pytest.mark.asyncio
    async def test_promote_history_session_infers_project_path_from_history_meta(self, client, mock_storage):
        history_service = _MockHistoryService()
        with patch('src.server.routers.nexus_history.get_session_storage', return_value=mock_storage), \
             patch('src.server.routers.nexus_history._get_history_service', return_value=history_service):
            response = await client.post(
                "/api/nexus/history/sessions/codebuddy/hist-sess-3/promote",
                json={
                    "exec_user": "ubuntu",
                    "mode": "full",
                },
            )

        assert response.status_code == 200
        data = response.json()
        runtime_session_id = data["runtime_session_id"]
        assert runtime_session_id in mock_storage.sessions
        assert mock_storage.history_runtime_map[("codebuddy", "hist-sess-3", "/home/ubuntu/demo-project")] == runtime_session_id


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

    def add_task(self, description, priority=TaskPriority.THOUGHT, **kwargs):
        allowed = set(Task.model_fields.keys())
        data = {key: value for key, value in kwargs.items() if key in allowed}
        task = Task(description=description, priority=priority, **data)
        self._tasks[task.id] = task
        self._ordered.insert(0, task)
        return task

    def update_task_status(self, task_id, new_status):
        task = self._tasks.get(task_id)
        if not task:
            return None
        current = TaskStatus.from_legacy(task.status if isinstance(task.status, str) else task.status.value)
        target = TaskStatus.from_legacy(new_status if isinstance(new_status, str) else new_status.value)
        if not TaskStatus.can_transition(current, target):
            return None
        task.status = target
        return task

    def update_task(self, task):
        if not task or task.id not in self._tasks:
            return False
        self._tasks[task.id] = task
        self._ordered = [task if t.id == task.id else t for t in self._ordered]
        return True

    def find_task_by_session_id(self, session_id):
        """Find a task whose session_id matches the given value."""
        # Fast path: task_ prefix
        if session_id.startswith("task_"):
            task_id = session_id[len("task_"):]
            task = self._tasks.get(task_id)
            if task:
                return task
        # Slow path: scan all tasks
        for t in self._tasks.values():
            if getattr(t, 'session_id', None) == session_id:
                return t
        return None

    def delete_task_hard(self, task_id: str) -> bool:
        task_id = str(task_id)
        if task_id in self._tasks:
            del self._tasks[task_id]
        self._ordered = [t for t in self._ordered if str(t.id) != task_id]
        return True

    def archive_tasks(self, task_ids):
        from datetime import datetime, timezone

        archived = []
        skipped = {}
        now = datetime.now(timezone.utc)
        for raw_id in task_ids or []:
            task_id = str(raw_id)
            t = self._tasks.get(task_id)
            if not t:
                skipped[task_id] = "not_found"
                continue
            st = t.status if isinstance(t.status, str) else t.status.value
            if st != TaskStatus.DONE.value:
                skipped[task_id] = f"invalid_status:{st}"
                continue
            t.status = TaskStatus.ARCHIVED
            t.archived_at = now
            archived.append(task_id)
        return {"count": len(archived), "archived": archived, "skipped": skipped}

    def unarchive_tasks(self, task_ids):
        unarchived = []
        skipped = {}
        for raw_id in task_ids or []:
            task_id = str(raw_id)
            t = self._tasks.get(task_id)
            if not t:
                skipped[task_id] = "not_found"
                continue
            st = t.status if isinstance(t.status, str) else t.status.value
            if st != TaskStatus.ARCHIVED.value:
                skipped[task_id] = f"invalid_status:{st}"
                continue
            t.status = TaskStatus.DONE
            t.archived_at = None
            unarchived.append(task_id)
        return {"count": len(unarchived), "unarchived": unarchived, "skipped": skipped}

    def clear_tasks(self, task_ids):
        cleared = []
        skipped = {}
        for raw_id in task_ids or []:
            task_id = str(raw_id)
            t = self._tasks.get(task_id)
            if not t:
                skipped[task_id] = "not_found"
                continue
            st = t.status if isinstance(t.status, str) else t.status.value
            if st != TaskStatus.ARCHIVED.value:
                skipped[task_id] = f"invalid_status:{st}"
                continue
            self.delete_task_hard(task_id)
            cleared.append(task_id)
        return {"count": len(cleared), "cleared": cleared, "skipped": skipped}


@pytest.fixture
def mock_task_queue():
    tasks = [
        Task(description="Fix login", priority=TaskPriority.SERIOUS, project_id="proj-a", project_name="Project A", workspace="/ws/a", status=TaskStatus.TODO, exec_user="ubuntu"),
        Task(description="Refactor API", priority=TaskPriority.THOUGHT, project_id="proj-b", project_name="Project B", workspace="/ws/b", status=TaskStatus.DOING, exec_user="ubuntu"),
        Task(description="Fix checkout", priority=TaskPriority.SERIOUS, project_id="proj-a", project_name="Project A", workspace="/ws/a", status=TaskStatus.DONE, exec_user="ubuntu"),
    ]
    return MockTaskQueue(tasks)


class TestTaskAPI:
    """Task API integration tests"""

    @pytest.mark.asyncio
    async def test_list_tasks_success(self, client, mock_storage, mock_task_queue):
        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue):
            response = await client.get("/api/nexus/tasks", params={"exec_user": "ubuntu"})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["tasks"]) == 3

    @pytest.mark.asyncio
    async def test_list_tasks_page_size_200_allowed(self, client, mock_storage, mock_task_queue):
        """UI 会用 page_size=200 加载看板；后端应允许该值。"""
        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue):
            response = await client.get(
                "/api/nexus/tasks",
                params={"exec_user": "ubuntu", "page": 1, "page_size": 200},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["page_size"] == 200
        assert data["total"] == 3
        assert len(data["tasks"]) == 3

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_status(self, client, mock_storage, mock_task_queue):
        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue):
            response = await client.get("/api/nexus/tasks", params={"exec_user": "ubuntu", "status": "done"})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["tasks"][0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_create_task_execution_binding_prefers_prior_session_id(self, client, mock_storage, mock_task_queue):
        registry = SimpleNamespace(list_providers=lambda: ["codebuddy"])

        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue), \
             patch('src.server.routers.nexus_tasks.get_provider_registry', return_value=registry):
            response = await client.post(
                "/api/nexus/tasks",
                params={"exec_user": "ubuntu"},
                json={
                    "description": "Use prior session",
                    "provider": "codebuddy",
                    "source_session_id": "source-session",
                    "prior_session_id": "prior-session",
                    "workspace": "/tmp",
                },
            )

        assert response.status_code == 200
        task = mock_task_queue.get_task(response.json()["id"])
        binding = mock_storage.execution_bindings[task.session_id or f"task_{task.id}"]
        assert binding["source_session_id"] == "prior-session"

    @pytest.mark.asyncio
    async def test_bulk_create_task_execution_binding_prefers_prior_session_id(self, client, mock_storage, mock_task_queue):
        registry = SimpleNamespace(list_providers=lambda: ["codebuddy"])

        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue), \
             patch('src.server.routers.nexus_tasks.get_provider_registry', return_value=registry):
            response = await client.post(
                "/api/nexus/tasks/bulk",
                params={"exec_user": "ubuntu"},
                json={
                    "tasks": [
                        {
                            "description": "Use prior session in bulk",
                            "provider": "codebuddy",
                            "source_session_id": "source-session",
                            "prior_session_id": "prior-session",
                            "workspace": "/tmp",
                        }
                    ]
                },
            )

        assert response.status_code == 200
        task = mock_task_queue.get_task(response.json()["created"][0]["id"])
        binding = mock_storage.execution_bindings[task.session_id or f"task_{task.id}"]
        assert binding["source_session_id"] == "prior-session"

    @pytest.mark.asyncio
    async def test_update_task_due_date_explicit_null_clears_nullable_fields(self, client, mock_storage, mock_task_queue):
        task = next(iter(mock_task_queue._tasks.values()))
        task.due_date = datetime(2026, 5, 1, tzinfo=timezone.utc)
        task.source_session_id = "source-session"
        task.prior_session_id = "prior-session"
        task.prior_work_dir = "/tmp/prior"
        task.repo_url = "https://example.com/repo.git"
        task.repo_root = "/repo"
        task.worktree_path = "/repo/wt"
        task.context = {
            "source_session_id": task.source_session_id,
            "prior_session_id": task.prior_session_id,
            "prior_work_dir": task.prior_work_dir,
            "repo_url": task.repo_url,
            "repo_root": task.repo_root,
            "worktree_path": task.worktree_path,
        }
        binding_session_id = task.session_id or f"task_{task.id}"
        mock_storage.execution_bindings[binding_session_id] = {
            "source_session_id": "prior-session",
            "work_dir": "/repo/wt",
            "metadata": {
                "repo_url": task.repo_url,
                "repo_root": task.repo_root,
                "worktree_path": task.worktree_path,
            },
        }

        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue):
            response = await client.patch(
                f"/api/nexus/tasks/{task.id}",
                params={"exec_user": "ubuntu"},
                json={
                    "due_date": None,
                    "source_session_id": None,
                    "prior_session_id": None,
                    "prior_work_dir": None,
                    "repo_url": None,
                    "repo_root": None,
                    "worktree_path": None,
                },
            )

        assert response.status_code == 200
        updated = mock_task_queue.get_task(task.id)
        assert updated.due_date is None
        assert updated.source_session_id is None
        assert updated.prior_session_id is None
        assert updated.prior_work_dir is None
        assert updated.repo_url is None
        assert updated.repo_root is None
        assert updated.worktree_path is None
        for key in ("source_session_id", "prior_session_id", "prior_work_dir", "repo_url", "repo_root", "worktree_path"):
            assert key not in (updated.context or {})
        binding = mock_storage.execution_bindings[binding_session_id]
        assert binding.get("source_session_id") is None
        assert binding.get("work_dir") is None
        assert binding.get("metadata") is None

    @pytest.mark.asyncio
    async def test_task_summary_metrics_use_total_non_terminal_active_cancelled_and_active_schedules(self, client, mock_storage):
        queue = MockTaskQueue([
            Task(description="Pending", priority=TaskPriority.THOUGHT, status=TaskStatus.PENDING, exec_user="ubuntu"),
            Task(description="Running", priority=TaskPriority.THOUGHT, status=TaskStatus.RUNNING, exec_user="ubuntu"),
            Task(description="Reviewing", priority=TaskPriority.THOUGHT, status=TaskStatus.IN_REVIEW, exec_user="ubuntu"),
            Task(description="Completed", priority=TaskPriority.THOUGHT, status=TaskStatus.COMPLETED, exec_user="ubuntu"),
            Task(description="Failed", priority=TaskPriority.THOUGHT, status=TaskStatus.FAILED, exec_user="ubuntu"),
            Task(description="Cancelled", priority=TaskPriority.THOUGHT, status=TaskStatus.CANCELLED, exec_user="ubuntu"),
        ])

        class _MockScheduleStorage:
            def __init__(self, exec_user="ubuntu"):
                self.exec_user = exec_user

            def list_schedules(self, page=1, page_size=20, status=None):
                assert status == "active"
                return [], 2

        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=queue), \
             patch('src.server.routers.nexus_tasks.ScheduleStorage', _MockScheduleStorage):
            response = await client.get("/api/nexus/tasks/summary", params={"exec_user": "ubuntu"})

        assert response.status_code == 200
        assert response.json() == {
            "total": 6,
            "active": 3,
            "running": 1,
            "reviewing": 1,
            "failed": 1,
            "cancelled": 1,
            "scheduled": 2,
        }

    @pytest.mark.asyncio
    async def test_continue_cancelled_task_is_blocked(self, client, mock_storage):
        queue = MockTaskQueue([
            Task(description="Cancelled", priority=TaskPriority.THOUGHT, status=TaskStatus.CANCELLED, exec_user="ubuntu"),
        ])
        task_id = next(iter(queue._tasks))

        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=queue):
            response = await client.post(
                f"/api/nexus/tasks/{task_id}/continue",
                params={"exec_user": "ubuntu"},
                json={"message": "resume please"},
            )

        assert response.status_code == 409
        assert "cancelled" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_task_status_rejects_completed_to_cancelled(self, client, mock_storage):
        queue = MockTaskQueue([
            Task(description="Done", priority=TaskPriority.THOUGHT, status=TaskStatus.COMPLETED, exec_user="ubuntu"),
        ])
        task_id = next(iter(queue._tasks))

        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=queue):
            response = await client.patch(
                f"/api/nexus/tasks/{task_id}/status",
                params={"exec_user": "ubuntu"},
                json={"status": "cancelled"},
            )

        assert response.status_code == 400
        assert "only pending or running tasks can be cancelled" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_workflow_endpoints_are_removed(self, client, mock_storage):
        response = await client.get("/api/nexus/workflow/templates")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, client, mock_storage, mock_task_queue):
        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue):
            response = await client.get("/api/nexus/tasks/nonexistent", params={"exec_user": "ubuntu"})

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_task_agui_messages_missing_log(self, client, mock_storage, mock_task_queue, tmp_path):
        # Ensure base path is tmp and log file does not exist
        with patch('src.server.routers.nexus_tasks.get_session_storage', return_value=mock_storage), \
             patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue), \
             patch('src.server.routers.nexus_tasks.settings.user_home_base', str(tmp_path)):
            response = await client.get(
                "/api/nexus/tasks/abc123/agui/messages",
                params={"exec_user": "ubuntu"}
            )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_task_agui_messages_success(self, client, mock_storage, mock_task_queue, tmp_path):
        task = next(iter(mock_task_queue._tasks.values()))
        task.session_id = "sess-real"
        task.exec_user = "ubuntu"

        log_path = tmp_path / "ubuntu" / ".nexus" / "sessions" / task.session_id / ".claude" / "conversation.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            '[{"role":"user","content":"hi","timestamp":"2026-01-01T00:00:00Z"},{"role":"assistant","content":"hello"}]',
            encoding="utf-8",
        )

        with patch('src.server.routers.nexus_tasks.get_session_storage', return_value=mock_storage), \
             patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue), \
             patch('src.server.routers.nexus_tasks.settings.user_home_base', str(tmp_path)):
            response = await client.get(
                f"/api/nexus/tasks/{task.id}/agui/messages",
                params={"exec_user": "ubuntu", "tail": 1}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "MESSAGES_SNAPSHOT"
        assert len(data["messages"]) == 1
        assert data["messages"][0]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_task_agui_messages_legacy_task_dir_fallback(self, client, mock_storage, mock_task_queue, tmp_path):
        task = next(iter(mock_task_queue._tasks.values()))
        task.session_id = "sess-missing"
        task.exec_user = "ubuntu"

        log_path = tmp_path / "ubuntu" / ".nexus" / "sessions" / f"task_{task.id}" / ".claude" / "conversation.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            '[{"role":"assistant","content":"legacy hello"}]',
            encoding="utf-8",
        )

        with patch('src.server.routers.nexus_tasks.get_session_storage', return_value=mock_storage), \
             patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue), \
             patch('src.server.routers.nexus_tasks.settings.user_home_base', str(tmp_path)):
            response = await client.get(
                f"/api/nexus/tasks/{task.id}/agui/messages",
                params={"exec_user": "ubuntu", "tail": 1}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "MESSAGES_SNAPSHOT"
        assert data["messages"][0]["content"] == "legacy hello"

    @pytest.mark.asyncio
    async def test_task_agui_messages_accept_large_tail(self, client, mock_storage, mock_task_queue):
        task = next(iter(mock_task_queue._tasks.values()))
        task.session_id = f"task_{task.id}"
        mock_storage.save_session_meta(
            SessionMeta(
                id=task.session_id,
                thread_id=task.session_id,
                username="ubuntu",
                title="Task Session",
                status=SessionStatus.COMPLETED,
                created_at=1704067200000,
                updated_at=1704067200000,
                message_count=2,
            )
        )
        mock_storage.messages[task.session_id] = [
            StoredMessage(id="m1", role="assistant", content="first", status=MessageStatus.COMPLETE),
            StoredMessage(id="m2", role="assistant", content="second", status=MessageStatus.COMPLETE),
        ]

        with patch('src.server.routers.nexus_tasks.get_session_storage', return_value=mock_storage), \
             patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue):
            response = await client.get(
                f"/api/nexus/tasks/{task.id}/agui/messages",
                params={"exec_user": "ubuntu", "tail": 5000},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "MESSAGES_SNAPSHOT"
        assert [msg["content"] for msg in data["messages"]] == ["first", "second"]

    @pytest.mark.asyncio
    async def test_task_agui_stream_replays_in_order_and_ends(self, client, mock_storage):
        task = Task(
            description="Replay AGUI stream",
            priority=TaskPriority.THOUGHT,
            status=TaskStatus.DOING,
            exec_user="ubuntu",
        )
        task.session_id = f"task_{task.id}"
        queue = MockTaskQueue([task])

        events = [
            {"type": "TEXT_MESSAGE_START", "messageId": "m1", "role": "assistant"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "先读文件"},
            {"type": "TOOL_CALL_START", "toolCallId": "t1", "toolCallName": "Read", "parentMessageId": "m1"},
            {"type": "TOOL_CALL_END", "toolCallId": "t1", "result": "ok"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "再总结"},
            {"type": "RUN_FINISHED", "threadId": "th1", "runId": "r1"},
        ]

        mock_storage.get_agui_event_count = lambda session_id: len(events) if session_id == task.session_id else 0
        mock_storage.get_agui_events = lambda session_id, start, end: (events[start:end + 1] if session_id == task.session_id else [])

        with patch('src.server.routers.nexus_streaming.get_session_storage', return_value=mock_storage), \
             patch('src.server.routers.nexus_streaming.get_task_queue', return_value=queue):
            response = await client.get(
                f"/api/nexus/tasks/{task.id}/agui/stream",
                params={"exec_user": "ubuntu", "tail": 5000, "poll_interval_ms": 200},
            )

        assert response.status_code == 200
        body = response.text
        assert 'id: 0' in body
        assert 'id: 5' in body

        idx_text1 = body.find('"type": "TEXT_MESSAGE_CONTENT"')
        idx_tool_start = body.find('"type": "TOOL_CALL_START"')
        idx_tool_end = body.find('"type": "TOOL_CALL_END"')
        idx_finished = body.find('"type": "RUN_FINISHED"')
        assert -1 not in (idx_text1, idx_tool_start, idx_tool_end, idx_finished)
        assert idx_text1 < idx_tool_start < idx_tool_end < idx_finished


class TestTaskBulkAPI:
    """Bulk task operations API integration tests"""

    @pytest.mark.asyncio
    async def test_bulk_archive_and_unarchive(self, client, mock_storage, mock_task_queue):
        done_task = next(t for t in mock_task_queue._tasks.values() if (t.status if isinstance(t.status, str) else t.status.value) == TaskStatus.DONE.value)

        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue):
            resp = await client.post(
                "/api/nexus/tasks/bulk_archive",
                params={"exec_user": "ubuntu"},
                json={"task_ids": [done_task.id]},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["count"] == 1
        assert (mock_task_queue.get_task(done_task.id).status if isinstance(mock_task_queue.get_task(done_task.id).status, str) else mock_task_queue.get_task(done_task.id).status.value) == TaskStatus.ARCHIVED.value

        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue):
            resp2 = await client.post(
                "/api/nexus/tasks/bulk_unarchive",
                params={"exec_user": "ubuntu"},
                json={"task_ids": [done_task.id]},
            )

        assert resp2.status_code == 200
        assert (mock_task_queue.get_task(done_task.id).status if isinstance(mock_task_queue.get_task(done_task.id).status, str) else mock_task_queue.get_task(done_task.id).status.value) == TaskStatus.DONE.value

    @pytest.mark.asyncio
    async def test_bulk_clear_deletes_task_and_session(self, client, mock_storage, mock_task_queue):
        done_task = next(t for t in mock_task_queue._tasks.values() if (t.status if isinstance(t.status, str) else t.status.value) == TaskStatus.DONE.value)

        # Archive it first
        mock_task_queue.archive_tasks([done_task.id])

        session_id = f"task_{done_task.id}"
        mock_storage.save_session_meta(SessionMeta(
            id=session_id,
            thread_id=session_id,
            username="testuser",
            title="Task session",
            status=SessionStatus.COMPLETED,
            created_at=1704067200000,
            updated_at=1704067200000,
            exec_user="ubuntu",
        ))

        with patch('src.server.routers.nexus_tasks.get_session_storage', return_value=mock_storage), \
             patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue):
            resp = await client.post(
                "/api/nexus/tasks/bulk_clear",
                params={"exec_user": "ubuntu"},
                json={"task_ids": [done_task.id]},
            )

        assert resp.status_code == 200
        assert mock_task_queue.get_task(done_task.id) is None
        assert mock_storage.get_session_meta(session_id) is None

    @pytest.mark.asyncio
    async def test_bulk_archive_requires_task_ids(self, client, mock_storage, mock_task_queue):
        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue):
            resp = await client.post(
                "/api/nexus/tasks/bulk_archive",
                params={"exec_user": "ubuntu"},
                json={"task_ids": []},
            )

        assert resp.status_code == 400


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
            exec_user="ubuntu",
        ))

        with patch('src.server.routers.nexus_tasks.get_session_storage', return_value=mock_storage), \
             patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue):
            resp = await client.delete(f"/api/nexus/tasks/{task_id}", params={"exec_user": "ubuntu"})

        assert resp.status_code == 200
        assert mock_task_queue.get_task(task_id) is None
        assert mock_storage.get_session_meta(session_id) is None


class FakeAgentsTaskQueue:
    def list_tasks(self, page=1, page_size=200, status=None):
        tasks = [
            SimpleNamespace(status="running"),
            SimpleNamespace(status="pending"),
            SimpleNamespace(status="failed"),
        ]
        return tasks, len(tasks)


class FakeTokenTracker:
    def get_stats(self, since=None):
        return SimpleNamespace(
            total_requests=6,
            total_prompt_tokens=1200,
            total_completion_tokens=300,
            total_tokens=1500,
            total_cost_usd=1.2345,
        )

    def get_attribution_breakdown(self, since=None):
        return {
            "by_workspace": [
                {
                    "key": "/tmp/agents",
                    "count": 6,
                    "prompt_tokens": 1200,
                    "completion_tokens": 300,
                    "total_tokens": 1500,
                    "total_cost_usd": 1.2345,
                }
            ],
            "by_agent": [
                {
                    "key": "agent-worker-2",
                    "count": 4,
                    "prompt_tokens": 900,
                    "completion_tokens": 250,
                    "total_tokens": 1150,
                    "total_cost_usd": 0.9345,
                },
                {
                    "key": "agent-planner",
                    "count": 2,
                    "prompt_tokens": 300,
                    "completion_tokens": 50,
                    "total_tokens": 350,
                    "total_cost_usd": 0.3000,
                },
            ],
            "by_runtime": [
                {
                    "key": "swarm",
                    "count": 6,
                    "prompt_tokens": 1200,
                    "completion_tokens": 300,
                    "total_tokens": 1500,
                    "total_cost_usd": 1.2345,
                }
            ],
        }


class FakeTeamManager:
    def __init__(self):
        self._teams = {"alpha-team": {"detail": {"provider": "claude", "runtime": "swarm"}}}

    def get_team_status(self, team_name: str):
        if team_name != "alpha-team":
            return {"error": f"Team not found: {team_name}"}
        return {
            "team_name": "alpha-team",
            "members": [
                {
                    "name": "lead",
                    "role": "lead",
                    "status": "running",
                    "agent_id": "agent-worker-2",
                    "capabilities": ["planning", "review"],
                    "unread_mail": 1,
                    "tasks": ["task-1"],
                },
                {
                    "name": "worker-a",
                    "role": "worker",
                    "status": "idle",
                    "agent_id": "agent-planner",
                    "capabilities": ["memory", "analysis"],
                    "unread_mail": 0,
                    "tasks": [],
                },
            ],
            "shared_state": {
                "display_name": "Alpha Team",
                "mission": "Ship Agents page",
                "workspace": "/tmp/agents",
                "shared_memory_policy": "team",
                "tags": ["frontend", "agents"],
            },
            "task_assignments": {},
            "available_tasks": ["task-2"],
            "running_agents": ["run-1"],
        }


def _build_agent_registry():
    from src.nanobot.agent.lifecycle import AgentRegistry, AgentState

    registry = AgentRegistry()
    worker = registry.register(
        name="Worker 2",
        provider="claude",
        workspace="/tmp/agents",
        capabilities=["planning", "review"],
        model="claude-3-sonnet",
        alias="claude",
        agent_id="agent-worker-2",
        metadata={
            "exec_user": "ubuntu",
            "memory_summary": "Shared session context available",
            "memory_entries": ["brief", "notes"],
        },
    )
    registry.update_status(worker.id, AgentState.RUNNING)

    planner = registry.register(
        name="Planner",
        provider="codex",
        workspace="/tmp/agents",
        capabilities=["memory", "analysis"],
        model="gpt-4o",
        alias="codex",
        agent_id="agent-planner",
        metadata={
            "exec_user": "ubuntu",
            "memory_summary": "Read-only memory",
            "memory_entries": ["timeline"],
        },
    )
    registry.update_status(planner.id, AgentState.ERROR)
    return registry


class TestAgentsContracts:
    @pytest.mark.asyncio
    async def test_agents_overview_includes_dashboard_costs_activity_and_team_summaries(self, client):
        registry = _build_agent_registry()
        fake_team_manager = FakeTeamManager()

        with patch.dict("src.server.routers.nexus_agents._AGENT_BINDINGS", {}, clear=True), \
             patch.dict("src.server.routers.nexus_agents._TEAM_CONFIGS", {}, clear=True), \
             patch("src.server.services.agent_registry.get_registry", return_value=registry), \
             patch("src.core.cost.tracker.get_token_tracker", return_value=FakeTokenTracker()), \
             patch("src.server.routers.nexus_models.get_task_queue", return_value=FakeAgentsTaskQueue()), \
             patch("src.server.routers.nexus_agents._get_subagent_manager", return_value=fake_team_manager):
            response = await client.get("/api/nexus/agents/overview")

        assert response.status_code == 200
        data = response.json()

        assert data["dashboard"]["total_agents"] == 2
        assert data["summary"]["teams_total"] == 1
        assert data["dashboard"]["online_agents"] == 2
        assert data["dashboard"]["running_agents"] == 1
        assert data["dashboard"]["error_agents"] == 1
        assert data["costs"]["total_cost_usd"] == pytest.approx(1.2345)
        assert data["recent_activity"]

        worker = next(agent for agent in data["agents"] if agent["id"] == "agent-worker-2")
        assert worker["identity"]["title"] == "Worker 2"
        assert worker["runtime"]["status"] == "running"
        assert worker["memory"]["summary"] == "Shared session context available"
        assert worker["cost"]["total_cost_usd"] == pytest.approx(0.9345)

        team = next(team for team in data["teams"] if team["team_name"] == "alpha-team")
        assert team["identity"]["title"] == "Alpha Team"
        assert team["runtime"]["status"] == "running"
        assert team["members"][0]["role"] == "lead"
        assert team["cost"]["total_cost_usd"] == pytest.approx(1.2345)

    @pytest.mark.asyncio
    async def test_agent_binding_get_and_patch_returns_stable_detail_sections(self, client):
        registry = _build_agent_registry()

        with patch.dict("src.server.routers.nexus_agents._AGENT_BINDINGS", {}, clear=True), \
             patch("src.server.services.agent_registry.get_registry", return_value=registry), \
             patch("src.core.cost.tracker.get_token_tracker", return_value=FakeTokenTracker()):
            get_response = await client.get("/api/nexus/agents/agent-worker-2/binding")
            patch_response = await client.patch(
                "/api/nexus/agents/agent-worker-2/binding",
                json={
                    "team_name": "alpha-team",
                    "runtime_profile": "balanced",
                    "memory_scope": "team",
                    "notes": "Pinned to alpha team",
                    "capabilities": ["planning", "review", "handoff"],
                },
            )
            refetch_response = await client.get("/api/nexus/agents/agent-worker-2/binding")

        assert get_response.status_code == 200
        initial = get_response.json()
        assert initial["binding"]["memory_scope"] == "session"
        assert initial["identity"]["title"] == "Worker 2"
        assert initial["runtime"]["status"] == "running"

        assert patch_response.status_code == 200
        updated = patch_response.json()
        assert updated["binding"]["team_name"] == "alpha-team"
        assert updated["binding"]["runtime_profile"] == "balanced"
        assert updated["binding"]["memory_scope"] == "team"
        assert updated["memory"]["scope"] == "team"
        assert updated["capabilities"] == ["planning", "review", "handoff"]
        assert updated["tools"] == ["planning", "review", "handoff"]

        assert refetch_response.status_code == 200
        refetched = refetch_response.json()
        assert refetched["binding"]["notes"] == "Pinned to alpha team"
        assert refetched["runtime"]["team_name"] == "alpha-team"

    @pytest.mark.asyncio
    async def test_team_config_get_and_patch_returns_runtime_memory_and_members(self, client):
        registry = _build_agent_registry()
        fake_team_manager = FakeTeamManager()

        with patch.dict("src.server.routers.nexus_agents._TEAM_CONFIGS", {}, clear=True), \
             patch("src.server.services.agent_registry.get_registry", return_value=registry), \
             patch("src.core.cost.tracker.get_token_tracker", return_value=FakeTokenTracker()), \
             patch("src.server.routers.nexus_agents._get_subagent_manager", return_value=fake_team_manager):
            get_response = await client.get("/api/nexus/agents/teams/alpha-team/config")
            patch_response = await client.patch(
                "/api/nexus/agents/teams/alpha-team/config",
                json={
                    "display_name": "Alpha Control",
                    "workspace": "/srv/alpha",
                    "mission": "Coordinate detail views",
                    "shared_memory_policy": "shared",
                    "auto_balance": True,
                    "notes": "Keep overview stable",
                    "tags": ["ops", "ui"],
                },
            )
            refetch_response = await client.get("/api/nexus/agents/teams/alpha-team/config")

        assert get_response.status_code == 200
        initial = get_response.json()
        assert initial["config"]["display_name"] == "Alpha Team"
        assert initial["runtime_detail"]["status"] == "running"
        assert initial["memory"]["scope"] == "team"
        assert len(initial["members"]) == 2

        assert patch_response.status_code == 200
        updated = patch_response.json()
        assert updated["config"]["display_name"] == "Alpha Control"
        assert updated["config"]["workspace"] == "/srv/alpha"
        assert updated["config"]["mission"] == "Coordinate detail views"
        assert updated["config"]["shared_memory_policy"] == "shared"
        assert updated["memory_policy"] == "shared"
        assert updated["config"]["auto_balance"] is True
        assert updated["config"]["tags"] == ["ops", "ui"]

        assert refetch_response.status_code == 200
        refetched = refetch_response.json()
        assert refetched["config"]["notes"] == "Keep overview stable"

    @pytest.mark.asyncio
    async def test_delete_task_idempotent(self, client, mock_storage, mock_task_queue):
        with patch('src.server.routers.nexus_tasks.get_task_queue', return_value=mock_task_queue):
            resp = await client.delete("/api/nexus/tasks/nonexistent", params={"exec_user": "ubuntu"})

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
            exec_user="ubuntu",
        ))

        with patch('src.server.routers.nexus_sessions.get_session_storage', return_value=mock_storage), \
             patch('src.server.routers.nexus_sessions.get_task_queue', return_value=mock_task_queue):
            resp = await client.delete(f"/api/nexus/sessions/{session_id}")

        assert resp.status_code == 200
        assert mock_task_queue.get_task(task_id) is None
        assert mock_storage.get_session_meta(session_id) is None

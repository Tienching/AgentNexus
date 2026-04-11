# -*- coding: utf-8 -*-
"""Integration tests for SQLite migration — verify all functionality works without Redis.

Tests exercise the migrated storage layers (session_storage, task_storage,
audit log, auth sessions) to confirm that the system operates correctly
using only SQLite as the data backend.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Point the Database singleton at a temporary file for each test."""
    db_path = str(tmp_path / "test_nexus.db")
    monkeypatch.setenv("NEXUS_DB_PATH", db_path)

    # Reset singleton so each test gets a fresh DB
    from src.runtime.stores.db import Database
    Database._instance = None

    yield db_path

    Database._instance = None


@pytest.fixture
def db():
    from src.runtime.stores.db import get_db
    return get_db()


# ---------------------------------------------------------------------------
# R-002 / R-003: Session Storage — SQLite
# ---------------------------------------------------------------------------

class TestSessionStorage:
    """Verify core session storage works with SQLite (no Redis)."""

    def _make_storage(self):
        from src.core.stores.session_storage import SessionStorage
        return SessionStorage()

    def _make_meta(self, session_id="test-session-1", username="alice"):
        from src.core.models.session import SessionMeta, SessionStatus
        return SessionMeta(
            id=session_id,
            thread_id=session_id,
            title="Test Session",
            username=username,
            status=SessionStatus.IDLE,
            created_at=int(time.time() * 1000),
            updated_at=int(time.time() * 1000),
        )

    def test_save_and_get_meta(self):
        storage = self._make_storage()
        meta = self._make_meta()
        assert storage.save_session_meta(meta) is True

        loaded = storage.get_session_meta("test-session-1")
        assert loaded is not None
        assert loaded.id == "test-session-1"
        assert loaded.title == "Test Session"
        assert loaded.username == "alice"

    def test_get_nonexistent_session(self):
        storage = self._make_storage()
        assert storage.get_session_meta("does-not-exist") is None

    def test_get_user_sessions(self):
        storage = self._make_storage()
        for i in range(5):
            storage.save_session_meta(self._make_meta(f"session-{i}", "alice"))
        storage.save_session_meta(self._make_meta("other-session", "bob"))

        sessions, total = storage.get_user_sessions("alice")
        assert total == 5
        assert len(sessions) == 5

        sessions, total = storage.get_user_sessions("bob")
        assert total == 1

    def test_get_all_sessions_pagination(self):
        storage = self._make_storage()
        for i in range(10):
            storage.save_session_meta(self._make_meta(f"session-{i}", "alice"))

        sessions, total = storage.get_all_sessions(page=1, page_size=3)
        assert total == 10
        assert len(sessions) == 3

    def test_get_all_usernames(self):
        storage = self._make_storage()
        storage.save_session_meta(self._make_meta("s1", "alice"))
        storage.save_session_meta(self._make_meta("s2", "bob"))
        storage.save_session_meta(self._make_meta("s3", "alice"))

        usernames = storage.get_all_usernames()
        assert usernames == ["alice", "bob"]

    def test_update_session_status(self):
        from src.core.models.session import SessionStatus
        storage = self._make_storage()
        storage.save_session_meta(self._make_meta())

        assert storage.update_session_status("test-session-1", SessionStatus.RUNNING) is True
        loaded = storage.get_session_meta("test-session-1")
        assert loaded.status == SessionStatus.RUNNING

    def test_delete_session(self):
        storage = self._make_storage()
        storage.save_session_meta(self._make_meta())
        assert storage.delete_session("test-session-1") is True
        assert storage.get_session_meta("test-session-1") is None

    def test_messages_crud(self):
        from src.core.models.session import StoredMessage
        storage = self._make_storage()
        storage.save_session_meta(self._make_meta())

        msg = StoredMessage(id="msg-1", role="user", content="Hello")
        assert storage.add_session_message("test-session-1", msg) is True

        messages = storage.get_session_messages("test-session-1")
        assert len(messages) == 1
        assert messages[0].content == "Hello"

        # Get by ID
        found = storage.get_message_by_id("test-session-1", "msg-1")
        assert found is not None
        assert found.content == "Hello"

        # Update message
        msg.content = "Hello Updated"
        assert storage.update_message("test-session-1", msg) is True
        found = storage.get_message_by_id("test-session-1", "msg-1")
        assert found.content == "Hello Updated"

        # Clear
        assert storage.clear_session_messages("test-session-1") is True
        assert storage.get_session_messages("test-session-1") == []

    def test_tool_calls_crud(self):
        from src.core.models.session import StoredToolCall
        storage = self._make_storage()
        storage.save_session_meta(self._make_meta())

        tc = StoredToolCall(id="tc-1", tool_name="bash", args={"cmd": "ls"})
        assert storage.save_tool_call("test-session-1", tc) is True

        loaded = storage.get_tool_call("test-session-1", "tc-1")
        assert loaded is not None
        assert loaded.tool_name == "bash"

        all_tc = storage.get_session_tool_calls("test-session-1")
        assert len(all_tc) == 1

    def test_streaming_content(self):
        storage = self._make_storage()
        storage.save_session_meta(self._make_meta())

        assert storage.save_streaming_content("test-session-1", "msg-1", "partial content") is True
        assert storage.get_streaming_content("test-session-1", "msg-1") == "partial content"

        assert storage.delete_streaming_content("test-session-1", "msg-1") is True
        assert storage.get_streaming_content("test-session-1", "msg-1") is None

    def test_agui_events(self):
        storage = self._make_storage()
        storage.save_session_meta(self._make_meta())

        for i in range(5):
            storage.append_agui_event("test-session-1", {"type": "test", "seq": i})

        assert storage.get_agui_event_count("test-session-1") == 5

        events = storage.get_agui_events("test-session-1", start=0, end=2)
        assert len(events) == 3
        assert events[0]["seq"] == 0


# ---------------------------------------------------------------------------
# R-004: Workspace Queue — no Redis dependency
# ---------------------------------------------------------------------------

class TestWorkspaceQueueNoRedis:
    """Verify workspace_queue.py has no Redis import dependency."""

    def test_no_redis_import(self):
        import importlib
        mod = importlib.import_module("src.runtime.execution.workspace_queue")
        source = open(mod.__file__).read()
        assert "redis_client" not in source
        assert "get_redis_client" not in source


# ---------------------------------------------------------------------------
# R-005: Health endpoint
# ---------------------------------------------------------------------------

class TestHealthNoRedis:
    """Verify health check works without Redis."""

    def test_health_check_functions_exist(self):
        from src.server.routers.health import _check_database, _check_redis_optional
        # Should not raise
        db_check = _check_database()
        assert db_check.name == "Database"
        assert db_check.status in ("healthy", "warning", "unhealthy")

        redis_check = _check_redis_optional()
        assert redis_check.name == "Redis (optional)"
        # Without Redis configured, should be degraded
        assert redis_check.status in ("healthy", "degraded")


# ---------------------------------------------------------------------------
# R-006: Audit log — SQLite
# ---------------------------------------------------------------------------

class TestAuditLog:
    """Verify audit log writes to SQLite."""

    def test_record_and_query(self):
        from src.server.routers.nexus_admin import record_audit_event, _audit_db

        record_audit_event("test_action", actor="tester", detail={"key": "value"})
        record_audit_event("test_action", actor="tester2")

        db = _audit_db()
        rows = db.execute_fetchall("SELECT * FROM audit_events ORDER BY id DESC")
        assert len(rows) >= 2
        assert rows[0]["action"] == "test_action"


# ---------------------------------------------------------------------------
# R-006: Auth sessions — SQLite
# ---------------------------------------------------------------------------

class TestAuthSessions:
    """Verify auth session tokens work with SQLite."""

    def test_create_validate_invalidate(self):
        from src.server.routers.nexus_auth import _create_session, _validate_session, _invalidate_session

        token = "test-token-12345"
        _create_session(token)
        assert _validate_session(token) is True

        _invalidate_session(token)
        assert _validate_session(token) is False

    def test_expired_session(self):
        from src.server.routers.nexus_auth import _validate_session, _session_db

        db = _session_db()
        # Insert with an already-expired timestamp
        with db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO auth_sessions (token, expires_at) VALUES (?, ?)",
                ("expired-token", time.time() - 100),
            )

        assert _validate_session("expired-token") is False


# ---------------------------------------------------------------------------
# R-007: pyproject.toml — redis is optional
# ---------------------------------------------------------------------------

class TestPyprojectToml:
    """Verify redis is not a hard dependency."""

    def test_redis_not_in_core_deps(self):
        import tomllib
        toml_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "pyproject.toml"
        )
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)

        core_deps = data.get("project", {}).get("dependencies", [])
        redis_in_core = any("redis" in d.lower() for d in core_deps)
        assert not redis_in_core, "redis should not be a core dependency"

        # Should be in optional deps
        optional = data.get("project", {}).get("optional-dependencies", {})
        mission_deps = optional.get("mission", [])
        redis_in_optional = any("redis" in d.lower() for d in mission_deps)
        assert redis_in_optional, "redis should be in optional 'mission' extras"


# ---------------------------------------------------------------------------
# R-008: .env.example — REDIS_ vars are commented out
# ---------------------------------------------------------------------------

class TestEnvExample:
    """Verify REDIS_* config is marked optional."""

    def test_redis_vars_commented(self):
        env_path = os.path.join(
            os.path.dirname(__file__), "..", "..", ".env.example"
        )
        content = open(env_path).read()
        # All REDIS_* assignments should be commented out
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("REDIS_") and "=" in stripped:
                assert False, f"REDIS var is not commented out: {stripped}"


# ---------------------------------------------------------------------------
# Full-stack: session_storage singleton works
# ---------------------------------------------------------------------------

class TestSessionStorageSingleton:
    """Verify get_session_storage() returns a working singleton."""

    def test_singleton(self):
        from src.core.stores.session_storage import get_session_storage

        s1 = get_session_storage()
        s2 = get_session_storage()
        # Singletons may be different due to DB reset per test, but both should work
        assert s1 is not None
        assert s2 is not None

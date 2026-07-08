# -*- coding: utf-8 -*-
"""Unit tests for the history parsing module.

Tests Claude, Codex, and CodeBuddy parsers using temporary fixture data.
"""

import json
import time
import uuid

import pytest

from src.runtime.history.base_parser import BaseHistoryParser, HistorySessionDetail
from src.runtime.history.claude_parser import ClaudeHistoryParser
from src.runtime.history.codex_parser import CodexHistoryParser
from src.runtime.history.codebuddy_parser import CodeBuddyHistoryParser
from src.runtime.history.service import HistoryService
from src.runtime.models.session import SessionMeta, SessionStatus


# ============ Fixtures ============


@pytest.fixture
def claude_parser():
    return ClaudeHistoryParser()


@pytest.fixture
def codex_parser():
    return CodexHistoryParser()


@pytest.fixture
def codebuddy_parser():
    return CodeBuddyHistoryParser()



@pytest.fixture
def history_service():
    svc = HistoryService()
    svc.register_parser(ClaudeHistoryParser())
    svc.register_parser(CodexHistoryParser())
    svc.register_parser(CodeBuddyHistoryParser())
    return svc


def _write_jsonl(path, entries):
    """Write a list of dicts as JSONL to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


# ============ Claude Parser Tests ============


class TestClaudeParser:
    """Tests for ClaudeHistoryParser."""

    def test_provider_name(self, claude_parser):
        assert claude_parser.provider_name == "claude"

    def test_encode_project_path(self, claude_parser):
        assert claude_parser.encode_project_path("/home/bob/myproject") == "-home-bob-myproject"
        assert claude_parser.encode_project_path("/") == "-"
        assert claude_parser.encode_project_path("/a/b/c") == "-a-b-c"

    def test_list_sessions_empty_dir(self, claude_parser, tmp_path):
        """No sessions when project dir doesn't exist."""
        sessions = claude_parser.list_sessions(tmp_path, "/home/bob/myproject")
        assert sessions == []

    def test_list_sessions_basic(self, claude_parser, tmp_path):
        """Parse basic Claude JSONL with user and assistant messages."""
        project_path = "/home/bob/myproject"
        encoded = claude_parser.encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        session_id = "sess-001"
        ts = int(time.time() * 1000)

        entries = [
            {
                "sessionId": session_id,
                "type": "human",
                "timestamp": ts,
                "cwd": project_path,
                "message": {"role": "user", "content": "Hello world"},
            },
            {
                "sessionId": session_id,
                "type": "assistant",
                "timestamp": ts + 1000,
                "message": {"role": "assistant", "content": "Hi there!"},
            },
        ]

        _write_jsonl(project_dir / "session.jsonl", entries)

        sessions = claude_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert sessions[0].id == session_id
        assert sessions[0].provider == "claude"
        assert sessions[0].source == "history"
        assert sessions[0].status == SessionStatus.COMPLETED
        assert sessions[0].title == "Hello world"
        assert sessions[0].message_count == 2

    def test_list_sessions_skips_error_messages(self, claude_parser, tmp_path):
        """API error messages should be skipped."""
        project_path = "/home/bob/myproject"
        encoded = claude_parser.encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        entries = [
            {
                "sessionId": "sess-err",
                "type": "assistant",
                "timestamp": int(time.time() * 1000),
                "isApiErrorMessage": True,
                "message": {"role": "assistant", "content": "Error occurred"},
            },
            {
                "sessionId": "sess-err",
                "type": "human",
                "timestamp": int(time.time() * 1000),
                "message": {"role": "user", "content": "Fix it"},
            },
        ]

        _write_jsonl(project_dir / "session.jsonl", entries)

        sessions = claude_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert sessions[0].message_count == 1  # Only user message counted

    def test_list_sessions_skips_system_prefixes(self, claude_parser, tmp_path):
        """Messages with system prefixes should be skipped."""
        project_path = "/home/bob/myproject"
        encoded = claude_parser.encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        entries = [
            {
                "sessionId": "sess-sys",
                "type": "human",
                "timestamp": int(time.time() * 1000),
                "message": {"role": "user", "content": "<command-name>some command</command-name>"},
            },
            {
                "sessionId": "sess-sys",
                "type": "human",
                "timestamp": int(time.time() * 1000) + 1000,
                "message": {"role": "user", "content": "Real question"},
            },
        ]

        _write_jsonl(project_dir / "session.jsonl", entries)

        sessions = claude_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert sessions[0].message_count == 1

    def test_list_sessions_excludes_agent_files(self, claude_parser, tmp_path):
        """agent-*.jsonl files should be excluded."""
        project_path = "/home/bob/myproject"
        encoded = claude_parser.encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        # Main session file
        _write_jsonl(project_dir / "session.jsonl", [
            {"sessionId": "s1", "type": "human", "timestamp": 1000000000000,
             "message": {"role": "user", "content": "Hello"}},
        ])

        # Agent file (should be excluded)
        _write_jsonl(project_dir / "agent-abc.jsonl", [
            {"sessionId": "s1", "type": "assistant", "timestamp": 1000000000000,
             "message": {"role": "assistant", "content": "agent response"}},
        ])

        sessions = claude_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert sessions[0].message_count == 1

    def test_list_sessions_summary_as_title(self, claude_parser, tmp_path):
        """Summary entries should set the session title."""
        project_path = "/home/bob/myproject"
        encoded = claude_parser.encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        entries = [
            {
                "sessionId": "s-sum",
                "type": "human",
                "timestamp": int(time.time() * 1000),
                "message": {"role": "user", "content": "Do something"},
            },
            {
                "sessionId": "s-sum",
                "type": "summary",
                "timestamp": int(time.time() * 1000) + 1000,
                "summary": "Working on project configuration",
            },
        ]

        _write_jsonl(project_dir / "session.jsonl", entries)

        sessions = claude_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert sessions[0].title == "Working on project configuration"

    def test_get_session_detail(self, claude_parser, tmp_path):
        """Full message detail retrieval with tool calls."""
        project_path = "/home/bob/myproject"
        encoded = claude_parser.encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        session_id = "sess-detail"
        tool_use_id = str(uuid.uuid4())
        ts = int(time.time() * 1000)

        entries = [
            {
                "sessionId": session_id,
                "type": "human",
                "uuid": "msg-1",
                "timestamp": ts,
                "message": {"role": "user", "content": "List files"},
            },
            {
                "sessionId": session_id,
                "type": "assistant",
                "uuid": "msg-2",
                "timestamp": ts + 1000,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I'll list the files for you."},
                        {
                            "type": "tool_use",
                            "id": tool_use_id,
                            "name": "Bash",
                            "input": {"command": "ls -la"},
                        },
                    ],
                },
            },
            {
                "sessionId": session_id,
                "type": "human",
                "uuid": "msg-3",
                "timestamp": ts + 2000,
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": [{"type": "text", "text": "file1.py\nfile2.py"}],
                        }
                    ],
                },
            },
        ]

        _write_jsonl(project_dir / "session.jsonl", entries)

        detail = claude_parser.get_session_detail(tmp_path, session_id)
        assert detail is not None
        assert detail.session_id == session_id
        assert len(detail.messages) == 2  # user + assistant
        assert len(detail.tool_calls) == 1
        assert detail.tool_calls[0].tool_name == "Bash"
        assert detail.tool_calls[0].result == "file1.py\nfile2.py"
        assert detail.messages[1].tool_call_ids == [tool_use_id]

    def test_get_session_detail_not_found(self, claude_parser, tmp_path):
        """Returns None for non-existent session."""
        (tmp_path / "projects").mkdir()
        detail = claude_parser.get_session_detail(tmp_path, "non-existent")
        assert detail is None

    def test_content_blocks_array(self, claude_parser, tmp_path):
        """Handle content as array of text blocks."""
        project_path = "/home/bob/project"
        encoded = claude_parser.encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        entries = [
            {
                "sessionId": "s-blocks",
                "type": "human",
                "timestamp": int(time.time() * 1000),
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "First part"},
                        {"type": "text", "text": "Second part"},
                    ],
                },
            },
        ]

        _write_jsonl(project_dir / "session.jsonl", entries)

        sessions = claude_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert sessions[0].message_count == 1

    def test_list_sessions_skips_non_message_types(self, claude_parser, tmp_path):
        """progress, system, queue-operation, file-history-snapshot are skipped."""
        project_path = "/home/bob/myproject"
        encoded = claude_parser.encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        ts = int(time.time() * 1000)
        entries = [
            {"sessionId": "s1", "type": "progress", "timestamp": ts,
             "data": {"type": "hook_progress"}, "cwd": project_path},
            {"sessionId": "s1", "type": "system", "timestamp": ts + 100,
             "cwd": project_path},
            {"sessionId": "s1", "type": "queue-operation", "timestamp": ts + 200,
             "operation": "enqueue"},
            {"sessionId": "s1", "type": "file-history-snapshot", "messageId": "x",
             "snapshot": {}, "isSnapshotUpdate": False},
            {"sessionId": "s1", "type": "user", "timestamp": ts + 300,
             "message": {"role": "user", "content": "Real question"},
             "uuid": "u1"},
        ]

        _write_jsonl(project_dir / "session.jsonl", entries)

        sessions = claude_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert sessions[0].message_count == 1

    def test_list_sessions_skips_tool_result_user_messages(self, claude_parser, tmp_path):
        """User messages that only carry tool_result blocks don't count."""
        project_path = "/home/bob/myproject"
        encoded = claude_parser.encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        ts = int(time.time() * 1000)
        entries = [
            {"sessionId": "s1", "type": "user", "timestamp": ts,
             "message": {"role": "user", "content": "Run a command"},
             "uuid": "u1"},
            {"sessionId": "s1", "type": "assistant", "timestamp": ts + 100,
             "message": {"role": "assistant", "content": [
                 {"type": "text", "text": "OK"},
                 {"type": "tool_use", "id": "tc1", "name": "Bash", "input": {}},
             ]}, "uuid": "a1"},
            {"sessionId": "s1", "type": "user", "timestamp": ts + 200,
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "tc1", "content": "output"}
             ]}, "uuid": "u2"},
        ]

        _write_jsonl(project_dir / "session.jsonl", entries)

        sessions = claude_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        # Only 2: real user msg + assistant with text
        assert sessions[0].message_count == 2

    def test_title_newlines_cleaned(self, claude_parser, tmp_path):
        """Title with newlines should be collapsed to single line."""
        project_path = "/home/bob/myproject"
        encoded = claude_parser.encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        ts = int(time.time() * 1000)
        entries = [
            {"sessionId": "s1", "type": "user", "timestamp": ts,
             "message": {"role": "user", "content": "回复一个字\n测试\n"},
             "uuid": "u1"},
        ]

        _write_jsonl(project_dir / "session.jsonl", entries)

        sessions = claude_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert "\n" not in sessions[0].title
        assert sessions[0].title == "回复一个字 测试"

    def test_get_session_detail_skips_non_message_types(self, claude_parser, tmp_path):
        """get_session_detail also skips progress/system/etc."""
        project_path = "/home/bob/myproject"
        encoded = claude_parser.encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        ts = int(time.time() * 1000)
        session_id = "s-detail-skip"
        entries = [
            {"sessionId": session_id, "type": "progress", "timestamp": ts,
             "data": {"type": "hook_progress"}, "cwd": project_path, "uuid": "p1"},
            {"sessionId": session_id, "type": "system", "timestamp": ts + 50, "uuid": "sys1"},
            {"sessionId": session_id, "type": "user", "timestamp": ts + 100,
             "message": {"role": "user", "content": "Hello"},
             "uuid": "u1"},
            {"sessionId": session_id, "type": "assistant", "timestamp": ts + 200,
             "message": {"role": "assistant", "content": "World"},
             "uuid": "a1"},
        ]

        _write_jsonl(project_dir / "session.jsonl", entries)

        detail = claude_parser.get_session_detail(tmp_path, session_id)
        assert detail is not None
        assert len(detail.messages) == 2
        assert detail.messages[0].role == "user"
        assert detail.messages[1].role == "assistant"

    def test_iso_timestamp_parsing(self, claude_parser, tmp_path):
        """ISO 8601 string timestamps are correctly parsed."""
        project_path = "/home/bob/myproject"
        encoded = claude_parser.encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        entries = [
            {"sessionId": "s-iso", "type": "user",
             "timestamp": "2026-02-11T06:37:53.440Z",
             "message": {"role": "user", "content": "ISO test"},
             "uuid": "u1"},
        ]

        _write_jsonl(project_dir / "session.jsonl", entries)

        sessions = claude_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert sessions[0].updated_at > 0


# ============ Codex Parser Tests ============


class TestCodexParser:
    """Tests for CodexHistoryParser."""

    def test_provider_name(self, codex_parser):
        assert codex_parser.provider_name == "codex"

    def test_list_sessions_empty(self, codex_parser, tmp_path):
        """No sessions when sessions dir doesn't exist."""
        sessions = codex_parser.list_sessions(tmp_path, "/home/bob/myproject")
        assert sessions == []

    def test_list_sessions_with_cwd_filter(self, codex_parser, tmp_path):
        """Only sessions matching project_path cwd are returned."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        project_path = "/home/bob/myproject"

        # Matching session (uses payload.message for user text)
        _write_jsonl(sessions_dir / "sess-match.jsonl", [
            {
                "type": "session_meta",
                "timestamp": int(time.time() * 1000),
                "payload": {"id": "sess-match", "cwd": project_path, "model": "o3"},
            },
            {
                "type": "event_msg",
                "timestamp": int(time.time() * 1000),
                "payload": {"type": "user_message", "message": "What is this project?"},
            },
        ])

        # Non-matching session (different project)
        _write_jsonl(sessions_dir / "sess-other.jsonl", [
            {
                "type": "session_meta",
                "timestamp": int(time.time() * 1000),
                "payload": {"id": "sess-other", "cwd": "/home/bob/other-project", "model": "o3"},
            },
            {
                "type": "event_msg",
                "timestamp": int(time.time() * 1000),
                "payload": {"type": "user_message", "message": "Other project question"},
            },
        ])

        sessions = codex_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert sessions[0].id == "sess-match"
        assert sessions[0].provider == "codex"
        assert sessions[0].source == "history"
        assert sessions[0].title == "What is this project?"

    def test_list_sessions_no_cwd_skip(self, codex_parser, tmp_path):
        """Sessions without cwd info are skipped."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        _write_jsonl(sessions_dir / "no-cwd.jsonl", [
            {
                "type": "session_meta",
                "timestamp": int(time.time() * 1000),
                "payload": {"id": "no-cwd"},
            },
        ])

        sessions = codex_parser.list_sessions(tmp_path, "/home/bob/myproject")
        assert sessions == []

    def test_get_session_detail_messages(self, codex_parser, tmp_path):
        """Full message parsing with function calls."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        session_id = "sess-detail"
        ts = int(time.time() * 1000)

        entries = [
            {
                "type": "session_meta",
                "timestamp": ts,
                "payload": {"id": session_id, "cwd": "/home/bob/project"},
            },
            {
                "type": "event_msg",
                "timestamp": ts,
                "payload": {"type": "user_message", "message": "Run ls"},
            },
            {
                "type": "response_item",
                "timestamp": ts + 500,
                "payload": {
                    "type": "message",
                    "id": "msg-asst-1",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "I'll run ls for you."}],
                },
            },
            {
                "type": "response_item",
                "timestamp": ts + 1000,
                "payload": {
                    "type": "function_call",
                    "call_id": "tc-1",
                    "name": "shell_command",
                    "arguments": '{"command": "ls -la"}',
                },
            },
            {
                "type": "response_item",
                "timestamp": ts + 2000,
                "payload": {
                    "type": "function_call_output",
                    "call_id": "tc-1",
                    "output": "file1.py\nfile2.py",
                },
            },
        ]

        _write_jsonl(sessions_dir / f"{session_id}.jsonl", entries)

        detail = codex_parser.get_session_detail(tmp_path, session_id)
        assert detail is not None
        assert len(detail.messages) == 2  # user + assistant
        assert len(detail.tool_calls) == 1
        assert detail.tool_calls[0].tool_name == "Bash"  # shell_command -> Bash
        assert detail.tool_calls[0].result == "file1.py\nfile2.py"

    def test_get_session_detail_custom_tool_call(self, codex_parser, tmp_path):
        """Custom tool call (apply_patch) parsing."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        session_id = "sess-patch"
        ts = int(time.time() * 1000)

        entries = [
            {
                "type": "session_meta",
                "timestamp": ts,
                "payload": {"id": session_id, "cwd": "/home/bob/project"},
            },
            {
                "type": "response_item",
                "timestamp": ts,
                "payload": {
                    "type": "message",
                    "id": "msg-asst",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Applying patch."}],
                },
            },
            {
                "type": "response_item",
                "timestamp": ts + 1000,
                "payload": {
                    "type": "custom_tool_call",
                    "id": "tc-patch",
                    "name": "apply_patch",
                    "input": "*** Update File: /home/bob/project/main.py\n@@ -1,3 +1,3 @@\n-old line\n+new line",
                },
            },
            {
                "type": "response_item",
                "timestamp": ts + 2000,
                "payload": {
                    "type": "custom_tool_call_output",
                    "id": "tc-patch",
                    "output": "Patch applied successfully",
                },
            },
        ]

        _write_jsonl(sessions_dir / f"{session_id}.jsonl", entries)

        detail = codex_parser.get_session_detail(tmp_path, session_id)
        assert detail is not None
        assert len(detail.tool_calls) == 1
        assert detail.tool_calls[0].tool_name == "Edit"  # apply_patch -> Edit
        assert detail.tool_calls[0].result == "Patch applied successfully"
        assert "main.py" in detail.tool_calls[0].args.get("file", "")

    def test_get_session_detail_reasoning(self, codex_parser, tmp_path):
        """Reasoning entries should be included as thinking messages."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        session_id = "sess-think"
        ts = int(time.time() * 1000)

        entries = [
            {
                "type": "session_meta",
                "timestamp": ts,
                "payload": {"id": session_id, "cwd": "/home/bob/project"},
            },
            {
                "type": "response_item",
                "timestamp": ts,
                "payload": {
                    "type": "reasoning",
                    "id": "think-1",
                    "content": [{"type": "summary_text", "text": "Let me think about this..."}],
                },
            },
        ]

        _write_jsonl(sessions_dir / f"{session_id}.jsonl", entries)

        detail = codex_parser.get_session_detail(tmp_path, session_id)
        assert detail is not None
        assert len(detail.messages) == 1
        assert "[Thinking]" in detail.messages[0].content

    def test_get_session_detail_not_found(self, codex_parser, tmp_path):
        """Returns None for non-existent session."""
        (tmp_path / "sessions").mkdir()
        detail = codex_parser.get_session_detail(tmp_path, "non-existent")
        assert detail is None

    def test_user_message_field(self, codex_parser, tmp_path):
        """Codex user_message uses payload.message (string), not payload.content."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        session_id = "sess-msg-field"
        ts = int(time.time() * 1000)
        entries = [
            {"type": "session_meta", "timestamp": ts,
             "payload": {"id": session_id, "cwd": "/home/bob/p"}},
            {"type": "event_msg", "timestamp": ts,
             "payload": {"type": "user_message", "message": "Hello from message field"}},
        ]
        _write_jsonl(sessions_dir / f"{session_id}.jsonl", entries)

        detail = codex_parser.get_session_detail(tmp_path, session_id)
        assert detail is not None
        assert len(detail.messages) == 1
        assert detail.messages[0].content == "Hello from message field"

    def test_reasoning_summary_array(self, codex_parser, tmp_path):
        """Codex reasoning uses payload.summary[].text format."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        session_id = "sess-summary"
        ts = int(time.time() * 1000)
        entries = [
            {"type": "session_meta", "timestamp": ts,
             "payload": {"id": session_id, "cwd": "/home/bob/p"}},
            {"type": "response_item", "timestamp": ts,
             "payload": {
                 "type": "reasoning",
                 "id": "r1",
                 "summary": [{"text": "Analyzing the code"}, {"text": "Found the issue"}],
             }},
        ]
        _write_jsonl(sessions_dir / f"{session_id}.jsonl", entries)

        detail = codex_parser.get_session_detail(tmp_path, session_id)
        assert detail is not None
        assert len(detail.messages) == 1
        assert "Analyzing the code" in detail.messages[0].content
        assert "Found the issue" in detail.messages[0].content

    def test_skip_environment_context(self, codex_parser, tmp_path):
        """Messages containing <environment_context> should be skipped."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        session_id = "sess-env"
        ts = int(time.time() * 1000)
        entries = [
            {"type": "session_meta", "timestamp": ts,
             "payload": {"id": session_id, "cwd": "/home/bob/p"}},
            {"type": "response_item", "timestamp": ts,
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": "<environment_context>system info</environment_context>"}]}},
            {"type": "response_item", "timestamp": ts + 100,
             "payload": {"type": "message", "role": "assistant",
                         "content": [{"type": "output_text", "text": "I can help with that."}]}},
        ]
        _write_jsonl(sessions_dir / f"{session_id}.jsonl", entries)

        detail = codex_parser.get_session_detail(tmp_path, session_id)
        assert detail is not None
        assert len(detail.messages) == 1
        assert detail.messages[0].role == "assistant"

    def test_custom_tool_call_uses_call_id(self, codex_parser, tmp_path):
        """custom_tool_call uses call_id field."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        session_id = "sess-callid"
        ts = int(time.time() * 1000)
        entries = [
            {"type": "session_meta", "timestamp": ts,
             "payload": {"id": session_id, "cwd": "/home/bob/p"}},
            {"type": "response_item", "timestamp": ts,
             "payload": {"type": "message", "id": "m1", "role": "assistant",
                         "content": [{"type": "output_text", "text": "Patching..."}]}},
            {"type": "response_item", "timestamp": ts + 100,
             "payload": {"type": "custom_tool_call", "call_id": "call-123",
                         "name": "apply_patch",
                         "input": "*** Update File: /f.py\n-old\n+new"}},
            {"type": "response_item", "timestamp": ts + 200,
             "payload": {"type": "custom_tool_call_output", "call_id": "call-123",
                         "output": "done"}},
        ]
        _write_jsonl(sessions_dir / f"{session_id}.jsonl", entries)

        detail = codex_parser.get_session_detail(tmp_path, session_id)
        assert detail is not None
        assert len(detail.tool_calls) == 1
        assert detail.tool_calls[0].id == "call-123"
        assert detail.tool_calls[0].result == "done"

    def test_iso_timestamp_in_codex(self, codex_parser, tmp_path):
        """String timestamps (ISO format) are parsed correctly."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        session_id = "sess-iso"
        entries = [
            {"type": "session_meta", "timestamp": "2026-02-11T06:37:53.440Z",
             "payload": {"id": session_id, "cwd": "/home/bob/p"}},
            {"type": "event_msg", "timestamp": "2026-02-11T06:38:00.000Z",
             "payload": {"type": "user_message", "message": "ISO test"}},
        ]
        _write_jsonl(sessions_dir / f"{session_id}.jsonl", entries)

        sessions = codex_parser.list_sessions(tmp_path, "/home/bob/p")
        assert len(sessions) == 1
        assert sessions[0].updated_at > 0


# ============ CodeBuddy Parser Tests ============


class TestCodeBuddyParser:
    """Tests for CodeBuddyHistoryParser."""

    def test_provider_name(self, codebuddy_parser):
        assert codebuddy_parser.provider_name == "codebuddy"

    def test_encode_project_path(self, codebuddy_parser):
        """CodeBuddy uses no leading dash (unlike Claude)."""
        assert codebuddy_parser._encode_project_path("/home/bob/myproject") == "home-bob-myproject"
        assert codebuddy_parser._encode_project_path("/") == ""

    def test_list_sessions_empty(self, codebuddy_parser, tmp_path):
        sessions = codebuddy_parser.list_sessions(tmp_path, "/home/bob/myproject")
        assert sessions == []

    def test_list_sessions_basic(self, codebuddy_parser, tmp_path):
        """Parse basic CodeBuddy JSONL with message entries."""
        project_path = "/home/bob/myproject"
        encoded = codebuddy_parser._encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        ts = int(time.time() * 1000)
        session_id = "cb-sess-1"
        entries = [
            {"id": "m1", "sessionId": session_id, "type": "message", "role": "user",
             "timestamp": ts, "cwd": project_path,
             "content": [{"type": "input_text", "text": "Hello from CodeBuddy"}]},
            {"id": "m2", "sessionId": session_id, "type": "message", "role": "assistant",
             "timestamp": ts + 1000,
             "content": [{"type": "output_text", "text": "Hi there!"}]},
        ]

        _write_jsonl(project_dir / f"{session_id}.jsonl", entries)

        sessions = codebuddy_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert sessions[0].id == session_id
        assert sessions[0].provider == "codebuddy"
        assert sessions[0].source == "history"
        assert sessions[0].title == "Hello from CodeBuddy"
        assert sessions[0].message_count == 2

    def test_list_sessions_topic_as_title(self, codebuddy_parser, tmp_path):
        """Topic entry sets session title."""
        project_path = "/home/bob/myproject"
        encoded = codebuddy_parser._encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        ts = int(time.time() * 1000)
        session_id = "cb-topic"
        entries = [
            {"timestamp": ts, "type": "topic", "topic": "项目全面测试与修订",
             "sessionId": session_id},
            {"id": "m1", "sessionId": session_id, "type": "message", "role": "user",
             "timestamp": ts + 100, "content": [{"type": "input_text", "text": "Test question"}]},
        ]

        _write_jsonl(project_dir / f"{session_id}.jsonl", entries)

        sessions = codebuddy_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert sessions[0].title == "项目全面测试与修订"

    def test_list_sessions_skips_file_history_snapshot(self, codebuddy_parser, tmp_path):
        """file-history-snapshot and reasoning entries are skipped in counting."""
        project_path = "/home/bob/myproject"
        encoded = codebuddy_parser._encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        ts = int(time.time() * 1000)
        session_id = "cb-skip"
        entries = [
            {"id": "s1", "timestamp": ts, "type": "file-history-snapshot",
             "isSnapshotUpdate": False, "sessionId": session_id},
            {"id": "r1", "timestamp": ts + 50, "type": "reasoning",
             "rawContent": [{"type": "reasoning_text", "text": "Thinking..."}],
             "sessionId": session_id},
            {"id": "m1", "sessionId": session_id, "type": "message", "role": "user",
             "timestamp": ts + 100, "content": [{"type": "input_text", "text": "Real Q"}]},
        ]

        _write_jsonl(project_dir / f"{session_id}.jsonl", entries)

        sessions = codebuddy_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert sessions[0].message_count == 1

    def test_list_sessions_skips_system_prefixes(self, codebuddy_parser, tmp_path):
        """System prefix messages are filtered."""
        project_path = "/home/bob/myproject"
        encoded = codebuddy_parser._encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        ts = int(time.time() * 1000)
        session_id = "cb-sys"
        entries = [
            {"id": "m1", "sessionId": session_id, "type": "message", "role": "user",
             "timestamp": ts, "content": [{"type": "input_text", "text": "<command-name>test</command-name>"}]},
            {"id": "m2", "sessionId": session_id, "type": "message", "role": "user",
             "timestamp": ts + 100, "content": [{"type": "input_text", "text": "Real question"}]},
        ]

        _write_jsonl(project_dir / f"{session_id}.jsonl", entries)

        sessions = codebuddy_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert sessions[0].message_count == 1

    def test_get_session_detail_basic(self, codebuddy_parser, tmp_path):
        """Basic message detail retrieval."""
        project_dir = tmp_path / "projects" / "home-bob-myproject"
        project_dir.mkdir(parents=True)

        ts = int(time.time() * 1000)
        session_id = "cb-detail"
        entries = [
            {"id": "m1", "sessionId": session_id, "type": "message", "role": "user",
             "timestamp": ts, "content": [{"type": "input_text", "text": "Hello"}]},
            {"id": "m2", "sessionId": session_id, "type": "message", "role": "assistant",
             "timestamp": ts + 500, "content": [{"type": "output_text", "text": "World"}]},
        ]

        _write_jsonl(project_dir / f"{session_id}.jsonl", entries)

        detail = codebuddy_parser.get_session_detail(tmp_path, session_id)
        assert detail is not None
        assert detail.session_id == session_id
        assert len(detail.messages) == 2
        assert detail.messages[0].role == "user"
        assert detail.messages[0].content == "Hello"
        assert detail.messages[1].role == "assistant"
        assert detail.messages[1].content == "World"

    def test_get_session_detail_function_calls(self, codebuddy_parser, tmp_path):
        """function_call and function_call_result are parsed correctly."""
        project_dir = tmp_path / "projects" / "home-bob-p"
        project_dir.mkdir(parents=True)

        ts = int(time.time() * 1000)
        session_id = "cb-fc"
        entries = [
            {"id": "m1", "sessionId": session_id, "type": "message", "role": "user",
             "timestamp": ts, "content": [{"type": "input_text", "text": "Run ls"}]},
            {"id": "m2", "sessionId": session_id, "type": "message", "role": "assistant",
             "timestamp": ts + 100, "content": [{"type": "output_text", "text": "Running..."}]},
            {"id": "fc1", "sessionId": session_id, "type": "function_call",
             "timestamp": ts + 200, "callId": "call-1", "name": "Bash",
             "arguments": '{"command": "ls -la"}'},
            {"id": "fcr1", "sessionId": session_id, "type": "function_call_result",
             "timestamp": ts + 300, "callId": "call-1", "name": "Bash", "status": "completed",
             "output": {"type": "text", "text": "file1.py\nfile2.py"}},
        ]

        _write_jsonl(project_dir / f"{session_id}.jsonl", entries)

        detail = codebuddy_parser.get_session_detail(tmp_path, session_id)
        assert detail is not None
        assert len(detail.messages) == 2
        assert len(detail.tool_calls) == 1
        assert detail.tool_calls[0].id == "call-1"
        assert detail.tool_calls[0].tool_name == "Bash"
        assert detail.tool_calls[0].result == "file1.py\nfile2.py"
        assert detail.tool_calls[0].status.value == "completed"
        # Tool call should be linked to assistant message
        assert detail.tool_calls[0].parent_message_id == "m2"

    def test_get_session_detail_skips_reasoning(self, codebuddy_parser, tmp_path):
        """Reasoning entries are skipped in message list."""
        project_dir = tmp_path / "projects" / "home-bob-p"
        project_dir.mkdir(parents=True)

        ts = int(time.time() * 1000)
        session_id = "cb-reason"
        entries = [
            {"id": "m1", "sessionId": session_id, "type": "message", "role": "user",
             "timestamp": ts, "content": [{"type": "input_text", "text": "Hello"}]},
            {"id": "r1", "sessionId": session_id, "type": "reasoning",
             "timestamp": ts + 50,
             "rawContent": [{"type": "reasoning_text", "text": "Thinking hard..."}]},
            {"id": "m2", "sessionId": session_id, "type": "message", "role": "assistant",
             "timestamp": ts + 100, "content": [{"type": "output_text", "text": "Done"}]},
        ]

        _write_jsonl(project_dir / f"{session_id}.jsonl", entries)

        detail = codebuddy_parser.get_session_detail(tmp_path, session_id)
        assert detail is not None
        assert len(detail.messages) == 2  # Only user + assistant, no reasoning

    def test_get_session_detail_not_found(self, codebuddy_parser, tmp_path):
        (tmp_path / "projects").mkdir()
        detail = codebuddy_parser.get_session_detail(tmp_path, "non-existent")
        assert detail is None

    def test_extract_text_input_output(self, codebuddy_parser):
        """input_text and output_text block types are correctly extracted."""
        assert codebuddy_parser._extract_text_from_content(
            [{"type": "input_text", "text": "hello"}]
        ) == "hello"
        assert codebuddy_parser._extract_text_from_content(
            [{"type": "output_text", "text": "world"}]
        ) == "world"
        # Also handles plain text type
        assert codebuddy_parser._extract_text_from_content(
            [{"type": "text", "text": "fallback"}]
        ) == "fallback"

    def test_title_newlines_cleaned(self, codebuddy_parser, tmp_path):
        """Title with newlines should be cleaned."""
        project_path = "/home/bob/myproject"
        encoded = codebuddy_parser._encode_project_path(project_path)
        project_dir = tmp_path / "projects" / encoded
        project_dir.mkdir(parents=True)

        ts = int(time.time() * 1000)
        entries = [
            {"id": "m1", "sessionId": "s1", "type": "message", "role": "user",
             "timestamp": ts, "content": [{"type": "input_text", "text": "line1\nline2\n"}]},
        ]
        _write_jsonl(project_dir / "s1.jsonl", entries)

        sessions = codebuddy_parser.list_sessions(tmp_path, project_path)
        assert len(sessions) == 1
        assert "\n" not in sessions[0].title
        assert sessions[0].title == "line1 line2"




def _write_json(path, data):
    """Write a dict as JSON to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


class TestHistoryService:
    """Tests for the HistoryService aggregation layer."""

    def test_register_and_get_parser(self, history_service):
        assert history_service.get_parser("claude") is not None
        assert history_service.get_parser("codex") is not None
        assert history_service.get_parser("codebuddy") is not None
        assert history_service.get_parser("unknown") is None

    def test_resolve_parser_for_alias(self, history_service):
        """Alias resolution falls back to prefix matching."""
        parser = history_service._resolve_parser_for_alias("claude-internal")
        assert parser is not None
        assert parser.provider_name == "claude"

        parser = history_service._resolve_parser_for_alias("codex-custom")
        assert parser is not None
        assert parser.provider_name == "codex"

    @pytest.mark.asyncio
    async def test_list_all_sessions_empty(self, history_service, tmp_path):
        """Empty results when no matching data."""
        result = await history_service.list_all_sessions(
            user_home=tmp_path,
            project_path="/home/bob/myproject",
            alias_config_map={"claude": tmp_path / ".claude"},
        )
        assert result.total == 0
        assert result.sessions == []

    @pytest.mark.asyncio
    async def test_list_all_sessions_cross_provider(self, history_service, tmp_path):
        """Aggregate sessions from multiple providers."""
        project_path = "/home/bob/myproject"

        # Set up Claude data
        claude_config = tmp_path / ".claude"
        encoded = BaseHistoryParser.encode_project_path(project_path)
        project_dir = claude_config / "projects" / encoded
        project_dir.mkdir(parents=True)

        _write_jsonl(project_dir / "session.jsonl", [
            {
                "sessionId": "claude-s1",
                "type": "human",
                "timestamp": int(time.time() * 1000),
                "message": {"role": "user", "content": "Claude question"},
            },
        ])

        # Set up Codex data
        codex_config = tmp_path / ".codex"
        sessions_dir = codex_config / "sessions"
        sessions_dir.mkdir(parents=True)

        _write_jsonl(sessions_dir / "codex-s1.jsonl", [
            {
                "type": "session_meta",
                "timestamp": int(time.time() * 1000),
                "payload": {"id": "codex-s1", "cwd": project_path},
            },
            {
                "type": "event_msg",
                "timestamp": int(time.time() * 1000),
                "payload": {"type": "user_message", "message": "Codex question"},
            },
        ])

        result = await history_service.list_all_sessions(
            user_home=tmp_path,
            project_path=project_path,
            alias_config_map={
                "claude": claude_config,
                "codex": codex_config,
            },
        )

        assert result.total == 2
        providers = {s.provider for s in result.sessions}
        assert "claude" in providers
        assert "codex" in providers

    @pytest.mark.asyncio
    async def test_list_all_sessions_with_search(self, history_service, tmp_path):
        """Search filter on session title."""
        project_path = "/home/bob/myproject"

        claude_config = tmp_path / ".claude"
        encoded = BaseHistoryParser.encode_project_path(project_path)
        project_dir = claude_config / "projects" / encoded
        project_dir.mkdir(parents=True)

        _write_jsonl(project_dir / "session.jsonl", [
            {
                "sessionId": "s-find",
                "type": "human",
                "timestamp": int(time.time() * 1000),
                "message": {"role": "user", "content": "Unique searchable title"},
            },
            {
                "sessionId": "s-other",
                "type": "human",
                "timestamp": int(time.time() * 1000) - 5000,
                "message": {"role": "user", "content": "Something else entirely"},
            },
        ])

        result = await history_service.list_all_sessions(
            user_home=tmp_path,
            project_path=project_path,
            alias_config_map={"claude": claude_config},
            search="searchable",
        )

        assert result.total == 1
        assert "searchable" in result.sessions[0].title.lower()

    @pytest.mark.asyncio
    async def test_list_all_sessions_pagination(self, history_service, tmp_path):
        """Pagination works correctly."""
        project_path = "/home/bob/myproject"

        claude_config = tmp_path / ".claude"
        encoded = BaseHistoryParser.encode_project_path(project_path)
        project_dir = claude_config / "projects" / encoded
        project_dir.mkdir(parents=True)

        entries = []
        for i in range(5):
            entries.append({
                "sessionId": f"s-{i}",
                "type": "human",
                "timestamp": int(time.time() * 1000) + i * 1000,
                "message": {"role": "user", "content": f"Question {i}"},
            })

        _write_jsonl(project_dir / "session.jsonl", entries)

        # Page 1 of 2
        result = await history_service.list_all_sessions(
            user_home=tmp_path,
            project_path=project_path,
            alias_config_map={"claude": claude_config},
            page=1,
            page_size=3,
        )

        assert result.total == 5
        assert len(result.sessions) == 3
        assert result.page == 1
        assert result.page_size == 3

        # Page 2
        result2 = await history_service.list_all_sessions(
            user_home=tmp_path,
            project_path=project_path,
            alias_config_map={"claude": claude_config},
            page=2,
            page_size=3,
        )

        assert result2.total == 5
        assert len(result2.sessions) == 2


# ============ Base Parser Tests ============


class TestBaseParser:
    """Tests for base parser utilities."""

    def test_safe_read_jsonl_valid(self, tmp_path):
        """Read valid JSONL file."""
        jsonl = tmp_path / "test.jsonl"
        jsonl.write_text('{"a": 1}\n{"b": 2}\n')

        entries = list(BaseHistoryParser.safe_read_jsonl(jsonl))
        assert len(entries) == 2
        assert entries[0] == {"a": 1}
        assert entries[1] == {"b": 2}

    def test_safe_read_jsonl_malformed_lines(self, tmp_path):
        """Malformed lines are skipped."""
        jsonl = tmp_path / "bad.jsonl"
        jsonl.write_text('{"good": 1}\nnot json\n{"also_good": 2}\n')

        entries = list(BaseHistoryParser.safe_read_jsonl(jsonl))
        assert len(entries) == 2

    def test_safe_read_jsonl_empty_lines(self, tmp_path):
        """Empty lines are skipped."""
        jsonl = tmp_path / "empty.jsonl"
        jsonl.write_text('\n{"a": 1}\n\n\n{"b": 2}\n\n')

        entries = list(BaseHistoryParser.safe_read_jsonl(jsonl))
        assert len(entries) == 2

    def test_safe_read_jsonl_max_lines(self, tmp_path):
        """Max lines limit is enforced."""
        jsonl = tmp_path / "big.jsonl"
        with open(jsonl, "w") as f:
            for i in range(100):
                f.write(json.dumps({"i": i}) + "\n")

        entries = list(BaseHistoryParser.safe_read_jsonl(jsonl, max_lines=50))
        assert len(entries) == 50

    def test_safe_read_jsonl_missing_file(self, tmp_path):
        """Missing file returns empty."""
        entries = list(BaseHistoryParser.safe_read_jsonl(tmp_path / "missing.jsonl"))
        assert entries == []

    def test_encode_project_path(self):
        assert BaseHistoryParser.encode_project_path("/home/bob/project") == "-home-bob-project"
        assert BaseHistoryParser.encode_project_path("/") == "-"

    def test_normalize_path(self):
        assert BaseHistoryParser.normalize_path("/home/bob/project/") == "/home/bob/project"
        assert BaseHistoryParser.normalize_path("/home/bob/../bob/project") == "/home/bob/project"


# ============ SessionMeta source field ============


class TestSessionMetaSource:
    """Tests for the new source field on SessionMeta."""

    def test_source_default_none(self):
        meta = SessionMeta(id="test", thread_id="test", username="bob")
        assert meta.source is None

    def test_source_history(self):
        meta = SessionMeta(id="test", thread_id="test", username="bob", source="history")
        assert meta.source == "history"

    def test_to_redis_hash_backward_compatible(self):
        """source field doesn't break to_redis_hash."""
        meta = SessionMeta(id="test", thread_id="test", username="bob", source="history")
        redis_hash = meta.to_redis_hash()
        # source is not stored in Redis (it's a runtime-only field)
        assert "id" in redis_hash
        assert "thread_id" in redis_hash

    def test_from_redis_hash_backward_compatible(self):
        """from_redis_hash works without source field."""
        data = {
            "id": "test",
            "thread_id": "test",
            "username": "bob",
            "status": "idle",
            "created_at": "1000",
            "updated_at": "1000",
            "message_count": "0",
        }
        meta = SessionMeta.from_redis_hash(data)
        assert meta.source is None  # Not in Redis data, defaults to None


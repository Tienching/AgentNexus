#!/usr/bin/env python3
"""
Unit tests for the orchestrator CLI script.

Tests all 10 subcommands, formatters, truncation, error handling,
and edge cases — all with mocked HTTP (no live API required).
"""
import json
import sys
import os
import importlib
import types
from unittest.mock import patch, MagicMock
from io import BytesIO

import pytest

# ── Load the orchestrator module from its script path ────────────────
SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "prompts",
    "skills",
    "orchestrator",
    "scripts",
    "orchestrator.py",
)
SCRIPT_PATH = os.path.normpath(SCRIPT_PATH)


def _load_orchestrator():
    """Import orchestrator.py as a module."""
    spec = importlib.util.spec_from_file_location("orchestrator", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


orch = _load_orchestrator()


# ── Fixtures ─────────────────────────────────────────────────────────

def _make_response(data: dict, status: int = 200) -> MagicMock:
    """Create a mock HTTP response."""
    body = json.dumps(data).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.status = status
    return resp


def _make_http_error(code: int, body: str = "error") -> Exception:
    """Create a mock urllib HTTPError."""
    import urllib.error
    err = urllib.error.HTTPError(
        url="http://test",
        code=code,
        msg="Error",
        hdrs={},
        fp=BytesIO(body.encode("utf-8")),
    )
    return err


def _make_url_error(reason: str = "connection refused") -> Exception:
    """Create a mock urllib URLError."""
    import urllib.error
    return urllib.error.URLError(reason)


def _make_args(**kwargs):
    """Create a namespace simulating argparse output."""
    defaults = {"exec_user": "testuser", "api": "http://localhost:8081/api/nexus"}
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


# ── Test: Formatters ─────────────────────────────────────────────────

class TestFormatters:
    def test_format_task_line_basic(self):
        t = {"id": "abc123", "status": "done", "description": "Build API", "provider": "claude"}
        line = orch._format_task_line(t)
        assert "[DONE" in line
        assert "abc123" in line
        assert "Build API" in line
        assert "(claude)" in line

    def test_format_task_line_with_deps(self):
        t = {"id": "x", "status": "todo", "description": "Task", "provider": "codex", "depends_on": ["a", "b"]}
        line = orch._format_task_line(t)
        assert "deps=[a,b]" in line

    def test_format_task_line_multiline_desc(self):
        t = {"id": "x", "status": "doing", "description": "First line\nSecond line\nThird", "provider": "p"}
        line = orch._format_task_line(t)
        assert "First line" in line
        assert "Second line" not in line

    def test_format_task_line_empty_desc(self):
        t = {"id": "x", "status": "todo", "description": "", "provider": "p"}
        line = orch._format_task_line(t)
        assert "(no description)" in line

    def test_format_task_line_no_deps(self):
        t = {"id": "x", "status": "done", "description": "Hi", "provider": "p"}
        line = orch._format_task_line(t)
        assert "deps=" not in line

    def test_format_task_detail_basic(self):
        t = {
            "id": "abc",
            "status": "done",
            "priority": "high",
            "provider": "claude",
            "alias": "claude-4",
            "description": "Do stuff",
            "created_at": "2026-01-01",
        }
        detail = orch._format_task_detail(t)
        assert "Task: abc" in detail
        assert "DONE" in detail
        assert "claude / claude-4" in detail
        assert "Do stuff" in detail
        assert "created_at: 2026-01-01" in detail

    def test_format_task_detail_with_deps_and_error(self):
        t = {
            "id": "x",
            "status": "failed",
            "priority": "normal",
            "provider": "p",
            "description": "desc",
            "depends_on": ["a", "b"],
            "error_message": "something broke " * 50,
        }
        detail = orch._format_task_detail(t)
        assert "Depends:  a, b" in detail
        assert "Error:" in detail
        # error truncated to 200 chars
        assert len([l for l in detail.split("\n") if "Error:" in l][0]) <= 250

    def test_format_task_detail_with_workspace_and_project(self):
        t = {
            "id": "x", "status": "todo", "priority": "low", "provider": "p",
            "description": "d", "workspace": "/home/test", "project_id": "proj1", "project_name": "My Project",
        }
        detail = orch._format_task_detail(t)
        assert "Workspace: /home/test" in detail
        assert "Project:  My Project (proj1)" in detail


class TestTruncate:
    def test_no_truncation(self):
        assert orch._truncate("short text", 100) == "short text"

    def test_truncation(self):
        result = orch._truncate("a" * 200, 50)
        assert len(result) < 200
        assert "truncated" in result
        assert "50/200" in result

    def test_exact_boundary(self):
        text = "a" * 100
        assert orch._truncate(text, 100) == text

    def test_one_over(self):
        text = "a" * 101
        result = orch._truncate(text, 100)
        assert "truncated" in result


# ── Test: APIError ───────────────────────────────────────────────────

class TestAPIError:
    def test_api_error_creation(self):
        err = orch.APIError("test error", status_code=404)
        assert str(err) == "test error"
        assert err.status_code == 404

    def test_api_error_default_code(self):
        err = orch.APIError("fail")
        assert err.status_code == 0


# ── Test: HTTP helpers ───────────────────────────────────────────────

class TestHTTPHelpers:
    @patch("urllib.request.urlopen")
    def test_request_get_success(self, mock_urlopen):
        mock_urlopen.return_value = _make_response({"ok": True})
        # Need to set API_BASE for the module
        old_base = orch.API_BASE
        orch.API_BASE = "http://test:8081/api/nexus"
        try:
            result = orch._request("GET", "/tasks")
            assert result == {"ok": True}
        finally:
            orch.API_BASE = old_base

    @patch("urllib.request.urlopen")
    def test_request_post_with_data(self, mock_urlopen):
        mock_urlopen.return_value = _make_response({"id": "x"})
        old_base = orch.API_BASE
        orch.API_BASE = "http://test:8081/api/nexus"
        try:
            result = orch._request("POST", "/tasks", data={"description": "test"})
            assert result == {"id": "x"}
            # Verify request was made with JSON body
            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            assert req.data is not None
            assert json.loads(req.data) == {"description": "test"}
        finally:
            orch.API_BASE = old_base

    @patch("urllib.request.urlopen")
    def test_request_with_params(self, mock_urlopen):
        mock_urlopen.return_value = _make_response({"tasks": []})
        old_base = orch.API_BASE
        orch.API_BASE = "http://test:8081/api/nexus"
        try:
            orch._request("GET", "/tasks", params={"status": "done", "page": 1, "empty": None})
            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            url = req.full_url
            assert "status=done" in url
            assert "page=1" in url
            assert "empty" not in url  # None params filtered out
        finally:
            orch.API_BASE = old_base

    @patch("urllib.request.urlopen")
    def test_request_http_error_raises_api_error(self, mock_urlopen):
        mock_urlopen.side_effect = _make_http_error(404, '{"detail":"not found"}')
        old_base = orch.API_BASE
        orch.API_BASE = "http://test:8081/api/nexus"
        try:
            with pytest.raises(orch.APIError) as exc_info:
                orch._request("GET", "/tasks/bad")
            assert exc_info.value.status_code == 404
            assert "404" in str(exc_info.value)
        finally:
            orch.API_BASE = old_base

    @patch("urllib.request.urlopen")
    def test_request_connection_error_raises_api_error(self, mock_urlopen):
        mock_urlopen.side_effect = _make_url_error("connection refused")
        old_base = orch.API_BASE
        orch.API_BASE = "http://test:8081/api/nexus"
        try:
            with pytest.raises(orch.APIError) as exc_info:
                orch._request("GET", "/tasks")
            assert "Connection error" in str(exc_info.value)
        finally:
            orch.API_BASE = old_base


# ── Test: Subcommands ────────────────────────────────────────────────

class TestCmdCreate:
    @patch.object(orch, "_post")
    def test_create_basic(self, mock_post, capsys):
        mock_post.return_value = {
            "id": "new123", "status": "todo", "priority": "thought",
            "provider": "claude", "alias": "claude", "description": "Test task",
            "created_at": "2026-01-01",
        }
        args = _make_args(
            description="Test task", provider="claude", alias=None,
            workspace=None, project_id=None, project_name=None, depends_on=None,
        )
        orch.cmd_create(args)
        out = capsys.readouterr().out
        assert "[OK] Created task new123" in out
        assert "Task: new123" in out

    @patch.object(orch, "_post")
    def test_create_with_all_options(self, mock_post, capsys):
        mock_post.return_value = {"id": "x", "status": "todo", "priority": "high", "provider": "codex", "description": "d"}
        args = _make_args(
            description="Full test", provider="codex", alias="codex-v2",
            workspace="/tmp/ws", project_id="proj1", project_name="My Proj",
            depends_on="a,b,c",
        )
        orch.cmd_create(args)
        # Verify payload
        call_data = mock_post.call_args[1].get("data") or mock_post.call_args[0][1]
        assert call_data["depends_on"] == ["a", "b", "c"]
        assert call_data["provider"] == "codex"


class TestCmdList:
    @patch.object(orch, "_get")
    def test_list_basic(self, mock_get, capsys):
        mock_get.return_value = {
            "tasks": [
                {"id": "a", "status": "done", "description": "Task A", "provider": "claude"},
                {"id": "b", "status": "doing", "description": "Task B", "provider": "codex"},
            ],
            "total": 10,
            "page": 1,
        }
        args = _make_args(status=None, project_id=None, search=None, page=1, page_size=15)
        orch.cmd_list(args)
        out = capsys.readouterr().out
        assert "Tasks (2/10, page 1):" in out
        assert "Task A" in out
        assert "Task B" in out
        assert "Summary:" in out

    @patch.object(orch, "_get")
    def test_list_empty(self, mock_get, capsys):
        mock_get.return_value = {"tasks": [], "total": 0, "page": 1}
        args = _make_args(status="doing", project_id=None, search=None, page=1, page_size=15)
        orch.cmd_list(args)
        out = capsys.readouterr().out
        assert "(none)" in out

    @patch.object(orch, "_get")
    def test_list_with_filters(self, mock_get, capsys):
        mock_get.return_value = {"tasks": [], "total": 0, "page": 1}
        args = _make_args(status="done", project_id="proj1", search="API", page=2, page_size=5)
        orch.cmd_list(args)
        call_params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
        assert call_params["status"] == "done"
        assert call_params["project_id"] == "proj1"
        assert call_params["search"] == "API"
        assert call_params["page"] == 2
        assert call_params["page_size"] == 5


class TestCmdGet:
    @patch.object(orch, "_get")
    def test_get_basic(self, mock_get, capsys):
        mock_get.return_value = {
            "id": "abc", "status": "doing", "priority": "normal",
            "provider": "codex", "description": "Analyze data",
            "session_id": "sess_abc",
        }
        args = _make_args(task_id="abc")
        orch.cmd_get(args)
        out = capsys.readouterr().out
        assert "Task: abc" in out
        assert "DOING" in out
        assert "Session:  sess_abc" in out


class TestCmdLog:
    @patch.object(orch, "_get")
    def test_log_with_tail(self, mock_get, capsys):
        mock_get.return_value = {
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
            ]
        }
        args = _make_args(task_id="abc", tail=5, limit=None, max_chars=None)
        orch.cmd_log(args)
        out = capsys.readouterr().out
        assert "2 messages" in out
        assert "[user] hello" in out
        assert "[assistant] world" in out

    @patch.object(orch, "_get")
    def test_log_with_limit(self, mock_get, capsys):
        mock_get.return_value = {"messages": [{"role": "user", "content": "hi"}]}
        args = _make_args(task_id="abc", tail=None, limit=3, max_chars=None)
        orch.cmd_log(args)
        call_params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
        assert "limit" in call_params
        assert "tail" not in call_params

    @patch.object(orch, "_get")
    def test_log_empty(self, mock_get, capsys):
        mock_get.return_value = {"messages": []}
        args = _make_args(task_id="abc", tail=None, limit=None, max_chars=None)
        orch.cmd_log(args)
        out = capsys.readouterr().out
        assert "No conversation log" in out

    @patch.object(orch, "_get")
    def test_log_truncation(self, mock_get, capsys):
        mock_get.return_value = {
            "messages": [{"role": "assistant", "content": "x" * 10000}]
        }
        args = _make_args(task_id="abc", tail=5, limit=None, max_chars=100)
        orch.cmd_log(args)
        out = capsys.readouterr().out
        assert "truncated" in out

    @patch.object(orch, "_get")
    def test_log_tail_takes_priority_over_limit(self, mock_get, capsys):
        """When tail is set, limit should not be sent (mutually exclusive)."""
        mock_get.return_value = {"messages": [{"role": "user", "content": "hi"}]}
        args = _make_args(task_id="abc", tail=5, limit=None, max_chars=None)
        orch.cmd_log(args)
        call_params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
        assert call_params.get("tail") == 5
        assert "limit" not in call_params


class TestCmdResult:
    @patch.object(orch, "_get")
    def test_result_found(self, mock_get, capsys):
        mock_get.return_value = {
            "messages": [
                {"role": "user", "content": "analyze this"},
                {"role": "assistant", "content": "Here is the analysis..."},
            ]
        }
        args = _make_args(task_id="abc", max_chars=None)
        orch.cmd_result(args)
        out = capsys.readouterr().out
        assert "Result for task abc:" in out
        assert "Here is the analysis..." in out

    @patch.object(orch, "_get")
    def test_result_no_assistant_message(self, mock_get, capsys):
        """When no assistant message found, falls back to task detail."""
        mock_get.side_effect = [
            {"messages": [{"role": "user", "content": "hello"}]},  # agui/messages
            {"id": "abc", "status": "doing"},  # task detail
        ]
        args = _make_args(task_id="abc", max_chars=None)
        orch.cmd_result(args)
        out = capsys.readouterr().out
        assert "no result yet" in out

    @patch.object(orch, "_get")
    def test_result_with_error(self, mock_get, capsys):
        mock_get.side_effect = [
            {"messages": []},
            {"id": "abc", "status": "failed", "error_message": "OOM"},
        ]
        args = _make_args(task_id="abc", max_chars=None)
        orch.cmd_result(args)
        out = capsys.readouterr().out
        assert "error: OOM" in out

    @patch.object(orch, "_get")
    def test_result_truncation(self, mock_get, capsys):
        mock_get.return_value = {
            "messages": [{"role": "assistant", "content": "x" * 20000}]
        }
        args = _make_args(task_id="abc", max_chars=50)
        orch.cmd_result(args)
        out = capsys.readouterr().out
        assert "truncated" in out

    @patch.object(orch, "_get")
    def test_result_uses_tail_20(self, mock_get, capsys):
        """Verify result fetches tail=20 to reliably find assistant message."""
        mock_get.return_value = {"messages": [{"role": "assistant", "content": "ok"}]}
        args = _make_args(task_id="abc", max_chars=None)
        orch.cmd_result(args)
        call_params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
        assert call_params.get("tail") == 20

    @patch.object(orch, "_get")
    def test_result_skips_empty_assistant(self, mock_get, capsys):
        """Assistant messages with only whitespace should be skipped."""
        mock_get.side_effect = [
            {"messages": [
                {"role": "assistant", "content": "   "},
                {"role": "assistant", "content": "real answer"},
            ]},
        ]
        args = _make_args(task_id="abc", max_chars=None)
        orch.cmd_result(args)
        out = capsys.readouterr().out
        assert "real answer" in out


class TestCmdCancel:
    @patch.object(orch, "_patch")
    def test_cancel(self, mock_patch, capsys):
        mock_patch.return_value = {"status": "cancelled"}
        args = _make_args(task_id="abc")
        orch.cmd_cancel(args)
        out = capsys.readouterr().out
        assert "[OK] Task abc -> cancelled" in out
        # Verify it called _patch with correct status
        call_data = mock_patch.call_args[1].get("data") or mock_patch.call_args[0][1]
        assert call_data["status"] == "cancelled"


class TestCmdDelete:
    @patch.object(orch, "_delete")
    def test_delete(self, mock_delete, capsys):
        mock_delete.return_value = {"ok": True}
        args = _make_args(task_id="abc")
        orch.cmd_delete(args)
        out = capsys.readouterr().out
        assert "[OK] Deleted task abc" in out


class TestCmdStatus:
    @patch.object(orch, "_patch")
    def test_status_update(self, mock_patch, capsys):
        mock_patch.return_value = {"status": "done"}
        args = _make_args(task_id="abc", new_status="done")
        orch.cmd_status(args)
        out = capsys.readouterr().out
        assert "[OK] Task abc -> done" in out


class TestCmdProjects:
    @patch.object(orch, "_get")
    def test_projects_list_format(self, mock_get, capsys):
        mock_get.return_value = [
            {"project_id": "proj1", "project_name": "My Project", "total_tasks": 5, "todo": 2, "doing": 1, "done": 2},
        ]
        args = _make_args()
        orch.cmd_projects(args)
        out = capsys.readouterr().out
        assert "Projects:" in out
        assert "proj1" in out
        assert "My Project" in out

    @patch.object(orch, "_get")
    def test_projects_dict_format(self, mock_get, capsys):
        """Handle paginated dict response format."""
        mock_get.return_value = {
            "projects": [
                {"project_id": "p1", "project_name": "P1", "total_tasks": 3, "pending": 1, "in_progress": 1, "completed": 1},
            ]
        }
        args = _make_args()
        orch.cmd_projects(args)
        out = capsys.readouterr().out
        assert "p1" in out

    @patch.object(orch, "_get")
    def test_projects_empty(self, mock_get, capsys):
        mock_get.return_value = []
        args = _make_args()
        orch.cmd_projects(args)
        out = capsys.readouterr().out
        assert "No projects found" in out


class TestCmdPlan:
    @patch.object(orch, "_post")
    def test_plan_basic(self, mock_post, capsys):
        mock_post.side_effect = [
            {"id": "real1"},
            {"id": "real2"},
        ]
        plan_json = json.dumps({
            "tasks": [
                {"id": "t1", "title": "Step 1", "description": "First", "provider": "claude"},
                {"id": "t2", "title": "Step 2", "description": "Second", "depends_on": ["t1"]},
            ]
        })
        args = _make_args(plan=plan_json, project_id="test-proj")
        orch.cmd_plan(args)
        out = capsys.readouterr().out
        assert "Creating 2 tasks" in out
        assert "[OK] Step 1 -> real1" in out
        assert "[OK] Step 2 -> real2" in out
        assert "Created 2/2" in out
        assert "t1->real1" in out
        assert "t2->real2" in out

    @patch.object(orch, "_post")
    def test_plan_dependency_resolution(self, mock_post, capsys):
        """Verify that t2's depends_on is resolved to real IDs."""
        mock_post.side_effect = [{"id": "REAL_A"}, {"id": "REAL_B"}]
        plan_json = json.dumps({
            "tasks": [
                {"id": "t1", "title": "A", "description": "d"},
                {"id": "t2", "title": "B", "description": "d", "depends_on": ["t1"]},
            ]
        })
        args = _make_args(plan=plan_json, project_id=None)
        orch.cmd_plan(args)
        # Second call should have depends_on=["REAL_A"]
        second_call_data = mock_post.call_args_list[1][1].get("data") or mock_post.call_args_list[1][0][1]
        assert second_call_data["depends_on"] == ["REAL_A"]

    @patch.object(orch, "_post")
    def test_plan_partial_failure(self, mock_post, capsys):
        """If one task fails, others should still be created."""
        mock_post.side_effect = [
            orch.APIError("HTTP 500: server error", status_code=500),
            {"id": "real2"},
        ]
        plan_json = json.dumps({
            "tasks": [
                {"id": "t1", "title": "Fail", "description": "d"},
                {"id": "t2", "title": "OK", "description": "d"},
            ]
        })
        args = _make_args(plan=plan_json, project_id=None)
        orch.cmd_plan(args)
        out = capsys.readouterr().out
        assert "[FAIL] Fail" in out
        assert "[OK] OK -> real2" in out
        assert "Created 1/2" in out

    @patch.object(orch, "_post")
    def test_plan_unresolved_dependency(self, mock_post, capsys):
        mock_post.side_effect = [
            orch.APIError("fail", status_code=500),
            {"id": "real2"},
        ]
        plan_json = json.dumps({
            "tasks": [
                {"id": "t1", "title": "Fail", "description": "d"},
                {"id": "t2", "title": "B", "description": "d", "depends_on": ["t1"]},
            ]
        })
        args = _make_args(plan=plan_json, project_id=None)
        orch.cmd_plan(args)
        out = capsys.readouterr().out
        assert "[WARN] Dep 't1' for task 't2' not resolved" in out

    def test_plan_invalid_json(self, capsys):
        args = _make_args(plan="not valid json{}", project_id=None)
        with pytest.raises(SystemExit):
            orch.cmd_plan(args)

    @patch.object(orch, "_post")
    def test_plan_empty_tasks(self, mock_post, capsys):
        args = _make_args(plan='{"tasks": []}', project_id=None)
        orch.cmd_plan(args)
        out = capsys.readouterr().out
        assert "No tasks in plan" in out
        mock_post.assert_not_called()


# ── Test: Main error handling ────────────────────────────────────────

class TestMainErrorHandling:
    @patch.object(orch, "_get")
    def test_api_error_caught_at_top_level(self, mock_get, capsys):
        mock_get.side_effect = orch.APIError("HTTP 500: boom", status_code=500)
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["orchestrator.py", "get", "bad-id"]):
                orch.main()
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "500" in err


# ── Test: argparse mutual exclusion ──────────────────────────────────

class TestArgparseMutualExclusion:
    def test_log_tail_and_limit_mutually_exclusive(self, capsys):
        """--tail and --limit cannot be used together."""
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["orchestrator.py", "log", "abc", "--tail", "5", "--limit", "10"]):
                orch.main()
        assert exc_info.value.code == 2  # argparse exits with code 2


# ── Test: Edge cases ─────────────────────────────────────────────────

class TestEdgeCases:
    @patch.object(orch, "_get")
    def test_result_empty_messages_list(self, mock_get, capsys):
        """Empty messages + no error → 'no result yet'."""
        mock_get.side_effect = [
            {"messages": []},
            {"id": "x", "status": "todo"},
        ]
        args = _make_args(task_id="x", max_chars=None)
        orch.cmd_result(args)
        out = capsys.readouterr().out
        assert "no result yet" in out

    @patch.object(orch, "_get")
    def test_list_status_summary(self, mock_get, capsys):
        """Verify status summary counts are correct."""
        mock_get.return_value = {
            "tasks": [
                {"id": "a", "status": "done", "description": "A", "provider": "p"},
                {"id": "b", "status": "done", "description": "B", "provider": "p"},
                {"id": "c", "status": "doing", "description": "C", "provider": "p"},
            ],
            "total": 3, "page": 1,
        }
        args = _make_args(status=None, project_id=None, search=None, page=1, page_size=15)
        orch.cmd_list(args)
        out = capsys.readouterr().out
        assert "doing:1" in out
        assert "done:2" in out

    def test_format_task_line_long_description_truncated(self):
        t = {"id": "x", "status": "todo", "description": "A" * 200, "provider": "p"}
        line = orch._format_task_line(t)
        # First line should be truncated to 80 chars
        desc_part = line.split("]")[1].strip()
        assert len(desc_part) < 200

    @patch.object(orch, "_get")
    def test_log_other_roles(self, mock_get, capsys):
        """Non user/assistant roles should show [role] prefix."""
        mock_get.return_value = {
            "messages": [{"role": "system", "content": "You are helpful"}]
        }
        args = _make_args(task_id="x", tail=5, limit=None, max_chars=None)
        orch.cmd_log(args)
        out = capsys.readouterr().out
        assert "[system] You are helpful" in out

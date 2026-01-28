# -*- coding: utf-8 -*-
"""Slash Command Handler Unit Tests"""

import pytest
import tempfile
import shutil
import re
from pathlib import Path
from unittest.mock import Mock, patch

from src.providers.claude_code_api.services import (
    SlashCommandHandler,
    SLASH_COMMANDS,
)
from src.runtime.commands.slash.handler import slugify_project
from src.providers.claude_code_api.models import TaskPriority, TaskStatus
from src.runtime.commands.slash.worktree import (
    NotGitRepoError,
    WorktreeDirConflictError,
    WorktreeResult,
)


class MockRedisClient:
    """Mock Redis client for slash command handler unit tests.

    This avoids requiring a real Redis during unit tests.
    """

    def __init__(self):
        self._prefix = ""
        self._hashes = {}
        self._sets = {}
        self._sorted_sets = {}
        self._lists = {}

    def _key(self, key: str) -> str:
        return key

    # Hash operations
    def hset(self, name: str, mapping: dict):
        self._hashes.setdefault(name, {}).update(mapping)
        return len(mapping)

    def hgetall(self, name: str):
        return self._hashes.get(name, {}).copy()

    def hget(self, name: str, key: str):
        return self._hashes.get(name, {}).get(key)

    def hdel(self, name: str, *keys: str):
        if name not in self._hashes:
            return 0
        removed = 0
        for k in keys:
            if k in self._hashes[name]:
                del self._hashes[name][k]
                removed += 1
        return removed

    # Set operations
    def sadd(self, name: str, *values):
        s = self._sets.setdefault(name, set())
        before = len(s)
        for v in values:
            s.add(v)
        return len(s) - before

    def srem(self, name: str, *values):
        s = self._sets.setdefault(name, set())
        removed = 0
        for v in values:
            if v in s:
                s.remove(v)
                removed += 1
        return removed

    def smembers(self, name: str):
        return set(self._sets.get(name, set()))

    def scard(self, name: str) -> int:
        return len(self._sets.get(name, set()))

    def sismember(self, name: str, value: str) -> bool:
        return value in self._sets.get(name, set())

    # Sorted set operations
    def zadd(self, name: str, mapping: dict):
        z = self._sorted_sets.setdefault(name, {})
        added = 0
        for member, score in mapping.items():
            if member not in z:
                added += 1
            z[member] = score
        return added

    def zrem(self, name: str, *values):
        z = self._sorted_sets.setdefault(name, {})
        removed = 0
        for v in values:
            if v in z:
                del z[v]
                removed += 1
        return removed

    def zrange(self, name: str, start: int, end: int, withscores: bool = False):
        z = self._sorted_sets.get(name, {})
        items = sorted(z.items(), key=lambda x: x[1])
        if end == -1:
            end = len(items) - 1
        sliced = items[start : end + 1]
        return sliced if withscores else [m for m, _ in sliced]

    # List operations
    def lpush(self, name: str, *values):
        lst = self._lists.setdefault(name, [])
        for v in reversed(values):
            lst.insert(0, v)
        return len(lst)

    def rpush(self, name: str, *values):
        lst = self._lists.setdefault(name, [])
        lst.extend(values)
        return len(lst)

    def lrange(self, name: str, start: int, end: int):
        lst = self._lists.get(name, [])
        if end == -1:
            end = len(lst) - 1
        return lst[start : end + 1]

    def lpop(self, name: str):
        lst = self._lists.get(name, [])
        if not lst:
            return None
        return lst.pop(0)

    def rpop(self, name: str):
        lst = self._lists.get(name, [])
        if not lst:
            return None
        return lst.pop()

    def llen(self, name: str) -> int:
        return len(self._lists.get(name, []))

    def lrem(self, name: str, count: int, value: str) -> int:
        lst = self._lists.get(name, [])
        before = len(lst)
        self._lists[name] = [v for v in lst if v != value]
        return before - len(self._lists[name])

    # Scan operations
    def scan_iter(self, match: str, count: int = 100):
        # Minimal implementation for patterns used by code
        needle = match.replace("*", "")
        for key in list(self._sets.keys()) + list(self._lists.keys()) + list(self._hashes.keys()):
            if needle in key:
                yield key


class TestSlugifyProject:
    """Test project name slugification"""

    def test_basic_slugify(self):
        assert slugify_project("My Project") == "my-project"
        assert slugify_project("Hello World") == "hello-world"

    def test_special_characters(self):
        assert slugify_project("My_Project!@#") == "myproject"
        assert slugify_project("test...project") == "testproject"

    def test_multiple_spaces(self):
        assert slugify_project("my   project") == "my-project"

    def test_leading_trailing(self):
        assert slugify_project("  my-project  ") == "my-project"


class TestSlashCommandHandler:
    """SlashCommandHandler tests"""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for tests"""
        temp = tempfile.mkdtemp()
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.fixture
    def mock_config(self, temp_dir):
        """Create mock config"""
        config = Mock()
        config.user_home_base = temp_dir
        return config

    @pytest.fixture
    def handler(self, mock_config):
        """Create handler instance (with mocked Redis backend)."""
        mock_redis = MockRedisClient()
        with patch('src.runtime.stores.task_storage.get_redis_client', return_value=mock_redis):
            h = SlashCommandHandler("test_agent", mock_config)
            # force queue init and bind redis
            _ = h.task_queue
            h.task_queue._redis = mock_redis
            return h

    def test_is_slash_command(self, handler):
        """Test slash command detection"""
        assert handler.is_slash_command("/task -- hello")
        assert handler.is_slash_command("/check")
        assert handler.is_slash_command("/usage")
        assert handler.is_slash_command("/report")
        assert handler.is_slash_command("/cancel -t 123")
        assert handler.is_slash_command("/trash")
        assert handler.is_slash_command("/clear")
        assert handler.is_slash_command("/chat -t 123")
        
        # Non-commands
        assert not handler.is_slash_command("hello /task")
        assert not handler.is_slash_command("/unknown command")
        assert not handler.is_slash_command("regular message")

    def test_get_command_and_args(self, handler):
        """Test command parsing"""
        cmd, args = handler.get_command_and_args("/task -- hello world")
        assert cmd == "/task"
        assert args == "-- hello world"

        cmd, args = handler.get_command_and_args("/check")
        assert cmd == "/check"
        assert args == ""

        cmd, args = handler.get_command_and_args("/report -t 123")
        assert cmd == "/report"
        assert args == "-t 123"

    def test_task_command_thought(self, handler):
        """Test /task command for thought"""
        response = handler.handle_command("/task -- Explore async patterns")
        
        assert "Task Created" in response
        assert "Thought" in response
        assert "Explore async patterns" in response
        assert "#" in response  # Task ID

    def test_task_command_with_provider(self, handler):
        response = handler.handle_command("/task -r gemini -- Build feature")
        assert "Task Created" in response
        assert "Build feature" in response

    def test_removed_think_command(self, handler):
        """Test /think is removed (no compatibility)"""
        response = handler.handle_command("/think Explore async patterns")

        assert "已移除" in response

    def test_task_command_with_project(self, handler):
        """Test /task command with project flag"""
        response = handler.handle_command("/task -p my-app -- Build feature")

        assert "Task Created" in response
        assert "Serious" in response
        assert "my-app" in response
        assert "Build feature" in response

    def test_task_with_workspace_inplace_skips_worktree(self, handler, temp_dir):
        ws = str(Path(temp_dir) / "repo")
        Path(ws).mkdir(parents=True, exist_ok=True)

        with patch('src.runtime.commands.slash.handler.ensure_task_worktree') as m:
            response = handler.handle_command(f"/task -w {ws} --inplace -- Do something")
            assert "Task Created" in response
            assert "Exec CWD" in response
            assert ws in response
            m.assert_not_called()

    def test_task_with_workspace_requires_git_when_not_inplace(self, handler, temp_dir):
        ws = str(Path(temp_dir) / "notgit")
        Path(ws).mkdir(parents=True, exist_ok=True)

        with patch(
            'src.runtime.commands.slash.handler.ensure_task_worktree',
            side_effect=NotGitRepoError("not a git repo"),
        ):
            response = handler.handle_command(f"/task -w {ws} -- Do something")
            assert "不是 Git 仓库" in response
            assert "-i" in response

    def test_task_with_workspace_worktree_success_sets_exec_cwd(self, handler, temp_dir):
        repo = Path(temp_dir) / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        wt_dir = Path(temp_dir) / "repo_feature_deadbeef"

        fake = WorktreeResult(
            repo_root=repo,
            repo_name="repo",
            task_id="deadbeef",
            branch="feature_deadbeef",
            worktree_dir=wt_dir,
            reused=False,
        )

        with patch('src.runtime.commands.slash.handler.ensure_task_worktree', return_value=fake):
            response = handler.handle_command(f"/task -w {repo} -- Build in worktree")
            assert "Task Created" in response
            assert "Exec CWD" in response
            assert str(wt_dir) in response


    def test_chat_continue_enqueues_same_task(self, handler):
        task_resp = handler.handle_command("/task -- First prompt")
        m = re.search(r"Task ID \| #([0-9a-fA-F]+)", task_resp)
        assert m, task_resp
        task_id = m.group(1)

        resp = handler.handle_command(f"/chat -c -t {task_id} -- follow up")
        assert "已入队" in resp
        assert task_id in resp

    def test_chat_continue_rejects_when_doing(self, handler):
        task_resp = handler.handle_command("/task -- First prompt")
        m = re.search(r"Task ID \| #([0-9a-fA-F]+)", task_resp)
        assert m, task_resp
        task_id = m.group(1)

        # mark as DOING
        handler.task_queue.start_task(task_id)

        resp = handler.handle_command(f"/chat -c -t {task_id} -- follow up")
        assert "执行中" in resp

    def test_chat_history_reads_archived_messages(self, handler):
        task_resp = handler.handle_command("/task -- First prompt")
        m = re.search(r"Task ID \| #([0-9a-fA-F]+)", task_resp)
        assert m, task_resp
        task_id = m.group(1)

        class FakeStorage:
            def get_session_meta(self, session_id):
                class Meta:
                    status = "running"
                    updated_at = 1700000000000

                return Meta()

            def get_session_messages(self, session_id):
                class Msg:
                    def __init__(self, role, content):
                        self.role = role
                        self.content = content

                return [Msg("user", "hello"), Msg("assistant", "world")]

        with patch('src.runtime.commands.slash.handler.get_session_storage', return_value=FakeStorage()):
            resp = handler.handle_command(f"/chat -t {task_id} -n 2")
            assert "会话状态" in resp
            assert "hello" in resp
            assert "world" in resp

    def test_task_command_empty(self, handler):
        """Test /task command with empty description"""
        response = handler.handle_command("/task")
        
        assert "命令解析失败" in response
        assert "Usage" in response

    def test_check_command(self, handler):
        """Test /check command"""
        response = handler.handle_command("/check")
        
        assert "System Status" in response
        assert "Queue Summary" in response
        assert "To Do" in response
        assert "Done" in response

    def test_usage_command(self, handler):
        """Test /usage command"""
        response = handler.handle_command("/usage")
        
        # Should return either usage info or not available message
        assert "Usage" in response or "not available" in response

    def test_report_command_empty(self, handler):
        """Test /report command without args"""
        response = handler.handle_command("/report")
        
        assert "Daily Report" in response or "Summary" in response

    def test_report_command_list(self, handler):
        """Test /report -l command"""
        response = handler.handle_command("/report -l")
        
        assert "Available Reports" in response

    def test_report_command_task_not_found(self, handler):
        """Test /report with non-existent task"""
        response = handler.handle_command("/report -t 99999")
        
        assert "Not Found" in response

    def test_cancel_command_empty(self, handler):
        """Test /cancel command without args"""
        response = handler.handle_command("/cancel")
        
        assert "命令解析失败" in response or "Usage" in response

    def test_cancel_command_task_not_found(self, handler):
        """Test /cancel with non-existent task"""
        response = handler.handle_command("/cancel -t 99999")
        
        assert "Cannot Cancel" in response or "Not Found" in response

    def test_trash_command_list_empty(self, handler):
        """Test /trash list when empty"""
        response = handler.handle_command("/trash")
        
        assert "Trash" in response
        assert "empty" in response.lower()

    def test_trash_command_restore_not_found(self, handler):
        """Test /trash restore with non-existent project"""
        response = handler.handle_command("/trash -p nonexistent")
        
        assert "Not Found" in response or "empty" in response.lower()

    def test_trash_command_empty_when_empty(self, handler):
        """Test /trash -e when already empty"""
        response = handler.handle_command("/trash -e")
        
        assert "empty" in response.lower()

    def test_clear_command(self, handler):
        """Test /clear command"""
        response = handler.handle_command("/clear")
        
        assert "Session Cleared" in response

    def test_unknown_command(self, handler):
        """Test unknown command"""
        response = handler.handle_command("/unknown")
        
        assert "未知命令" in response or "命令解析失败" in response


class TestSlashCommandsConstant:
    """Test SLASH_COMMANDS constant"""

    def test_all_commands_present(self):
        """Verify all expected commands are in SLASH_COMMANDS"""
        expected = ["/task", "/check", "/usage", "/report", "/cancel", "/trash", "/clear", "/help", "/chat"]
        for cmd in expected:
            assert cmd in SLASH_COMMANDS

    def test_commands_are_lowercase(self):
        """Verify all commands are lowercase"""
        for cmd in SLASH_COMMANDS:
            assert cmd == cmd.lower()
            assert cmd.startswith("/")

# -*- coding: utf-8 -*-
"""Slash Command Handler Unit Tests"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch

from src.claude_code_api.services.slash_command_handler import (
    SlashCommandHandler,
    SLASH_COMMANDS,
    slugify_project,
)
from src.claude_code_api.models.task_models import TaskPriority, TaskStatus


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
        """Create handler instance"""
        return SlashCommandHandler("test_agent", mock_config)

    def test_is_slash_command(self, handler):
        """Test slash command detection"""
        assert handler.is_slash_command("/think hello")
        assert handler.is_slash_command("/check")
        assert handler.is_slash_command("/usage")
        assert handler.is_slash_command("/report")
        assert handler.is_slash_command("/cancel 123")
        assert handler.is_slash_command("/trash list")
        assert handler.is_slash_command("/clear")
        
        # Non-commands
        assert not handler.is_slash_command("hello /think")
        assert not handler.is_slash_command("/unknown command")
        assert not handler.is_slash_command("regular message")

    def test_get_command_and_args(self, handler):
        """Test command parsing"""
        cmd, args = handler.get_command_and_args("/think hello world")
        assert cmd == "/think"
        assert args == "hello world"

        cmd, args = handler.get_command_and_args("/check")
        assert cmd == "/check"
        assert args == ""

        cmd, args = handler.get_command_and_args("/report 123")
        assert cmd == "/report"
        assert args == "123"

    def test_think_command_thought(self, handler):
        """Test /think command for thought"""
        response = handler.handle_command("/think Explore async patterns")
        
        assert "Task Created" in response
        assert "Thought" in response
        assert "Explore async patterns" in response
        assert "#" in response  # Task ID

    def test_think_command_with_project(self, handler):
        """Test /think command with project flag"""
        response = handler.handle_command("/think Build feature -p my-app")
        
        assert "Task Created" in response
        assert "Serious" in response
        assert "my-app" in response
        assert "Build feature" in response

    def test_think_command_empty(self, handler):
        """Test /think command with empty description"""
        response = handler.handle_command("/think")
        
        assert "Missing Description" in response
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
        """Test /report --list command"""
        response = handler.handle_command("/report --list")
        
        assert "Available Reports" in response

    def test_report_command_task_not_found(self, handler):
        """Test /report with non-existent task"""
        response = handler.handle_command("/report 99999")
        
        assert "Not Found" in response

    def test_cancel_command_empty(self, handler):
        """Test /cancel command without args"""
        response = handler.handle_command("/cancel")
        
        assert "Missing Identifier" in response
        assert "Usage" in response

    def test_cancel_command_task_not_found(self, handler):
        """Test /cancel with non-existent task"""
        response = handler.handle_command("/cancel 99999")
        
        assert "Cannot Cancel" in response or "Not Found" in response

    def test_trash_command_list_empty(self, handler):
        """Test /trash list when empty"""
        response = handler.handle_command("/trash list")
        
        assert "Trash" in response
        assert "empty" in response.lower()

    def test_trash_command_restore_not_found(self, handler):
        """Test /trash restore with non-existent project"""
        response = handler.handle_command("/trash restore nonexistent")
        
        assert "Not Found" in response or "empty" in response.lower()

    def test_trash_command_empty_when_empty(self, handler):
        """Test /trash empty when already empty"""
        response = handler.handle_command("/trash empty")
        
        assert "empty" in response.lower()

    def test_clear_command(self, handler):
        """Test /clear command"""
        response = handler.handle_command("/clear")
        
        assert "Session Cleared" in response

    def test_unknown_command(self, handler):
        """Test unknown command"""
        response = handler.handle_command("/unknown")
        
        assert "Unknown Command" in response


class TestSlashCommandsConstant:
    """Test SLASH_COMMANDS constant"""

    def test_all_commands_present(self):
        """Verify all expected commands are in SLASH_COMMANDS"""
        expected = ["/think", "/check", "/usage", "/report", "/cancel", "/trash", "/clear"]
        for cmd in expected:
            assert cmd in SLASH_COMMANDS

    def test_commands_are_lowercase(self):
        """Verify all commands are lowercase"""
        for cmd in SLASH_COMMANDS:
            assert cmd == cmd.lower()
            assert cmd.startswith("/")

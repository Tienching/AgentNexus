# -*- coding: utf-8 -*-
"""Integration tests for mission CLI script.

Tests the argparse structure and command dispatch (not actual nexus calls).
"""

import subprocess
import sys
import os

SCRIPT = os.path.join(
    os.path.dirname(__file__), "..",
    "prompts", "skills", "mission", "scripts", "mission.py",
)


class TestMissionCLIParsing:
    """Test CLI argument parsing and help output."""

    def test_help_output(self):
        """Script should show help without errors."""
        result = subprocess.run(
            [sys.executable, SCRIPT, "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "mission" in result.stdout.lower() or "goal" in result.stdout.lower()

    def test_plan_help(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "plan", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "goal" in result.stdout.lower()

    def test_start_help(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "start", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "goal" in result.stdout.lower()

    def test_approve_help(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "approve", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "mission_id" in result.stdout.lower()

    def test_status_help(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "status", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_list_help(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "list", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "include-completed" in result.stdout.lower().replace("_", "-")

    def test_cancel_help(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "cancel", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_pause_help(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "pause", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_resume_help(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "resume", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_log_help(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "log", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "tail" in result.stdout.lower()

    def test_no_command_shows_error(self):
        """Running without a subcommand should fail."""
        result = subprocess.run(
            [sys.executable, SCRIPT],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0

    def test_unknown_command_shows_error(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "nonexistent"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0

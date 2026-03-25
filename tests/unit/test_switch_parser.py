# -*- coding: utf-8 -*-
"""Tests for /switch slash command parser."""

from src.runtime.commands.slash.parser import parse_slash_command


def test_switch_exec_user_short_option():
    parsed = parse_slash_command("/switch -u tswitch")
    assert parsed.cmd == "switch"
    assert parsed.subcmd == "now"
    assert parsed.options["exec-user"] == "tswitch"


def test_switch_exec_user_combined_with_provider_and_model():
    parsed = parse_slash_command("/switch -r codex -u tswitch -m gpt-5")
    assert parsed.options["provider"] == "codex"
    assert parsed.options["exec-user"] == "tswitch"
    assert parsed.options["model"] == "gpt-5"

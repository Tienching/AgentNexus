# -*- coding: utf-8 -*-
"""Tests for /history slash command parser."""
import pytest
from src.runtime.commands.slash.parser import SlashCommandParseError, parse_slash_command


def test_history_default_list():
    r = parse_slash_command("/history")
    assert r.cmd == "history"
    assert r.subcmd == "list"
    assert r.options.get("num") == 10  # default


def test_history_list_with_num():
    r = parse_slash_command("/history -n 20")
    assert r.subcmd == "list"
    assert r.options["num"] == 20


def test_history_list_with_provider():
    r = parse_slash_command("/history -r gemini")
    assert r.subcmd == "list"
    assert r.options["provider"] == "gemini"


def test_history_list_combined():
    r = parse_slash_command("/history -r gemini -n 5")
    assert r.subcmd == "list"
    assert r.options["provider"] == "gemini"
    assert r.options["num"] == 5


def test_history_jsonl_short_option_removed():
    r = parse_slash_command("/history -j abc123")
    assert r.subcmd == "list"
    assert "jsonl" not in r.options


def test_history_session_short_option():
    r = parse_slash_command("/history -s abc123")
    assert r.cmd == "history"
    assert r.subcmd == "jsonl"
    assert r.options["session"] == "abc123"


def test_history_user_filter():
    r = parse_slash_command("/history -u tswitch")
    assert r.subcmd == "list"
    assert r.options["user"] == "tswitch"


def test_history_fetch():
    r = parse_slash_command("/history -f -s abc123")
    assert r.cmd == "history"
    assert r.subcmd == "fetch"
    assert r.options["fetch"] is True
    assert r.options["session"] == "abc123"


def test_history_continue():
    r = parse_slash_command("/history -c -s abc123")
    assert r.cmd == "history"
    assert r.subcmd == "continue"
    assert r.options["continue"] is True
    assert r.options["session"] == "abc123"


def test_history_fetch_continue_require_session_flag():
    with pytest.raises(SlashCommandParseError):
        parse_slash_command("/history -f abc123")

    with pytest.raises(SlashCommandParseError):
        parse_slash_command("/history -c abc123")


def test_history_long_options():
    with pytest.raises(SlashCommandParseError):
        parse_slash_command("/history --jsonl abc-def-123")

    r = parse_slash_command("/history --session abc-def-123")
    assert r.subcmd == "jsonl"
    assert r.options["session"] == "abc-def-123"

    r = parse_slash_command("/history --fetch --session some-uuid")
    assert r.subcmd == "fetch"
    assert r.options["fetch"] is True
    assert r.options["session"] == "some-uuid"

    r = parse_slash_command("/history --continue --session some-uuid")
    assert r.subcmd == "continue"
    assert r.options["continue"] is True
    assert r.options["session"] == "some-uuid"


def test_history_session_with_user_filter():
    r = parse_slash_command("/history -s abc123 -u tswitch")
    assert r.subcmd == "jsonl"
    assert r.options["session"] == "abc123"
    assert r.options["user"] == "tswitch"


def test_history_num_long():
    r = parse_slash_command("/history --num 50")
    assert r.subcmd == "list"
    assert r.options["num"] == 50

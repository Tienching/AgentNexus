# -*- coding: utf-8 -*-
"""Tests for /history slash command parser."""
import pytest
from src.runtime.commands.slash.parser import parse_slash_command


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


def test_history_jsonl():
    r = parse_slash_command("/history -j abc123")
    assert r.cmd == "history"
    assert r.subcmd == "jsonl"
    assert r.options["jsonl"] == "abc123"


def test_history_fetch():
    r = parse_slash_command("/history -f abc123")
    assert r.cmd == "history"
    assert r.subcmd == "fetch"
    assert r.options["fetch"] == "abc123"


def test_history_continue():
    r = parse_slash_command("/history -c abc123")
    assert r.cmd == "history"
    assert r.subcmd == "continue"
    assert r.options["continue"] == "abc123"


def test_history_long_options():
    r = parse_slash_command("/history --jsonl abc-def-123")
    assert r.subcmd == "jsonl"
    assert r.options["jsonl"] == "abc-def-123"

    r = parse_slash_command("/history --fetch some-uuid")
    assert r.subcmd == "fetch"

    r = parse_slash_command("/history --continue some-uuid")
    assert r.subcmd == "continue"


def test_history_num_long():
    r = parse_slash_command("/history --num 50")
    assert r.subcmd == "list"
    assert r.options["num"] == 50

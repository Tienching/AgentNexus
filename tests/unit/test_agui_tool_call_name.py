# -*- coding: utf-8 -*-
"""Tests for AG-UI tool-call naming contract."""

import json

import pytest

from src.runtime.events.agui import ToolCallStartEvent, build_tool_call_name


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected"),
    [
        ("Skill", {"skill": "knot-data"}, "Skill: knot-data"),
        ("Skill", {"skill_name": "knot-data"}, "Skill: knot-data"),
        ("Skill", {"name": "knot-data"}, "Skill: knot-data"),
        ("Skill", {"command": "knot-data"}, "Skill: knot-data"),
        ("Bash", {"description": "收集系统状态", "command": "uname -a"}, "Bash: 收集系统状态"),
        ("web_search", {"query": "配置下发超时"}, "web_search: 配置下发超时"),
        ("Read", '{"file_path": "/tmp/a.py"}', "Read: /tmp/a.py"),
        ("TaskOutput", {"task_id": "agent-123", "block": True}, "TaskOutput: 等待专家返回结果"),
        ("Read", "not-json", "Read"),
    ],
)
def test_build_tool_call_name(tool_name, arguments, expected):
    assert build_tool_call_name(tool_name, arguments) == expected


def test_display_name_equal_to_raw_does_not_block_argument_fallback():
    assert (
        build_tool_call_name("Skill", {"skill": "knot-data"}, display_name="Skill")
        == "Skill: knot-data"
    )


def test_tool_call_start_event_emits_standard_fields_only():
    payload = json.loads(
        ToolCallStartEvent(
            toolCallId="tool-1",
            toolCallName="Skill: knot-data",
            parentMessageId="msg-1",
        ).to_sse().split("data: ", 1)[1]
    )

    assert payload == {
        "type": "TOOL_CALL_START",
        "toolCallId": "tool-1",
        "toolCallName": "Skill: knot-data",
        "parentMessageId": "msg-1",
    }

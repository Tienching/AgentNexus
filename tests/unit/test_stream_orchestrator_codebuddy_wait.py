# -*- coding: utf-8 -*-
"""Regression tests for CodeBuddy analyst wait-state recovery."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.runtime.streaming.orchestrator import StreamOrchestrator


def sse_payload(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class FakeExecutor:
    def __init__(self, turns: list[list[dict]]):
        self.turns = turns
        self.calls = 0
        self.contents: list[str] = []

    async def execute(self, request_model, *, exec_user: str, output_format: str):
        self.calls += 1
        self.contents.append(request_model.content)
        for event in self.turns[self.calls - 1]:
            yield json.dumps(event, ensure_ascii=False)


class FakeAdapter:
    def __init__(self):
        self.message_id = "msg-1"

    def create_start_event(self):
        return sse_payload({"type": "RUN_STARTED", "threadId": "thread-1", "runId": "run-1"})

    def create_end_event(self):
        return sse_payload({"type": "RUN_FINISHED", "threadId": "thread-1", "runId": "run-1"})

    def create_error_event(self, message: str):
        return sse_payload({"type": "RUN_ERROR", "message": message})

    def convert(self, event: dict):
        if event.get("type") != "text":
            return None
        return sse_payload(
            {
                "type": "TEXT_MESSAGE_CONTENT",
                "messageId": self.message_id,
                "delta": event.get("delta", ""),
            }
        )


class FakeArchiver:
    async def on_run_started(self, initial_messages=None):
        pass

    async def on_run_finished(self):
        pass

    async def on_run_error(self, error: str):
        pass

    async def archive_event(self, payload: dict):
        pass


@pytest.mark.asyncio
async def test_codebuddy_wait_state_auto_continues_before_run_finished():
    orchestrator = StreamOrchestrator()
    request = SimpleNamespace(
        content="诊断 Kernel panic",
        content_parts=[{"type": "text", "content": "诊断 Kernel panic"}],
        image_paths=[],
        file_paths=[],
        session_cleared=False,
    )
    executor = FakeExecutor(
        [
            [
                {
                    "type": "function_call_result",
                    "name": "Agent",
                    "content": "Spawned successfully. task_id: agent-68335b40",
                    "session_id": "codebuddy-session-1",
                },
                {"type": "text", "delta": "Analyst 正在后台运行，等待其通过 SendMessage 返回分析结果。"},
            ],
            [
                {
                    "type": "text",
                    "delta": "# 故障诊断报告\n## 诊断结论\n**根本原因:** PCIe AER fatal error",
                }
            ],
        ]
    )

    chunks = [
        chunk
        async for chunk in orchestrator.stream_agui(
            executor=executor,
            request_model=request,
            adapter=FakeAdapter(),
            archiver=FakeArchiver(),
            initial_messages=[],
            exec_user="tencent",
            session_id="runtime-session-1",
        )
    ]

    joined = "".join(chunks)
    assert executor.calls == 2
    assert "Analyst 正在后台运行" in joined
    assert "# 故障诊断报告" in joined
    assert joined.rfind("RUN_FINISHED") > joined.rfind("# 故障诊断报告")
    assert request.cli_session_id == "codebuddy-session-1"
    assert "agent-68335b40" in executor.contents[1]
    assert "TaskOutput(block=true, timeout=600)" in executor.contents[1]
    assert request.content_parts == []


@pytest.mark.asyncio
async def test_codebuddy_final_report_does_not_auto_continue():
    orchestrator = StreamOrchestrator()
    request = SimpleNamespace(content="诊断端口", content_parts=[], image_paths=[], file_paths=[])
    executor = FakeExecutor(
        [
            [
                {
                    "type": "function_call_result",
                    "name": "Agent",
                    "content": "Spawned successfully. task_id: agent-abc123",
                },
                {"type": "text", "delta": "# 故障诊断报告\n## 诊断结论\n**根本原因:** 光模块异常"},
            ]
        ]
    )

    chunks = [
        chunk
        async for chunk in orchestrator.stream_agui(
            executor=executor,
            request_model=request,
            adapter=FakeAdapter(),
            archiver=FakeArchiver(),
            initial_messages=[],
            exec_user="tencent",
        )
    ]

    assert executor.calls == 1
    assert "# 故障诊断报告" in "".join(chunks)

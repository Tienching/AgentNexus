# -*- coding: utf-8 -*-
"""Hermes ACP session/update notification -> AG-UI SSE adapter.

Maps ACP ``sessionUpdate`` types to AG-UI events:

  ACP sessionUpdate          AG-UI event(s)
  ─────────────────────────  ──────────────────────────────────────
  agent_message_chunk        TextMessageStart(once) / Content / End
  agent_thought_chunk        CustomEvent(name=reasoning)  (no native thinking)
  tool_call                  ToolCallStart + ToolCallArgs
  tool_call_update (result)  ToolCallResult + ToolCallEnd
  usage_update / *_commands  ignored
  terminal marker            RunFinished
  error                      RunError

The adapter is stateful: it tracks the current message id and active tool calls
per session so Start/End pair up correctly.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, List, Optional

from src.runtime.adapters.base import AdapterState, BaseAdapter
from src.protocols.base import ProtocolType
from src.runtime.events.agui.events import (
    CustomEvent,
    RunFinishedEvent,
    RunStartedEvent,
    RunErrorEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
    build_tool_call_name,
)

logger = logging.getLogger(__name__)


def _gen_id(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _part_text(part: Any) -> str:
    """Extract text from an ACP content part ({type:text,text:...}) or raw str."""
    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        if part.get("type") == "text":
            return part.get("text", "")
        # file/image parts: render a placeholder
        return json.dumps(part, ensure_ascii=False)[:200]
    return str(part)


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, (list, tuple)):
        return "".join(_part_text(p) for p in content)
    return _part_text(content)


class HermesACPAdapterState(AdapterState):
    """Tracks current assistant message + active tool calls."""

    def __init__(self, thread_id: str = "", run_id: str = ""):
        super().__init__(thread_id=thread_id, run_id=run_id)
        self.assistant_message_id: Optional[str] = None
        self.assistant_started = False
        self.assistant_text_snapshot = ""
        self.assistant_last_chunk = ""
        self.assistant_snapshot_mode = False
        # tool_call_id -> bool(ended)
        self.active_tools: dict = {}


class HermesACPAGUIAdapter(BaseAdapter):
    """Convert hermes ACP session/update events into AG-UI SSE."""

    def __init__(self):
        self.state = HermesACPAdapterState()
        self._run_finished = False

    def init_state(self, thread_id: str, run_id: str) -> None:
        self.state = HermesACPAdapterState(thread_id=thread_id, run_id=run_id)
        self._run_finished = False

    # ── BaseAdapter abstract surface ──────────────────────────────────
    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.AGUI

    def format_sse(self, data: str) -> str:
        return f"data: {data}\n\n"

    def create_start_event(self) -> str:
        return RunStartedEvent(threadId=self.state.thread_id, runId=self.state.run_id).to_sse()

    def create_end_event(self, is_error: bool = False, error_msg: str = "") -> str:
        if self._run_finished:
            # Already finished — only flush a pending assistant end if needed.
            return "".join(self._finish_assistant())
        self._run_finished = True
        return RunFinishedEvent(threadId=self.state.thread_id, runId=self.state.run_id).to_sse()

    def create_error_event(self, error_msg: str) -> str:
        return RunErrorEvent(
            threadId=self.state.thread_id, runId=self.state.run_id, message=error_msg
        ).to_sse()

    # ── helpers ───────────────────────────────────────────────────────
    def _ensure_assistant_start(self) -> List[str]:
        if not self.state.assistant_message_id:
            self.state.assistant_message_id = _gen_id("msg")
        if not self.state.assistant_started:
            self.state.assistant_started = True
            return [TextMessageStartEvent(messageId=self.state.assistant_message_id).to_sse()]
        return []

    def _finish_assistant(self) -> List[str]:
        out: List[str] = []
        if self.state.assistant_started and self.state.assistant_message_id:
            out.append(TextMessageEndEvent(messageId=self.state.assistant_message_id).to_sse())
            self.state.assistant_started = False
        self.state.assistant_text_snapshot = ""
        self.state.assistant_last_chunk = ""
        self.state.assistant_snapshot_mode = False
        return out

    def _normalize_agent_message_delta(self, text: str) -> str:
        """Convert Hermes agent chunks into AG-UI deltas.

        Hermes ACP builds have been observed to emit either true deltas or
        cumulative text snapshots for ``agent_message_chunk``. AG-UI expects
        deltas, so strip the already-seen prefix when the chunk is a snapshot.
        """
        if not text:
            return ""

        previous = self.state.assistant_text_snapshot
        last_chunk = self.state.assistant_last_chunk

        if previous and text.startswith(previous) and len(text) > len(previous):
            self.state.assistant_snapshot_mode = True
            self.state.assistant_text_snapshot = text
            self.state.assistant_last_chunk = text
            return text[len(previous):]

        if self.state.assistant_snapshot_mode and text == previous:
            self.state.assistant_last_chunk = text
            return ""

        if text == last_chunk and len(text) >= 8:
            return ""

        self.state.assistant_text_snapshot = previous + text
        self.state.assistant_last_chunk = text
        return text

    # ── main convert entry ────────────────────────────────────────────
    def convert(self, event: dict) -> Optional[str]:
        """Convert one event dict to an SSE string (may emit multiple joined)."""
        results: List[str] = []
        # NOTE: RUN_STARTED is emitted by the orchestrator (create_start_event);
        # this adapter only reacts to ACP events, so we do NOT auto-emit it here
        # (would otherwise duplicate it in the SSE stream).

        # Terminal marker emitted by the executor
        if event.get("__acp_terminal__"):
            results.extend(self._finish_assistant())
            results.append(self.create_end_event())
            return "".join(results)

        # Error event (executor-level)
        if event.get("type") == "error":
            results.append(
                RunErrorEvent(
                    threadId=self.state.thread_id,
                    runId=self.state.run_id,
                    message=str(event.get("message", "unknown error")),
                ).to_sse()
            )
            self._run_finished = True
            return "".join(results)

        # ACP session/update notification
        if event.get("method") == "session/update":
            params = event.get("params", {}) or {}
            update = params.get("update", {}) or {}
            su = update.get("sessionUpdate") or update.get("session_update")
            results.extend(self._handle_update(su, update))

        if results:
            return "".join(results)
        return None

    def _handle_update(self, su: Optional[str], update: dict) -> List[str]:
        out: List[str] = []
        if su == "agent_message_chunk":
            text = _content_text(update.get("content"))
            delta = self._normalize_agent_message_delta(text)
            if delta:
                out.extend(self._ensure_assistant_start())
                out.append(TextMessageContentEvent(messageId=self.state.assistant_message_id, delta=delta).to_sse())
        elif su == "agent_thought_chunk":
            text = _content_text(update.get("content"))
            if text:
                out.append(
                    CustomEvent(
                        threadId=self.state.thread_id,
                        runId=self.state.run_id,
                        name="reasoning",
                        value=text,
                    ).to_sse()
                )
        elif su == "tool_call":
            out.extend(self._handle_tool_call(update))
        elif su == "tool_call_update":
            out.extend(self._handle_tool_call_update(update))
        # usage_update / available_commands_update / current_mode_update / etc. → ignore
        return out

    def _handle_tool_call(self, update: dict) -> List[str]:
        out: List[str] = []
        tool_id = update.get("toolCallId") or update.get("tool_call_id") or _gen_id("tool")
        title = update.get("title") or update.get("name") or "tool"
        # args may arrive as content list or raw
        args_text = _content_text(update.get("content")) or update.get("input")
        display = build_tool_call_name(title, args_text if isinstance(args_text, (dict, list)) else None)
        self.state.active_tools[tool_id] = False
        out.append(
            ToolCallStartEvent(
                toolCallId=tool_id,
                toolCallName=display or title,
                parentMessageId=self.state.assistant_message_id,
            ).to_sse()
        )
        if args_text:
            delta = json.dumps(args_text, ensure_ascii=False) if not isinstance(args_text, str) else args_text
            out.append(ToolCallArgsEvent(toolCallId=tool_id, delta=delta).to_sse())
        return out

    def _handle_tool_call_update(self, update: dict) -> List[str]:
        out: List[str] = []
        tool_id = update.get("toolCallId") or update.get("tool_call_id")
        if not tool_id:
            return out
        result_text = _content_text(update.get("content"))
        status = update.get("status")
        # Result + End always paired (codebuddy/claude convention)
        if result_text or status in ("completed", "failed", "in_progress"):
            if result_text:
                out.append(
                    ToolCallResultEvent(
                        messageId=self.state.assistant_message_id or _gen_id("msg"),
                        toolCallId=tool_id,
                        content=result_text,
                    ).to_sse()
                )
            if status in ("completed", "failed"):
                out.append(ToolCallEndEvent(toolCallId=tool_id, result=result_text or "").to_sse())
                self.state.active_tools.pop(tool_id, None)
        return out

    def parse_json_line(self, line: str):
        try:
            return json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None

    def process_stream(self, hermes_stream, output_format: str = "raw"):
        """Async generator: start → convert each line → end."""

        async def _gen():
            try:
                yield self.create_start_event()
                async for line in hermes_stream:
                    parsed = self.parse_json_line(line) if isinstance(line, str) else line
                    if parsed is None:
                        continue
                    sse = self.convert(parsed)
                    if sse:
                        yield sse
                if not self._run_finished:
                    yield self.create_end_event()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("hermes adapter stream error")
                yield self.create_error_event(str(exc))

        return _gen()

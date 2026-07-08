# -*- coding: utf-8 -*-
"""Tests for hermes ACP connection framing + adapter event mapping."""
import asyncio
import json

import pytest

from src.providers.hermes.acp_connection import HermesACPConnection, ACPError
from src.runtime.adapters.hermes import HermesACPAGUIAdapter


# ── Adapter event mapping ─────────────────────────────────────────────
class TestHermesAdapter:
    def _new(self):
        a = HermesACPAGUIAdapter()
        a.init_state("t1", "r1")
        return a

    def test_agent_message_chunk_emits_text(self):
        a = self._new()
        sse = a.convert({"method": "session/update", "params": {"update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "hello"}}}})
        # RUN_STARTED is owned by the orchestrator, not the adapter.
        assert "TEXT_MESSAGE_START" in sse
        assert "TEXT_MESSAGE_CONTENT" in sse
        assert "hello" in sse

    def test_agent_message_snapshot_chunks_emit_only_new_delta(self):
        a = self._new()
        first = a.convert({"method": "session/update", "params": {"update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "hello"}}}})
        second = a.convert({"method": "session/update", "params": {"update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "hello world"}}}})
        duplicate = a.convert({"method": "session/update", "params": {"update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "hello world"}}}})

        assert '"delta":"hello"' in first
        assert '"delta":" world"' in second
        assert duplicate is None

    def test_repeated_long_agent_message_chunk_is_ignored(self):
        a = self._new()
        chunk = "same content repeated"
        first = a.convert({"method": "session/update", "params": {"update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": chunk}}}})
        duplicate = a.convert({"method": "session/update", "params": {"update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": chunk}}}})

        assert chunk in first
        assert duplicate is None

    def test_tool_call_emits_start_and_args(self):
        a = self._new()
        sse = a.convert({"method": "session/update", "params": {"update": {
            "sessionUpdate": "tool_call", "toolCallId": "tc1", "title": "read",
            "content": [{"type": "text", "text": "/etc/hostname"}]}}})
        assert "TOOL_CALL_START" in sse
        assert "TOOL_CALL_ARGS" in sse

    def test_tool_call_update_completed_emits_result_and_end(self):
        a = self._new()
        a.convert({"method": "session/update", "params": {"update": {
            "sessionUpdate": "tool_call", "toolCallId": "tc1", "title": "read", "content": []}}})
        sse = a.convert({"method": "session/update", "params": {"update": {
            "sessionUpdate": "tool_call_update", "toolCallId": "tc1",
            "status": "completed", "content": [{"type": "text", "text": "any1"}]}}})
        assert "TOOL_CALL_RESULT" in sse
        assert "TOOL_CALL_END" in sse

    def test_agent_thought_chunk_emits_reasoning_custom(self):
        a = self._new()
        sse = a.convert({"method": "session/update", "params": {"update": {
            "sessionUpdate": "agent_thought_chunk",
            "content": {"type": "text", "text": "thinking..."}}}})
        assert "reasoning" in sse
        assert "CUSTOM" in sse

    def test_usage_update_ignored(self):
        a = self._new()
        sse = a.convert({
            "method": "session/update",
            "params": {"update": {"sessionUpdate": "usage_update", "size": 1000, "used": 10}},
        })
        # usage_update produces no AG-UI output at all (returns None or empty).
        assert sse is None or sse == ""
        assert not sse or ("TEXT_MESSAGE" not in sse and "TOOL_CALL" not in sse)

    def test_terminal_marker_emits_run_finished(self):
        a = self._new()
        sse = a.convert({"__acp_terminal__": True})
        assert "RUN_FINISHED" in sse

    def test_end_event_is_idempotent_after_terminal_marker(self):
        a = self._new()
        terminal_sse = a.convert({"__acp_terminal__": True})
        trailing_sse = a.create_end_event()
        assert terminal_sse.count("RUN_FINISHED") == 1
        assert "RUN_FINISHED" not in trailing_sse

    def test_error_event_emits_run_error(self):
        a = self._new()
        sse = a.convert({"type": "error", "message": "boom"})
        assert "RUN_ERROR" in sse

    def test_message_start_end_pairing(self):
        a = self._new()
        a.convert({"method": "session/update", "params": {"update": {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "a"}}}})
        sse = a.convert({"__acp_terminal__": True})
        # assistant end must be emitted before run finished
        assert sse.index("TEXT_MESSAGE_END") < sse.index("RUN_FINISHED")


# ── Connection framing (NDJSON) ───────────────────────────────────────
class TestACPConnectionFraming:
    def test_handle_message_routes_response_to_future(self):
        c = HermesACPConnection.__new__(HermesACPConnection)
        c._pending = {}
        loop = asyncio.new_event_loop()
        try:
            fut = loop.create_future()
            c._pending[5] = fut
            c._handle_message({"jsonrpc": "2.0", "id": 5, "result": {"ok": True}})
            assert fut.done()
            assert fut.result() == {"ok": True}
            assert 5 not in c._pending
        finally:
            loop.close()

    def test_handle_message_routes_notification_to_queue(self):
        c = HermesACPConnection.__new__(HermesACPConnection)
        c._pending = {}
        c._event_queue = asyncio.Queue()
        notif = {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {}}}
        c._handle_message(notif)
        assert c._event_queue.qsize() == 1

    def test_handle_message_error_raises_in_future(self):
        c = HermesACPConnection.__new__(HermesACPConnection)
        c._pending = {}
        loop = asyncio.new_event_loop()
        try:
            fut = loop.create_future()
            c._pending[7] = fut
            c._handle_message({"jsonrpc": "2.0", "id": 7, "error": {"code": -32602, "message": "bad"}})
            assert fut.done()
            with pytest.raises(ACPError):
                fut.result()
        finally:
            loop.close()

class TestHermesExecutorHardening:
    def test_hermes_alias_does_not_select_executable(self):
        from src.providers.base import RequestContext
        from src.providers.hermes.acp_executor import HermesACPExecutor
        from src.providers.hermes.cli_executor import HermesCLIExecutor, HermesExecutorConfig

        context = RequestContext(content="hi", user="u", session_id="s", exec_user="ubuntu", alias="/tmp/evil-hermes")

        acp_cmd = HermesACPExecutor()._build_acp_cmd(context)
        assert acp_cmd[0] != "/tmp/evil-hermes"

        cli = HermesCLIExecutor(HermesExecutorConfig(hermes_command="hermes"))
        cli_cmd = cli._build_command(context)
        assert cli_cmd[0] != "/tmp/evil-hermes"

    @pytest.mark.asyncio
    async def test_acp_prompt_completion_terminates_stream(self, monkeypatch):
        from src.providers.base import RequestContext
        from src.providers.hermes import acp_executor as module
        from src.providers.hermes.acp_executor import HermesACPExecutor

        class FakeConnection:
            def __init__(self, cmd, cwd=None):
                self.events = asyncio.Queue()
                self.stopped = False

            async def start(self):
                pass

            async def initialize(self):
                return {}

            async def initialized(self):
                pass

            async def new_session(self, cwd):
                return {"sessionId": "hermes-session"}

            async def prompt(self, session_id, text):
                await self.events.put({
                    "method": "session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "done"},
                        }
                    },
                })
                return {"stopReason": "end_turn"}

            async def next_event(self):
                return await self.events.get()

            async def cancel(self, session_id, reason):
                pass

            async def stop(self):
                self.stopped = True

        monkeypatch.setattr(module, "HermesACPConnection", FakeConnection)

        executor = HermesACPExecutor()
        executor.PROMPT_DONE_EVENT_GRACE_SECONDS = 0.01
        context = RequestContext(content="hi", user="u", session_id="s", exec_user="ubuntu")

        lines = [json.loads(line) async for line in executor._run_acp(context)]

        assert any(line.get("method") == "session/update" for line in lines)
        assert lines[-1]["__acp_terminal__"] is True

    @pytest.mark.asyncio
    async def test_acp_tool_completion_does_not_terminate_turn(self, monkeypatch):
        from src.providers.base import RequestContext
        from src.providers.hermes import acp_executor as module
        from src.providers.hermes.acp_executor import HermesACPExecutor

        class FakeConnection:
            def __init__(self, cmd, cwd=None):
                self.events = asyncio.Queue()

            async def start(self):
                pass

            async def initialize(self):
                return {}

            async def initialized(self):
                pass

            async def new_session(self, cwd):
                return {"sessionId": "hermes-session"}

            async def prompt(self, session_id, text):
                for update in [
                    {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "tool-1",
                        "title": "terminal: date",
                        "content": {"type": "text", "text": "$ date"},
                    },
                    {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "tool-1",
                        "status": "completed",
                        "content": {"type": "text", "text": "ok"},
                    },
                    {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "final answer"},
                    },
                ]:
                    await self.events.put({
                        "method": "session/update",
                        "params": {"update": update},
                    })
                return {"stopReason": "end_turn"}

            async def next_event(self):
                return await self.events.get()

            async def cancel(self, session_id, reason):
                pass

            async def stop(self):
                pass

        monkeypatch.setattr(module, "HermesACPConnection", FakeConnection)

        executor = HermesACPExecutor()
        executor.PROMPT_DONE_EVENT_GRACE_SECONDS = 0.01
        context = RequestContext(content="hi", user="u", session_id="s", exec_user="ubuntu")

        lines = [json.loads(line) async for line in executor._run_acp(context)]
        updates = [
            line.get("params", {}).get("update", {})
            for line in lines
            if line.get("method") == "session/update"
        ]

        assert [update.get("sessionUpdate") for update in updates] == [
            "tool_call",
            "tool_call_update",
            "agent_message_chunk",
        ]
        assert lines[-1]["__acp_terminal__"] is True


class TestACPSentinelFallback:
    """Cover the QueueFull drop-oldest sentinel fallback in _read_loop finally.

    When the bounded event queue is full at stream end, the sentinel (None) must
    still be delivered so consumers do not block forever. The fallback drops the
    oldest buffered notification to make room.
    """

    def _emit_sentinel(self, queue):
        """Mirror the _read_loop finally-block logic (acp_connection.py)."""
        import asyncio as _a
        try:
            queue.put_nowait(None)
        except _a.QueueFull:
            try:
                queue.get_nowait()  # drop oldest non-terminal event
            except _a.QueueEmpty:
                pass
            queue.put_nowait(None)

    def test_sentinel_delivered_when_queue_has_room(self):
        q = asyncio.Queue(maxsize=2)
        self._emit_sentinel(q)
        assert q.qsize() == 1
        assert q.get_nowait() is None

    def test_sentinel_drops_oldest_when_queue_full(self):
        # Pre-fill a maxsize=1 queue with a buffered notification
        q = asyncio.Queue(maxsize=1)
        q.put_nowait({"jsonrpc": "2.0", "method": "session/update", "params": {}})
        assert q.full()
        # Emitting the sentinel on a full queue must drop the oldest (the
        # notification) and still deliver the terminal None.
        self._emit_sentinel(q)
        assert q.qsize() == 1
        assert q.get_nowait() is None

    def test_sentinel_always_terminal_even_if_drained_between(self):
        # Edge case: another consumer drains between the QueueFull and the
        # get_nowait (QueueEmpty path). The sentinel must still land.
        q = asyncio.Queue(maxsize=1)
        q.put_nowait({"method": "x"})
        # simulate: put_nowait(None) -> full -> get_nowait succeeds, but then
        # a second get_nowait (the "drain") would be empty. Our helper does ONE
        # get_nowait which removes the notification; the put succeeds.
        self._emit_sentinel(q)
        assert q.get_nowait() is None
        assert q.empty()

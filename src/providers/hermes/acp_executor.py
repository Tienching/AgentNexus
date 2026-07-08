# -*- coding: utf-8 -*-
"""Hermes Agent CLI executor using the ACP (Agent Client Protocol) transport.

Replaces the oneshot text executor: instead of ``hermes -z`` + plain stdout, it
talks to ``hermes acp`` over NDJSON JSON-RPC, preserving tool calls, thoughts
and streaming agent messages.

Contract (orchestrator): ``execute()`` is an async generator yielding one JSON
string per line. Each line is an ACP ``session/update`` notification (dict),
handed to the Hermes ACP adapter for AG-UI conversion. A terminal marker line
``{"__acp_terminal__": true}`` signals the stream end.

NOTE: This module must NOT depend on server-layer packages.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, List, Optional

from src.providers.base import BaseExecutor, ExecutorConfig, RequestContext
from src.providers.hermes.acp_connection import ACPError, HermesACPConnection
from src.providers.hermes.cli_executor import _resolve_hermes_binary
from src.providers._error_sanitize import safe_error_message


def safe_err(detail: str) -> str:
    """Best-effort generic message; full detail already logged."""
    return safe_error_message(detail)

logger = logging.getLogger(__name__)


class HermesACPExecutor(BaseExecutor):
    """Runs hermes via ACP and yields session/update notifications."""

    PROMPT_DONE_EVENT_GRACE_SECONDS = 0.25

    def __init__(self, config: Optional[ExecutorConfig] = None):
        if config is None:
            config = ExecutorConfig()
        super().__init__(config)

    async def execute(
        self,
        request: Any,
        exec_user: str = "default",
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        if isinstance(request, RequestContext):
            context = request
        else:
            context = RequestContext.from_request_model(request, exec_user)
        async for line in self._run_acp(context):
            yield line

    def _build_command(self, context: RequestContext) -> List[str]:
        """Satisfy BaseExecutor abstract contract; ACP uses its own subprocess."""
        return self._build_acp_cmd(context)

    def _build_acp_cmd(self, context: RequestContext) -> List[str]:
        # alias may be user-influenced; only honor a bare command name (no path
        # separator) to avoid it being used as an arbitrary executable path.
        raw_alias = (getattr(context, "alias", None) or "").strip()
        configured = raw_alias if (raw_alias and "/" not in raw_alias) else "hermes"
        cli_command = _resolve_hermes_binary(configured)
        return [cli_command, "acp"]

    async def _run_acp(self, context: RequestContext) -> AsyncGenerator[str, None]:
        cmd = self._build_acp_cmd(context)
        exec_dir = self.resolve_exec_dir(context)
        # wrap for user switch (su + shlex); stdin/stdout/stderr pass through bash -c transparently
        final_cmd = self.wrap_command_for_user(cmd, exec_dir, context.exec_user)

        logger.info("hermes acp execute: %s", final_cmd[0] if final_cmd else "<?>")

        # The connection manages its own subprocess (needs bidirectional stdio).
        # wrap_command_for_user yields ["bash","-c","cd ... && hermes acp"] OR
        # ["su","-",user,"-c","cd ... && hermes acp"]; we feed that to the connection.
        # wrap_command_for_user already embeds "cd exec_dir &&"; no separate cwd to avoid double-switch.
        conn = HermesACPConnection(final_cmd)
        session_id: Optional[str] = None
        try:
            await conn.start()
            await conn.initialize()
            await conn.initialized()

            sess = await conn.new_session(cwd=str(exec_dir))
            session_id = sess.get("sessionId") if isinstance(sess, dict) else None
            if not session_id:
                yield json.dumps({"type": "error", "message": "hermes ACP: no session"})
                return

            # Issue prompt (does not block on the response; events stream in parallel).
            prompt_task = asyncio.create_task(conn.prompt(session_id, context.content or ""))

            # Stream session/update notifications to the adapter. Hermes keeps
            # the ACP process alive after a prompt has reached end_turn, so
            # prompt completion must also terminate this request's SSE stream.
            while True:
                ev, prompt_completed = await self._next_event_or_prompt_done(conn, prompt_task)
                if ev is None:
                    break
                method = ev.get("method", "")
                if method != "session/update":
                    # other notifications (e.g. session/cancelled) — pass through rarely
                    if prompt_completed:
                        break
                    continue
                yield json.dumps(ev, ensure_ascii=False)

                # Detect terminal task state inside the update payload.
                update = ev.get("params", {}).get("update", {})
                session_update = str(update.get("sessionUpdate") or update.get("session_update") or "").lower()
                status = str(update.get("status") or update.get("state") or "").lower()
                if (
                    session_update not in {"tool_call", "tool_call_update"}
                    and status in {"completed", "failed", "canceled", "cancelled", "error"}
                ):
                    break

            # Ensure the prompt future is settled (it resolves at end_turn).
            try:
                if prompt_task.done():
                    prompt_task.result()
                else:
                    await asyncio.wait_for(prompt_task, timeout=5.0)
            except Exception as exc:
                logger.debug("hermes prompt settle: %s", exc)

            yield json.dumps({"__acp_terminal__": True, "sessionId": session_id})
        except ACPError as exc:
            logger.warning("hermes acp error: %s", exc)
            yield json.dumps({"type": "error", "message": safe_err(str(exc))})
        except asyncio.CancelledError:
            if session_id:
                await conn.cancel(session_id, "client disconnected")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("hermes acp unexpected error")
            yield json.dumps({"type": "error", "message": safe_err(str(exc))})
        finally:
            await conn.stop()

    async def _next_event_or_prompt_done(
        self,
        conn: HermesACPConnection,
        prompt_task: asyncio.Task,
    ) -> tuple[Optional[dict], bool]:
        """Wait for the next ACP event, but stop once the prompt is complete.

        ``session/prompt`` resolves at end_turn, while the ACP subprocess may
        remain open for future prompts. Without this race the SSE stream can
        hang after the final assistant text has already been delivered.
        """
        event_task = asyncio.create_task(conn.next_event())
        done, _pending = await asyncio.wait(
            {event_task, prompt_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if event_task in done:
            return event_task.result(), False

        try:
            event = await asyncio.wait_for(
                event_task,
                timeout=self.PROMPT_DONE_EVENT_GRACE_SECONDS,
            )
            return event, True
        except asyncio.TimeoutError:
            event_task.cancel()
            try:
                await event_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            return None, True


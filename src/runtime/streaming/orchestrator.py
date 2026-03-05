# -*- coding: utf-8 -*-
"""Streaming orchestrator (API-agnostic)

This module holds the core streaming orchestration logic, but intentionally does not
import FastAPI, adapters, or storage implementations.

The API layer (e.g. `claude_code_api`) is responsible for:
- parsing HTTP requests into request models
- choosing provider/adapters/executors
- constructing an archiver (optional)
- wrapping the async generator into `StreamingResponse`

The orchestrator is responsible for:
- iterating executor output
- converting provider raw events to protocol SSE
- best-effort archiving of converted AG-UI events
- graceful error finalization
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Iterable, Optional

logger = logging.getLogger(__name__)


class StreamOrchestrator:
    def __init__(self) -> None:
        self._pending_archive_tasks: list[asyncio.Task] = []

    async def _flush_pending_archives(self) -> None:
        """Wait for all pending archive tasks to complete before finalizing."""
        if not self._pending_archive_tasks:
            return
        tasks = self._pending_archive_tasks
        self._pending_archive_tasks = []
        results = await asyncio.gather(*tasks, return_exceptions=True)
        failed = sum(1 for r in results if isinstance(r, Exception))
        if failed:
            logger.warning(f"[StreamOrchestrator] {failed}/{len(results)} archive tasks failed")

    async def stream_agui(
        self,
        *,
        executor: Any,
        request_model: Any,
        adapter: Any,
        archiver: Any,
        initial_messages: list[dict[str, Any]],
        exec_user: str,
        handoff_pending_target: Optional[str] = None,
        handoff_pending_model: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Generate AG-UI SSE stream.

        Contracts expected:
        - executor.execute(request_model, exec_user=..., output_format="raw") -> AsyncIterator[str]
        - adapter.convert(dict) -> Optional[str] (SSE chunks)
        - adapter.create_start_event()/create_end_event()/create_error_event(str) -> str
        - archiver.on_run_started(list)/on_run_finished()/on_run_error(str)
        - archiver.archive_event(dict)
        """

        event_count = 0
        summary_text_parts = [] if handoff_pending_target else None
        try:
            await archiver.on_run_started(initial_messages)

            start_event = adapter.create_start_event()
            if start_event:
                event_count += self._count_sse_events(start_event)
                yield start_event

            async for line in executor.execute(request_model, exec_user=exec_user, output_format="raw"):
                if not line or not str(line).strip():
                    continue

                try:
                    event_data = json.loads(line)
                except Exception:
                    continue

                try:
                    converted = adapter.convert(event_data)
                except Exception:
                    continue

                if converted:
                    # Archive converted AG-UI events asynchronously (non-blocking)
                    self._schedule_archive_converted(converted, archiver)
                    # Collect text from AG-UI events for switch summary
                    if summary_text_parts is not None:
                        for payload in self._iter_agui_payloads(converted):
                            if payload.get("type") == "TEXT_MESSAGE_CONTENT":
                                summary_text_parts.append(payload.get("delta", ""))
                    event_count += self._count_sse_events(converted)
                    yield converted

            # Store agent-generated summary and append notification before end event
            if handoff_pending_target and summary_text_parts and session_id:
                summary_text = "".join(summary_text_parts).strip()
                if summary_text:
                    try:
                        from ..stores.session_storage import get_session_storage
                        storage = get_session_storage()
                        storage.set_handoff_context(
                            session_id,
                            summary_text,
                            handoff_pending_target,
                            model=handoff_pending_model,
                        )
                        logger.info(
                            f"Stored switch summary ({len(summary_text)} chars) for next switch",
                            extra={"session_id": session_id, "target": handoff_pending_target},
                        )
                        # Append a notification message in the SSE stream
                        summary_preview = summary_text[:200] + "..." if len(summary_text) > 200 else summary_text
                        notify_text = (
                            f"\n\n---\n"
                            f"✅ **Agent 切换准备完成**\n\n"
                            f"**目标 Agent**: `{handoff_pending_target}`\n"
                            f"**上下文摘要** ({len(summary_text)} 字符):\n"
                            f"> {summary_preview}\n\n"
                            f"请发送下一条消息，将自动切换到 `{handoff_pending_target}` 并携带以上摘要。"
                        )
                        notify_sse = self._build_text_content_sse(adapter, notify_text)
                        if notify_sse:
                            yield notify_sse
                    except Exception as e:
                        logger.error(f"Failed to store switch summary: {e}")

            end_event = adapter.create_end_event()
            if end_event:
                event_count += self._count_sse_events(end_event)
                yield end_event

            # Wait for all pending archive tasks before finalizing session status
            await self._flush_pending_archives()
            await archiver.on_run_finished()

        except (asyncio.CancelledError, GeneratorExit):
            # Client disconnected or generator closed — finalize session status
            logger.info("Stream cancelled/closed by client, finalizing session")
            try:
                await self._flush_pending_archives()
                await archiver.on_run_finished()
            except Exception:
                pass
            # Do NOT re-raise GeneratorExit (it's not an error)
            # For CancelledError, let it propagate after cleanup
            return

        except Exception as e:
            try:
                await archiver.on_run_error(str(e))
            except Exception:
                pass
            yield adapter.create_error_event(str(e))

    def _schedule_archive_converted(self, converted_sse: str, archiver: Any) -> None:
        for payload in self._iter_agui_payloads(converted_sse):
            try:
                event_type = payload.get("type", "unknown")
                if event_type in ("TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"):
                    logger.debug(f"[StreamOrchestrator] Scheduling archive: type={event_type}, messageId={payload.get('messageId')}")
                task = asyncio.create_task(archiver.archive_event(payload))
                self._pending_archive_tasks.append(task)
            except Exception as e:
                logger.warning(f"[StreamOrchestrator] Failed to schedule archive: {e}")

    def _iter_agui_payloads(self, converted_sse: str) -> Iterable[dict[str, Any]]:
        for chunk in str(converted_sse).split("\n\n"):
            chunk = chunk.strip()
            if not chunk:
                continue
            if not chunk.startswith("data:"):
                continue
            payload = chunk.replace("data:", "", 1).strip()
            if not payload:
                continue
            try:
                data = json.loads(payload)
            except Exception:
                continue
            if isinstance(data, dict):
                yield data

    def _count_sse_events(self, sse: str) -> int:
        # Each event is separated by blank line.
        return sum(1 for part in str(sse).split("\n\n") if part.strip())

    def _build_text_content_sse(self, adapter: Any, text: str) -> Optional[str]:
        """Build a TEXT_MESSAGE_CONTENT SSE event using the adapter's current state.

        Returns the SSE string or None if unable to build.
        """
        try:
            message_id = getattr(getattr(adapter, "state", None), "current_message_id", None)
            if not message_id:
                return None
            payload = {
                "type": "TEXT_MESSAGE_CONTENT",
                "messageId": message_id,
                "delta": text,
            }
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.warning(f"Failed to build text content SSE: {e}")
            return None

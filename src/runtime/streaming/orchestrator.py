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

                # Collect text for handoff summary from raw events
                if summary_text_parts is not None:
                    try:
                        event = event_data.get("event", {})
                        if event_data.get("type") == "stream_event" and event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                summary_text_parts.append(delta.get("text", ""))
                    except Exception:
                        pass

                try:
                    converted = adapter.convert(event_data)
                except Exception:
                    continue

                if converted:
                    # Archive converted AG-UI events asynchronously (non-blocking)
                    self._schedule_archive_converted(converted, archiver)
                    event_count += self._count_sse_events(converted)
                    yield converted

            end_event = adapter.create_end_event()
            if end_event:
                event_count += self._count_sse_events(end_event)
                yield end_event

            await archiver.on_run_finished()

        except Exception as e:
            try:
                await archiver.on_run_error(str(e))
            except Exception:
                pass
            yield adapter.create_error_event(str(e))
        finally:
            # Store summary as handoff context for next message
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
                        )
                        logger.info(
                            f"Stored handoff summary ({len(summary_text)} chars) for next switch",
                            extra={"session_id": session_id, "target": handoff_pending_target},
                        )
                    except Exception as e:
                        logger.error(f"Failed to store handoff summary: {e}")

    def _schedule_archive_converted(self, converted_sse: str, archiver: Any) -> None:
        for payload in self._iter_agui_payloads(converted_sse):
            try:
                event_type = payload.get("type", "unknown")
                if event_type in ("TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"):
                    logger.debug(f"[StreamOrchestrator] Scheduling archive: type={event_type}, messageId={payload.get('messageId')}")
                asyncio.create_task(archiver.archive_event(payload))
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

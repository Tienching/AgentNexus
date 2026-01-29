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
        agent_name: str,
    ) -> AsyncGenerator[str, None]:
        """Generate AG-UI SSE stream.

        Contracts expected:
        - executor.execute(request_model, agent_name=..., output_format="raw") -> AsyncIterator[str]
        - adapter.convert(dict) -> Optional[str] (SSE chunks)
        - adapter.create_start_event()/create_end_event()/create_error_event(str) -> str
        - archiver.on_run_started(list)/on_run_finished()/on_run_error(str)
        - archiver.archive_event(dict)
        """

        event_count = 0
        try:
            await archiver.on_run_started(initial_messages)

            start_event = adapter.create_start_event()
            if start_event:
                event_count += self._count_sse_events(start_event)
                yield start_event

            async for line in executor.execute(request_model, agent_name=agent_name, output_format="raw"):
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

    async def stream_legacy(
        self,
        *,
        executor: Any,
        request_model: Any,
        legacy_adapter: Any,
        agui_adapter: Any,
        archiver: Any,
        initial_messages: list[dict[str, Any]],
        agent_name: str,
    ) -> AsyncGenerator[str, None]:
        """Generate legacy SSE stream, while archiving a converted AG-UI stream."""

        try:
            await archiver.on_run_started(initial_messages)
            logger.info(f"[StreamOrchestrator] Legacy stream started, session_id={getattr(archiver, 'session_id', 'unknown')}")

            async for line in executor.execute(request_model, agent_name=agent_name, output_format="raw"):
                if not line or not str(line).strip():
                    continue

                try:
                    event_data = json.loads(line)
                except Exception:
                    continue

                # 1) Archive: convert to AG-UI and store
                try:
                    converted_agui = agui_adapter.convert(event_data)
                    if converted_agui:
                        self._schedule_archive_converted(converted_agui, archiver)
                except Exception as e:
                    logger.warning(f"[StreamOrchestrator] Failed to convert/archive AG-UI: {e}")

                # 2) Output: legacy SSE
                if isinstance(event_data, dict) and event_data.get("type") == "error":
                    yield executor.format_legacy_error(event_data.get("message", "处理错误"))
                    continue

                # Slash command: legacy adapter may skip result
                if (
                    isinstance(event_data, dict)
                    and event_data.get("type") == "result"
                    and event_data.get("subtype") == "slash_command"
                ):
                    content = event_data.get("content") or event_data.get("result") or ""
                    if content:
                        yield executor.format_legacy_sse(content, finished=True, answer_success=1)
                    continue

                converted_legacy = None
                try:
                    converted_legacy = legacy_adapter.convert(event_data)
                except Exception:
                    converted_legacy = None

                if converted_legacy:
                    yield converted_legacy

            logger.info(f"[StreamOrchestrator] Legacy stream finished, calling on_run_finished")
            await archiver.on_run_finished()

        except Exception as e:
            try:
                await archiver.on_run_error(str(e))
            except Exception:
                pass
            yield executor.format_legacy_error(f"处理错误: {e}")

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

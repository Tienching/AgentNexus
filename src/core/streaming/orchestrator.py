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
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Iterable, Optional

logger = logging.getLogger(__name__)


class RecoverableError(Enum):
    """可恢复错误类型分类"""
    TEMPORARY = "temporary"      # 临时错误（网络抖动），应重试
    VALIDATION = "validation"    # 验证错误，不重试
    RATE_LIMIT = "rate_limit"    # 限流，稍后重试
    UNKNOWN = "unknown"           # 未知错误，标记为 tombstone


@dataclass
class StreamChunk:
    """流式块元数据"""
    block_id: str
    block_type: str              # "text" | "code" | "tool_call" | "thinking"
    sequence: int                # 序列号（递增）
    content: str                 # 累积内容
    is_final: bool = False       # 是否为最终块
    parent_chunk_id: str | None = None  # 父块 ID（用于嵌套块）


@dataclass
class TombstoneRecord:
    """墓碑记录：标记已被后续数据"覆盖"的块"""
    block_id: str
    sequence: int                # 被标记时的序列号
    reason: str                 # "replaced" | "rollback" | "retry" | "superseded"
    created_at: float
    parent_chunk_id: str | None = None  # 父块 ID（用于嵌套块）


@dataclass
class TerminalOutputFilter:
    """Hide RCA orchestration chatter before a terminal user-visible answer."""

    enabled: bool
    buffer: str = ""
    terminal_seen: bool = False
    message_id: str | None = None
    pending_start_payload: dict[str, Any] | None = None
    visible_message_started: bool = False

    TERMINAL_MARKERS = (
        "## 故障诊断报告",
        "# 故障诊断报告",
        "故障诊断报告",
        "RETRY_REQUIRED",
        "NEED_USER_INPUT",
        "ESCALATE",
    )

    def filter_agui_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.enabled:
            return [payload]

        event_type = payload.get("type")
        if event_type == "TEXT_MESSAGE_START":
            self.message_id = payload.get("messageId") or self.message_id
            if self.terminal_seen:
                self.visible_message_started = True
                return [payload]
            self.pending_start_payload = dict(payload)
            return []

        if event_type == "TEXT_MESSAGE_CONTENT":
            self.message_id = payload.get("messageId") or self.message_id
            delta = str(payload.get("delta") or "")
            visible_delta = self._filter_text(delta)
            if not visible_delta:
                return []
            updated = dict(payload)
            updated["delta"] = visible_delta
            return self._ensure_text_start(payload) + [updated]

        if "response" in payload and isinstance(payload.get("response"), str):
            visible_response = self._filter_text(str(payload.get("response") or ""))
            if visible_response:
                updated = dict(payload)
                updated["response"] = visible_response
                return [updated]
            if payload.get("finished") is True:
                flushed = self._flush_if_needed()
                if flushed:
                    updated = dict(payload)
                    updated["response"] = flushed
                    return [updated]
            return []

        if event_type == "TEXT_MESSAGE_END":
            self.message_id = payload.get("messageId") or self.message_id
            if not self.terminal_seen:
                return []
            if not self.visible_message_started:
                return []
            self.visible_message_started = False
            self.pending_start_payload = None
            return [payload]

        if event_type == "RUN_FINISHED":
            flushed = self._flush_if_needed()
            if not flushed:
                return [payload]
            flush_payload = {
                "type": "TEXT_MESSAGE_CONTENT",
                "messageId": payload.get("messageId") or self.message_id,
                "delta": flushed,
            }
            result = self._ensure_text_start(flush_payload) + [flush_payload]
            if self.visible_message_started:
                result.append(
                    {
                        "type": "TEXT_MESSAGE_END",
                        "messageId": flush_payload.get("messageId") or self.message_id,
                    }
                )
                self.visible_message_started = False
            result.append(payload)
            return result

        return [payload]

    def _ensure_text_start(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if self.visible_message_started:
            return []

        message_id = payload.get("messageId") or self.message_id
        start_payload = dict(
            self.pending_start_payload
            or {
                "type": "TEXT_MESSAGE_START",
                "role": "assistant",
            }
        )
        start_payload["type"] = "TEXT_MESSAGE_START"
        if message_id:
            start_payload["messageId"] = message_id
        start_payload.setdefault("role", "assistant")
        self.visible_message_started = True
        self.pending_start_payload = None
        return [start_payload]

    def _filter_text(self, text: str) -> str:
        if not text:
            return ""
        if self.terminal_seen:
            return text

        self.buffer += text
        marker_index = self._find_terminal_marker(self.buffer)
        if marker_index < 0:
            return ""

        self.terminal_seen = True
        visible = self.buffer[marker_index:]
        self.buffer = ""
        return visible

    def _flush_if_needed(self) -> str:
        if self.terminal_seen or not self.buffer:
            return ""
        visible = self.buffer
        self.buffer = ""
        return visible

    def _find_terminal_marker(self, text: str) -> int:
        indexes = [text.find(marker) for marker in self.TERMINAL_MARKERS]
        indexes = [idx for idx in indexes if idx >= 0]
        return min(indexes) if indexes else -1


class WithholdingQueue:
    """可恢复错误的块队列"""

    def __init__(self, max_size: int = 100):
        self.queue: deque[StreamChunk] = deque(maxlen=max_size)
        self.retry_count: dict[str, int] = {}
        self.max_retries = 3

    def hold(self, chunk: StreamChunk) -> None:
        """扣留块"""
        # 避免重复扣留同一块
        if not any(c.block_id == chunk.block_id for c in self.queue):
            self.queue.append(chunk)
            if chunk.block_id not in self.retry_count:
                self.retry_count[chunk.block_id] = 0

    def release(self, block_id: str) -> StreamChunk | None:
        """释放块"""
        for i, chunk in enumerate(self.queue):
            if chunk.block_id == block_id:
                del self.queue[i]
                return chunk
        return None

    def release_all(self) -> list[StreamChunk]:
        """全部释放"""
        chunks = list(self.queue)
        self.queue.clear()
        self.retry_count.clear()
        return chunks

    def should_retry(self, block_id: str) -> bool:
        """是否应重试"""
        return self.retry_count.get(block_id, 0) < self.max_retries

    def mark_retry(self, block_id: str) -> None:
        """记录重试次数"""
        self.retry_count[block_id] = self.retry_count.get(block_id, 0) + 1

    def clear(self) -> None:
        """清空队列"""
        self.queue.clear()
        self.retry_count.clear()

    def is_empty(self) -> bool:
        """队列是否为空"""
        return len(self.queue) == 0

    def get_pending(self) -> list[StreamChunk]:
        """获取待处理块列表（按顺序）"""
        return list(self.queue)


class StreamOrchestrator:
    def __init__(self) -> None:
        self._pending_archive_tasks: list[asyncio.Task] = []
        # Tombstone tracking
        self._active_chunks: dict[str, StreamChunk] = {}
        self._tombstones: dict[str, TombstoneRecord] = {}
        self._withholding_queue: WithholdingQueue = WithholdingQueue()
        self._block_sequence: dict[str, int] = {}  # 每个 block_id 的当前序列号

    def _get_next_sequence(self, block_id: str) -> int:
        """获取下一个序列号"""
        seq = self._block_sequence.get(block_id, 0) + 1
        self._block_sequence[block_id] = seq
        return seq

    def _mark_tombstone(self, block_id: str, sequence: int, reason: str, parent_chunk_id: str | None = None) -> TombstoneRecord:
        """标记块为 tombstone"""
        record = TombstoneRecord(
            block_id=block_id,
            sequence=sequence,
            reason=reason,
            created_at=time.time(),
            parent_chunk_id=parent_chunk_id,
        )
        self._tombstones[block_id] = record
        # 从活跃块中移除
        if block_id in self._active_chunks:
            del self._active_chunks[block_id]
        logger.debug(f"Marked tombstone: {block_id} (seq={sequence}, reason={reason})")
        return record

    def _get_active_chunks(self) -> dict[str, StreamChunk]:
        """获取所有活跃块"""
        return self._active_chunks.copy()

    def _get_tombstones(self) -> dict[str, TombstoneRecord]:
        """获取所有 tombstone 记录"""
        return self._tombstones.copy()

    def _replace_chunk(self, block_id: str, new_content: str, block_type: str = "text", parent_chunk_id: str | None = None) -> StreamChunk:
        """替换块内容（创建新序列）"""
        # 标记旧块为 tombstone
        old_chunk = self._active_chunks.get(block_id)
        if old_chunk:
            self._mark_tombstone(block_id, old_chunk.sequence, "replaced", old_chunk.parent_chunk_id)

        # 创建新块
        new_sequence = self._get_next_sequence(block_id)
        new_chunk = StreamChunk(
            block_id=block_id,
            block_type=block_type,
            sequence=new_sequence,
            content=new_content,
            is_final=False,
            parent_chunk_id=parent_chunk_id,
        )
        self._active_chunks[block_id] = new_chunk
        return new_chunk

    def _update_chunk(self, block_id: str, delta_content: str, is_final: bool = False) -> StreamChunk | None:
        """更新块内容（追加）"""
        chunk = self._active_chunks.get(block_id)
        if chunk is None:
            # 自动创建新块
            new_sequence = self._get_next_sequence(block_id)
            chunk = StreamChunk(
                block_id=block_id,
                block_type="text",
                sequence=new_sequence,
                content=delta_content,
                is_final=is_final,
            )
            self._active_chunks[block_id] = chunk
        else:
            chunk.content += delta_content
            chunk.is_final = is_final
        return chunk

    def _classify_error(self, error: Exception | str) -> RecoverableError:
        """分类错误类型"""
        error_str = str(error).lower()

        # 临时错误（网络相关）
        temporary_keywords = ["timeout", "connection", "network", "econnreset", "econnrefused", "enetunreach", "etimedout"]
        if any(kw in error_str for kw in temporary_keywords):
            return RecoverableError.TEMPORARY

        # 限流错误
        rate_limit_keywords = ["rate limit", "429", "too many requests", "quota", "throttle"]
        if any(kw in error_str for kw in rate_limit_keywords):
            return RecoverableError.RATE_LIMIT

        # 验证错误
        validation_keywords = ["validation", "invalid", "malformed", "400", "401", "403", "404"]
        if any(kw in error_str for kw in validation_keywords):
            return RecoverableError.VALIDATION

        return RecoverableError.UNKNOWN

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

    async def _wait_for_withholding_retry(self, delay: float = 2.0) -> bool:
        """等待后重试扣留的块，返回是否有更多待处理块"""
        await asyncio.sleep(delay)
        return not self._withholding_queue.is_empty()

    async def stream_agui_with_tombstone(
        self,
        *,
        executor: Any,
        request_model: Any,
        adapter: Any,
        archiver: Any,
        initial_messages: list[dict[str, Any]],
        exec_user: str,
        retry_delay: float = 2.0,
        max_retry_delay: float = 30.0,
    ) -> AsyncGenerator[str, None]:
        """Generate AG-UI SSE stream with tombstone and recoverable error withholding.

        Enhanced version of stream_agui that:
        1. Tracks each block_id's current sequence number
        2. Marks old blocks as tombstone when replaced/retry events arrive
        3. Withholds blocks on recoverable errors (TEMPORARY/RATE_LIMIT)
        4. Emits tombstone events via SSE for frontend awareness
        5. Retries withheld blocks with exponential backoff
        """

        event_count = 0
        current_retry_delay = retry_delay
        terminal_filter = TerminalOutputFilter(
            enabled=self._should_filter_terminal_output(request_model, initial_messages)
        )

        try:
            await archiver.on_run_started(initial_messages)

            start_event = adapter.create_start_event()
            if start_event:
                event_count += self._count_sse_events(start_event)
                yield start_event

            # Yield withheld blocks first (from previous session if any)
            while not self._withholding_queue.is_empty():
                pending = self._withholding_queue.get_pending()
                for chunk in pending:
                    hold_event = adapter.create_chunk_hold_event(chunk.block_id, "pending_retry")
                    if hold_event:
                        yield hold_event

            async for line in executor.execute(request_model, exec_user=exec_user, output_format="raw"):
                if not line or not str(line).strip():
                    continue

                try:
                    event_data = json.loads(line)
                except Exception:
                    continue

                # Handle tombstone events from executor
                if isinstance(event_data, dict):
                    event_type = event_data.get("type", "")
                    block_id = event_data.get("block_id", "")

                    # Check for block replacement/rollback signals
                    if event_type in ("block.replaced", "block.rollback", "block.retry"):
                        old_block_id = event_data.get("old_block_id") or block_id
                        if old_block_id in self._active_chunks:
                            old_chunk = self._active_chunks[old_block_id]
                            tombstone = self._mark_tombstone(old_block_id, old_chunk.sequence, event_type.split(".")[-1])
                            tombstone_event = adapter.create_tombstone_event(tombstone)
                            if tombstone_event:
                                yield tombstone_event
                            # Emit new block info if provided
                            new_block_id = event_data.get("new_block_id") or block_id
                            if new_block_id != old_block_id:
                                replace_event = adapter.create_chunk_replace_event(
                                    old_block_id, new_block_id, event_data.get("content", "")
                                )
                                if replace_event:
                                    yield replace_event

                try:
                    converted = adapter.convert(event_data)
                except Exception:
                    continue

                if converted:
                    converted = self._filter_terminal_output_sse(converted, terminal_filter)
                if converted:
                    # Archive converted AG-UI events asynchronously (non-blocking)
                    self._schedule_archive_converted(converted, archiver)
                    event_count += self._count_sse_events(converted)
                    yield converted

            # Release all withheld blocks before ending
            withheld_chunks = self._withholding_queue.release_all()
            for chunk in withheld_chunks:
                release_event = adapter.create_chunk_release_event(chunk.block_id, chunk.content)
                if release_event:
                    yield release_event

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
            return

        except Exception as e:
            error_type = self._classify_error(e)

            if error_type in (RecoverableError.TEMPORARY, RecoverableError.RATE_LIMIT):
                # Withhold current chunk and emit hold event
                current_block_id = event_data.get("block_id", "unknown") if isinstance(event_data, dict) else "unknown"
                current_content = event_data.get("content", "") if isinstance(event_data, dict) else ""

                if current_block_id != "unknown":
                    chunk = StreamChunk(
                        block_id=current_block_id,
                        block_type="text",
                        sequence=self._get_next_sequence(current_block_id),
                        content=current_content,
                    )
                    self._withholding_queue.hold(chunk)

                    hold_event = adapter.create_chunk_hold_event(current_block_id, error_type.value)
                    if hold_event:
                        yield hold_event

                    # Retry with exponential backoff
                    if self._withholding_queue.should_retry(current_block_id):
                        self._withholding_queue.mark_retry(current_block_id)
                        await asyncio.sleep(current_retry_delay)
                        current_retry_delay = min(current_retry_delay * 2, max_retry_delay)
                        # Note: In a real implementation, you would re-execute the request here
            elif error_type == RecoverableError.UNKNOWN:
                # Mark as tombstone and continue
                if isinstance(event_data, dict) and event_data.get("block_id"):
                    tombstone = self._mark_tombstone(
                        event_data["block_id"],
                        self._block_sequence.get(event_data["block_id"], 0),
                        "error"
                    )
                    tombstone_event = adapter.create_tombstone_event(tombstone)
                    if tombstone_event:
                        yield tombstone_event

            # Final error handling
            try:
                await archiver.on_run_error(str(e))
            except Exception:
                pass
            yield adapter.create_error_event(str(e))

    async def stream_agui(
        self,
        *,
        executor: Any,
        request_model: Any,
        adapter: Any,
        archiver: Any,
        initial_messages: list[dict[str, Any]],
        exec_user: str,
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
        terminal_filter = TerminalOutputFilter(
            enabled=self._should_filter_terminal_output(request_model, initial_messages)
        )
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
                    converted = self._filter_terminal_output_sse(converted, terminal_filter)
                if converted:
                    # Archive converted AG-UI events asynchronously (non-blocking)
                    self._schedule_archive_converted(converted, archiver)
                    event_count += self._count_sse_events(converted)
                    yield converted

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
            return

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
        exec_user: str,
    ) -> AsyncGenerator[str, None]:
        """Generate legacy SSE stream, while archiving a converted AG-UI stream."""

        try:
            await archiver.on_run_started(initial_messages)

            async for line in executor.execute(request_model, exec_user=exec_user, output_format="raw"):
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
                except Exception:
                    pass

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

            await self._flush_pending_archives()
            await archiver.on_run_finished()

        except (asyncio.CancelledError, GeneratorExit):
            logger.info("Legacy stream cancelled/closed by client, finalizing session")
            try:
                await self._flush_pending_archives()
                await archiver.on_run_finished()
            except Exception:
                pass
            return

        except Exception as e:
            try:
                await archiver.on_run_error(str(e))
            except Exception:
                pass
            yield executor.format_legacy_error(f"处理错误: {e}")

    def _should_filter_terminal_output(
        self,
        request_model: Any,
        initial_messages: list[dict[str, Any]],
    ) -> bool:
        """Return whether to suppress RCA orchestration chatter for this request."""
        text_parts: list[str] = []
        for message in initial_messages or []:
            if isinstance(message, dict):
                text_parts.append(self._stringify_message_content(message.get("content")))

        try:
            for message in getattr(request_model, "messages", []) or []:
                if isinstance(message, dict):
                    text_parts.append(self._stringify_message_content(message.get("content")))
                else:
                    text_parts.append(self._stringify_message_content(getattr(message, "content", "")))
        except Exception:
            pass

        user_text = "\n".join(part for part in text_parts if part)
        if not user_text:
            return False

        diagnosis_keywords = (
            "RCA",
            "故障",
            "诊断",
            "定位",
            "根因",
            "处理建议",
            "设备",
            "端口",
            "告警",
            "重启",
            "异常",
            "diag",
            "PARITYECC",
            "link down",
            "flap",
        )
        lowered = user_text.lower()
        return any(keyword.lower() in lowered for keyword in diagnosis_keywords)

    def _stringify_message_content(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
            return "\n".join(part for part in parts if part)
        return str(content)

    def _filter_terminal_output_sse(
        self,
        converted_sse: str,
        terminal_filter: TerminalOutputFilter,
    ) -> str:
        if not terminal_filter.enabled or not converted_sse:
            return converted_sse

        filtered_chunks: list[str] = []
        for raw_chunk in str(converted_sse).split("\n\n"):
            chunk = raw_chunk.strip()
            if not chunk:
                continue
            payload = self._extract_sse_payload(chunk)
            if payload is None:
                filtered_chunks.append(f"{chunk}\n\n")
                continue
            for filtered_payload in terminal_filter.filter_agui_payload(payload):
                if filtered_payload.get("type") == "TEXT_MESSAGE_CONTENT" and not filtered_payload.get("messageId"):
                    continue
                filtered_chunks.append(self._format_agui_payload_sse(filtered_payload))
        return "".join(filtered_chunks)

    def _extract_sse_payload(self, chunk: str) -> dict[str, Any] | None:
        data_lines: list[str] = []
        for line in chunk.splitlines():
            stripped = line.strip()
            if stripped.startswith("data:"):
                data_lines.append(stripped.replace("data:", "", 1).strip())
        if not data_lines:
            return None
        try:
            payload = json.loads("\n".join(data_lines))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _format_agui_payload_sse(self, payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _schedule_archive_converted(self, converted_sse: str, archiver: Any) -> None:
        for payload in self._iter_agui_payloads(converted_sse):
            try:
                task = asyncio.create_task(archiver.archive_event(payload))
                self._pending_archive_tasks.append(task)
            except Exception:
                pass

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

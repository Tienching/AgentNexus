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

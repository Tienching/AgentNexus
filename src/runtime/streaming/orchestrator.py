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
import re
import uuid
from typing import Any, AsyncGenerator, Iterable, Optional

from src.core.streaming.orchestrator import TerminalOutputFilter

logger = logging.getLogger(__name__)


_CODEBUDDY_AGENT_TASK_RE = re.compile(r"\bagent-[0-9A-Za-z_-]+\b")
_CODEBUDDY_AGENT_WAIT_MARKERS = (
    "等待分析结果",
    "等待其通过 SendMessage",
    "等待 `SendMessage`",
    "正在后台运行",
    "正在等待",
    "等待专家",
    "专家返回",
    "结果稍后",
    "收到后汇总",
    "已启动待返回",
    "待返回",
)
_CODEBUDDY_FINAL_MARKERS = (
    "# 故障诊断报告",
    "## 诊断结论",
    "**根本原因:**",
    "根本原因:",
    "## 证据链",
    "## 修复方案",
    "RETRY_REQUIRED",
    "NEED_USER_INPUT",
    "ESCALATE",
)
_CODEBUDDY_MAX_AGENT_WAIT_CONTINUES = 2
_AGENTHUB_DATA_RESULT_MARKERS = (
    "agenthub_data.py",
    "agenthub-data",
    "客服号聊天历史",
    "search_group_chat_history",
)
_GROUP_HISTORY_REQUEST_MARKERS = (
    "群历史",
    "聊天历史",
    "历史消息",
    "聊天记录",
)


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
        terminal_filter = TerminalOutputFilter(
            enabled=self._should_filter_terminal_output(request_model, initial_messages)
        )
        try:
            await archiver.on_run_started(initial_messages)

            start_event = adapter.create_start_event()
            if start_event:
                event_count += self._count_sse_events(start_event)
                yield start_event

            text_parts: list[str] = []
            visible_text_parts: list[str] = []
            agenthub_data_tool_results: list[str] = []
            codebuddy_agent_task_ids: set[str] = set()
            auto_continue_count = 0

            while True:
                async for line in executor.execute(request_model, exec_user=exec_user, output_format="raw"):
                    if not line or not str(line).strip():
                        continue

                    try:
                        event_data = json.loads(line)
                    except Exception:
                        continue

                    codebuddy_agent_task_ids.update(self._extract_codebuddy_agent_task_ids(event_data))
                    self._remember_cli_session_id(request_model, event_data)

                    try:
                        converted = adapter.convert(event_data)
                    except Exception:
                        continue

                    if converted:
                        # Collect text from AG-UI events for switch summary and CodeBuddy wait-state recovery.
                        for payload in self._iter_agui_payloads(converted):
                            if payload.get("type") == "TEXT_MESSAGE_CONTENT":
                                delta = payload.get("delta", "")
                                if delta:
                                    text_parts.append(str(delta))
                                if summary_text_parts is not None:
                                    summary_text_parts.append(delta)
                            self._collect_agenthub_data_tool_result(payload, agenthub_data_tool_results)
                        visible_converted = self._filter_terminal_output_sse(converted, terminal_filter)
                        if visible_converted:
                            for payload in self._iter_agui_payloads(visible_converted):
                                if payload.get("type") == "TEXT_MESSAGE_CONTENT":
                                    delta = payload.get("delta", "")
                                    if delta:
                                        visible_text_parts.append(str(delta))
                            # Archive user-visible converted AG-UI events asynchronously (non-blocking).
                            self._schedule_archive_converted(visible_converted, archiver)
                            event_count += self._count_sse_events(visible_converted)
                            yield visible_converted

                if not self._should_continue_codebuddy_agent_wait(
                    "".join(text_parts),
                    codebuddy_agent_task_ids,
                    auto_continue_count,
                ):
                    break

                auto_continue_count += 1
                task_ids = sorted(codebuddy_agent_task_ids)
                logger.warning(
                    "CodeBuddy analyst run ended in wait state; auto-continuing before RUN_FINISHED",
                    extra={"task_ids": task_ids, "auto_continue_count": auto_continue_count},
                )
                self._prepare_codebuddy_agent_wait_continue(request_model, task_ids)

            if self._should_emit_agenthub_data_fallback(
                request_model,
                initial_messages,
                "".join(visible_text_parts),
                agenthub_data_tool_results,
            ):
                fallback_sse = self._build_agenthub_data_fallback_sse(
                    adapter,
                    agenthub_data_tool_results,
                )
                if fallback_sse:
                    terminal_filter.buffer = ""
                    terminal_filter.pending_start_payload = None
                    terminal_filter.visible_message_started = False
                    self._schedule_archive_converted(fallback_sse, archiver)
                    event_count += self._count_sse_events(fallback_sse)
                    yield fallback_sse

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
                end_event = self._filter_terminal_output_sse(end_event, terminal_filter)
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
            content = getattr(request_model, "content", "")
            if content:
                text_parts.append(self._stringify_message_content(content))
        except Exception:
            pass

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
        # WeCom group messages often include the bot mention "TSwitch-RCA".
        # That name alone should not make ordinary history-summary requests run
        # through the RCA terminal-output filter.
        user_text = re.sub(
            r"@?TSwitch\s*-\s*RCA(?:[（(][^）)]*[）)])?",
            "",
            user_text,
            flags=re.IGNORECASE,
        )
        user_text = user_text.replace("交换机智能诊断助手", "")

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

    def _collect_agenthub_data_tool_result(
        self,
        payload: dict[str, Any],
        results: list[str],
    ) -> None:
        event_type = payload.get("type")
        if event_type not in ("TOOL_CALL_RESULT", "TOOL_CALL_END"):
            return
        content = payload.get("content") if event_type == "TOOL_CALL_RESULT" else payload.get("result")
        if not content:
            return
        text = str(content)
        if any(marker in text for marker in _AGENTHUB_DATA_RESULT_MARKERS):
            results.append(text)

    def _should_emit_agenthub_data_fallback(
        self,
        request_model: Any,
        initial_messages: list[dict[str, Any]],
        visible_text: str,
        agenthub_data_tool_results: list[str],
    ) -> bool:
        if visible_text.strip():
            return False
        if not agenthub_data_tool_results:
            return False

        request_text_parts: list[str] = []
        for message in initial_messages or []:
            if isinstance(message, dict):
                request_text_parts.append(self._stringify_message_content(message.get("content")))
        try:
            request_text_parts.append(self._stringify_message_content(getattr(request_model, "content", "")))
        except Exception:
            pass
        request_text = "\n".join(part for part in request_text_parts if part)
        if not request_text:
            return False
        return any(marker in request_text for marker in _GROUP_HISTORY_REQUEST_MARKERS)

    def _build_agenthub_data_fallback_sse(
        self,
        adapter: Any,
        agenthub_data_tool_results: list[str],
    ) -> Optional[str]:
        fallback_text = self._build_agenthub_data_fallback_text(agenthub_data_tool_results)
        if not fallback_text:
            return None

        message_id = None
        try:
            message_id = getattr(getattr(adapter, "state", None), "current_message_id", None)
        except Exception:
            message_id = None
        message_id = message_id or f"nexus-agenthub-data-{uuid.uuid4().hex}"

        try:
            if getattr(adapter, "state", None) is not None:
                adapter.state.current_message_id = message_id
                adapter.state.message_started = False
        except Exception:
            pass

        payloads = [
            {"type": "TEXT_MESSAGE_START", "messageId": message_id, "role": "assistant"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": message_id, "delta": fallback_text},
            {"type": "TEXT_MESSAGE_END", "messageId": message_id},
        ]
        return "".join(self._format_agui_payload_sse(payload) for payload in payloads)

    def _build_agenthub_data_fallback_text(
        self,
        agenthub_data_tool_results: list[str],
    ) -> str:
        selected = self._select_agenthub_history_result(agenthub_data_tool_results)
        if not selected:
            return ""

        stdout = self._extract_tool_stdout(selected).strip()
        if not stdout:
            stdout = selected.strip()

        group_id = self._extract_group_id(stdout)
        message_count = self._extract_message_count(stdout)
        group_label = f"群 ID: `{group_id}`" if group_id else "该群"

        if "未查询到客服号聊天历史" in stdout:
            return (
                "## 群历史总结\n\n"
                f"已调用 `agenthub-data` 查询{group_label}，但客服号侧没有返回可总结的聊天历史。"
                "如果这是智能机器人渠道，查询不到客服号历史属于预期边界。"
            )

        excerpt = self._trim_text(stdout, 3200)
        if message_count == 1:
            return (
                "## 群历史总结\n\n"
                f"已调用 `agenthub-data` 查询{group_label}，客服号侧当前只返回 1 条消息。"
                "这条记录就是本次触发查询的消息，因此没有更多群历史可总结。\n\n"
                "查询摘录：\n"
                f"{excerpt}"
            )

        count_text = f"{message_count} 条" if message_count is not None else "若干条"
        return (
            "## 群历史总结\n\n"
            f"已调用 `agenthub-data` 查询{group_label}，客服号侧返回 {count_text}聊天记录。"
            "由于模型本轮未生成最终总结，以下先返回查询结果摘录，避免本轮只停在工具调用阶段。\n\n"
            "查询摘录：\n"
            f"{excerpt}"
        )

    def _select_agenthub_history_result(self, agenthub_data_tool_results: list[str]) -> str:
        for result in reversed(agenthub_data_tool_results):
            if "客服号聊天历史查询结果" in result or "未查询到客服号聊天历史" in result:
                return result
        return agenthub_data_tool_results[-1] if agenthub_data_tool_results else ""

    def _extract_tool_stdout(self, text: str) -> str:
        match = re.search(r"Stdout:\s*(.*?)(?:\nStderr:|\Z)", text, flags=re.S)
        if not match:
            return text
        return match.group(1).strip()

    def _extract_group_id(self, text: str) -> Optional[str]:
        match = re.search(r"群\s*ID[:：]\s*([^\s`]+)", text)
        return match.group(1).strip() if match else None

    def _extract_message_count(self, text: str) -> Optional[int]:
        match = re.search(r"消息数[:：]\s*(\d+)", text)
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    def _trim_text(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "\n...(已截断)"

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

    def _extract_codebuddy_agent_task_ids(self, event_data: dict[str, Any]) -> set[str]:
        combined = "\n".join(self._iter_string_fragments(event_data))
        if not combined:
            return set()
        task_ids = set(_CODEBUDDY_AGENT_TASK_RE.findall(combined))
        if not task_ids:
            return set()
        agent_markers = (
            "Agent",
            "Spawned successfully",
            "subagent_type",
            "team member task",
            "TaskOutput",
            "SendMessage",
        )
        if any(marker in combined for marker in agent_markers):
            return task_ids
        return set()

    def _iter_string_fragments(self, value: Any) -> Iterable[str]:
        if isinstance(value, dict):
            for key, item in value.items():
                yield str(key)
                yield from self._iter_string_fragments(item)
        elif isinstance(value, list):
            for item in value:
                yield from self._iter_string_fragments(item)
        elif isinstance(value, str):
            yield value
        elif value is not None:
            yield str(value)

    def _remember_cli_session_id(self, request_model: Any, event_data: dict[str, Any]) -> None:
        if not isinstance(event_data, dict):
            return
        cli_session_id = event_data.get("session_id") or event_data.get("thread_id")
        if not cli_session_id:
            return
        try:
            if not getattr(request_model, "cli_session_id", None):
                setattr(request_model, "cli_session_id", str(cli_session_id))
        except Exception:
            return

    def _should_continue_codebuddy_agent_wait(
        self,
        text: str,
        task_ids: set[str],
        auto_continue_count: int,
    ) -> bool:
        if auto_continue_count >= _CODEBUDDY_MAX_AGENT_WAIT_CONTINUES:
            return False
        if not task_ids or not text:
            return False
        if any(marker in text for marker in _CODEBUDDY_FINAL_MARKERS):
            return False
        return any(marker in text for marker in _CODEBUDDY_AGENT_WAIT_MARKERS)

    def _prepare_codebuddy_agent_wait_continue(self, request_model: Any, task_ids: list[str]) -> None:
        task_list = ", ".join(task_ids) if task_ids else "未知"
        followup = (
            "上一轮已经启动 CodeBuddy analyst，但用户可见输出停在等待状态，这不是完成态。\n"
            f"已启动但未汇总的 task_id: {task_list}\n\n"
            "请继续同一个 RCA 会话，并遵守：\n"
            "1. 不要重新派发重复 analyst；先读取已经收到的 SendMessage/专家结论文件。\n"
            "2. 如果仍未读到结论，必须对未完成 task 调用 TaskOutput(block=true, timeout=600) 形成等待屏障。\n"
            "3. 只有所有已启动 analyst 都返回可读专家最终结论，才允许进入 FINAL_READY 并输出完整故障诊断报告。\n"
            "4. 如果 TaskOutput 返回 task 不存在、running 后仍未读到可读专家最终结论、仅有 evidence_brief、"
            "仅有你自己的推理、工具超时或专家失败，只能输出 RETRY_REQUIRED 或 ESCALATE；"
            "不得输出 FINAL_READY，不得输出完整故障诊断报告，不得以 AGENTS 自行裁决绕过专家。\n"
            "5. 禁止只回复“正在等待/后台运行/稍后返回/收到后汇总”。"
        )
        try:
            setattr(request_model, "content", followup)
            setattr(request_model, "content_parts", [])
            setattr(request_model, "image_paths", [])
            setattr(request_model, "file_paths", [])
            setattr(request_model, "session_cleared", False)
        except Exception:
            logger.warning("Failed to prepare CodeBuddy analyst wait-state continuation", exc_info=True)

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

# -*- coding: utf-8 -*-
"""Stream Handler Service

Handle AG-UI protocol streaming responses (Legacy protocol removed)
"""

import asyncio
import json
import time
import uuid
from typing import Any, Dict

from fastapi import HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from ..models import RequestModel
from src.runtime.events.agui import AGUIRequest
from ..adapters import ProtocolType, get_router
from ..config import settings
from ..logger import get_logger
from ..providers import get_provider_registry
from .cli_executor import CLIExecutor
from .callback_handler import CallbackHandler
from .stream_archiver import create_archiver
from .session_storage import get_session_storage
from src.providers.gemini import GeminiExecutor
from src.providers.codex import CodexCLIExecutor
from src.providers.codebuddy import CodebuddyCLIExecutor
from src.runtime.adapters.gemini import GeminiAGUIAdapter
from src.runtime.adapters.codex import CodexCLIAGUIAdapter
from src.runtime.adapters.codebuddy import CodebuddyAGUIAdapter
from src.runtime.streaming import StreamOrchestrator

logger = get_logger(__name__)


class StreamHandler:
    """流式处理器 - 统一使用 AG-UI 协议"""

    def __init__(self):
        self._cli_executor = CLIExecutor(config=settings)
        self._gemini_executor = GeminiExecutor(config=settings)
        self._codex_executor = CodexCLIExecutor()
        self._codebuddy_executor = CodebuddyCLIExecutor()
        self.callback_handler = CallbackHandler()

    def _get_provider(self, request: Request, body_dict: Dict[str, Any]) -> str:
        # Keep existing resolution behavior, but centralize logic in ProviderRegistry.
        reg = get_provider_registry()
        resolved = reg.resolve_provider(request, body_dict)
        return resolved.name

    def _get_executor(self, provider: str, request_model: RequestModel | None = None):
        """Select executor for this request.

        Notes:
        - Backward compat: unknown provider still uses Claude backend.
        - Slash commands are local operations; always route them to CLIExecutor.
        """
        try:
            content = (getattr(request_model, "content", "") or "").strip()
        except Exception:
            content = ""

        if content.startswith("/"):
            return self._cli_executor

        provider_lower = (provider or "").strip().lower()
        if provider_lower == "gemini":
            return self._gemini_executor
        elif provider_lower == "codex":
            return self._codex_executor
        elif provider_lower == "codebuddy":
            return self._codebuddy_executor
        return self._cli_executor

    def _get_agui_adapter(self, provider: str):
        provider_lower = (provider or "").strip().lower()
        if provider_lower == "gemini":
            return GeminiAGUIAdapter()
        elif provider_lower == "codex":
            return CodexCLIAGUIAdapter()
        elif provider_lower == "codebuddy":
            return CodebuddyAGUIAdapter()
        return get_router().get_adapter(ProtocolType.AGUI)

    async def handle_agui_request(
        self,
        request: Request,
        body_dict: Dict[str, Any],
        exec_user: str
    ) -> StreamingResponse:
        """处理 AG-UI 协议请求"""
        provider = self._get_provider(request, body_dict)
        
        try:
            agui_request = AGUIRequest.model_validate(body_dict)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid AG-UI request: {str(e)}"
            )
        
        legacy_data = agui_request.to_legacy_request()
        # Username is optional for AG-UI callers; use an internal default.
        if not legacy_data.get("user"):
            legacy_data["user"] = "anonymous"
        request_model = RequestModel.model_validate(legacy_data)

        # In /workspace -t mode, the workspace provider (stored in Redis session)
        # should override the request-level provider for executor and adapter selection.
        # Without this, a workspace using gemini would get a Claude executor/adapter.
        session_id = request_model.session_id or agui_request.threadId
        workspace_provider = None
        workspace_alias = None
        if session_id:
            try:
                storage = get_session_storage()
                workspace_provider = storage.get_workspace_provider(session_id)
                if workspace_provider:
                    logger.info(
                        f"Workspace provider override for executor/adapter selection: {provider} -> {workspace_provider}",
                        extra={"session_id": session_id, "workspace_provider": workspace_provider}
                    )
                    provider = workspace_provider
                # Also restore the original alias (e.g., 'gemini-internal') for CLI command selection
                workspace_alias = storage.get_workspace_alias(session_id)
                if workspace_alias:
                    logger.info(f"Workspace alias restored: {workspace_alias}")
                # Set exec_dir override (cwd) for non-CLIExecutor executors (e.g., GeminiExecutor)
                exec_dir_override = storage.get_exec_dir_override(session_id)
                if exec_dir_override:
                    request_model.cwd = exec_dir_override
                    request_model.cwd_mode = "inplace"
                    logger.info(f"Workspace exec_dir override: {exec_dir_override}")
            except Exception as e:
                logger.warning(f"Failed to check workspace provider/alias: {e}")

        request_model.provider = provider
        request_model.agent_type = provider
        # Set alias on request_model so executors (e.g., GeminiExecutor) use the correct CLI command
        if workspace_alias and not getattr(request_model, "alias", None):
            request_model.alias = workspace_alias
        # In workspace mode, mark as chat_continue so GeminiExecutor adds --resume latest
        if workspace_provider:
            request_model.run_kind = "chat_continue"
        
        adapter = self._get_agui_adapter(provider)
        executor = self._get_executor(provider, request_model=request_model)

        adapter.init_state(
            thread_id=agui_request.threadId,
            run_id=agui_request.runId
        )
        
        # 提取 response_url
        response_url = agui_request.get_response_url()
        
        logger.info(
            "AG-UI request converted",
            extra={
                "thread_id": agui_request.threadId,
                "run_id": agui_request.runId,
                "user": request_model.user,
                "provider": provider,
                "has_response_url": bool(response_url),
            }
        )
        
        # For AG-UI, content is required but user is not.
        if not request_model.content:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Missing required field: content (or messages for AG-UI)"
            )
        
        # 如果有 response_url，启用超时回调模式
        if response_url:
            return await self._stream_agui_with_callback(
                request, request_model, agui_request, adapter, exec_user, executor, provider
            )
        
        # 标准 AG-UI 流式处理
        # Extract username for archiver
        username = request_model.user or "anonymous"
        alias = agui_request.get_alias() or provider
        
        # Create archiver for session storage
        archiver = create_archiver(
            thread_id=agui_request.threadId,
            run_id=agui_request.runId,
            username=username,
            exec_user=exec_user,
            provider=provider,
            alias=alias,
        )
        
        # Extract initial messages for archiver
        initial_messages = [
            {"id": msg.get("id"), "role": msg.get("role"), "content": msg.get("content")}
            for msg in (agui_request.messages or [])
            if isinstance(msg, dict)
        ]
        
        orchestrator = StreamOrchestrator()

        return StreamingResponse(
            orchestrator.stream_agui(
                executor=executor,
                request_model=request_model,
                adapter=adapter,
                archiver=archiver,
                initial_messages=initial_messages,
                exec_user=exec_user,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Transfer-Encoding": "chunked",
            },
        )

    async def _stream_agui_with_callback(
        self,
        request: Request,
        request_model: RequestModel,
        agui_request: AGUIRequest,
        adapter,
        exec_user: str,
        executor,
        provider: str = "claude",
    ) -> StreamingResponse:
        """支持超时回调的 AG-UI 流式处理
        
        在 5分30秒 时发送超时提示并结束 SSE 流，
        后台继续收集 CLI 回复，完成后通过 response_url 发送剩余结果。
        """
        STREAM_TIMEOUT = 330  # 5分30秒
        
        response_url = agui_request.get_response_url()
        msg_id = agui_request.get_msg_id()
        
        # Create archiver for session storage
        username = request_model.user or "anonymous"
        alias = agui_request.get_alias() or provider
        archiver = create_archiver(
            thread_id=agui_request.threadId,
            run_id=agui_request.runId,
            username=username,
            exec_user=exec_user,
            provider=provider,
            alias=alias,
        )
        
        # Extract initial messages for archiver
        initial_messages = [
            {"id": msg.get("id"), "role": msg.get("role"), "content": msg.get("content")}
            for msg in (agui_request.messages or [])
            if isinstance(msg, dict)
        ]
        
        message_queue: asyncio.Queue = asyncio.Queue()
        
        stream_state = {
            "client_disconnected": False,
            "stream_timeout": False,
            "all_events": [],      # 所有 AG-UI 事件
            "sent_count": 0,       # 已发送的事件数
            "producer_done": False,
            "start_time": time.time(),
        }
        
        async def producer():
            """后台生产者：执行 CLI 并收集事件"""
            try:
                # Initialize archiver
                await archiver.on_run_started(initial_messages)
                
                async for line in executor.execute(request_model, exec_user=exec_user, output_format="raw"):
                    if not line.strip():
                        continue
                    
                    try:
                        event_data = json.loads(line)
                        converted = adapter.convert(event_data)
                        
                        # Archive converted AG-UI events asynchronously
                        if converted:
                            for _evt in converted.split('\n\n'):
                                _evt = _evt.strip()
                                if not _evt:
                                    continue
                                if _evt.startswith('data:'):
                                    try:
                                        payload = _evt.replace('data:', '', 1).strip()
                                        asyncio.create_task(archiver.archive_event(json.loads(payload)))
                                    except Exception:
                                        pass
                        
                        if converted:
                            # 保存事件
                            for event_str in converted.split('\n\n'):
                                if event_str.strip():
                                    stream_state["all_events"].append(event_str + '\n\n')
                            
                            await message_queue.put(("events", converted))
                    except json.JSONDecodeError:
                        logger.warning(f"AG-UI JSON decode error: {line[:200]}")
                        continue
                    except Exception as e:
                        logger.warning(f"AG-UI convert error: {e}")
                        continue
                        
            except Exception as e:
                logger.error(f"AG-UI producer error: {e}", exc_info=True)
                await archiver.on_run_error(str(e))
                await message_queue.put(("error", str(e)))
            finally:
                stream_state["producer_done"] = True
                await message_queue.put(("done", None))
                
                # Finalize archiver
                if not stream_state.get("error_occurred"):
                    await archiver.on_run_finished()
                
                # 如果超时或断开，发送剩余事件到 response_url
                if (stream_state["stream_timeout"] or stream_state["client_disconnected"]) and response_url:
                    pending_events = stream_state["all_events"][stream_state["sent_count"]:]
                    if pending_events:
                        logger.info(
                            "Sending remaining AG-UI events via callback",
                            extra={
                                "pending_count": len(pending_events),
                                "total_count": len(stream_state["all_events"]),
                            }
                        )
                        await self.callback_handler.send_agui_callback(
                            response_url,
                            pending_events,
                            {
                                "user": request_model.user,
                                "msg_id": msg_id or request_model.msg_id,
                                "session_id": request_model.session_id,
                                "content": request_model.content,
                            }
                        )
        
        producer_task = asyncio.create_task(producer())
        
        async def generate():
            """生成 AG-UI SSE 流"""
            event_count = 0
            try:
                # 发送开始事件
                start_event = adapter.create_start_event()
                if start_event:
                    event_count += 1
                    yield start_event
                
                while True:
                    elapsed_time = time.time() - stream_state["start_time"]
                    
                    # 超时检查
                    if elapsed_time >= STREAM_TIMEOUT:
                        logger.info("AG-UI stream timeout reached, switching to background processing")
                        stream_state["stream_timeout"] = True
                        
                        # 发送超时提示
                        timeout_msg = "\n\n---\n⏰ **处理时间较长，已转为后台处理**\n\n内容较多，为避免连接超时，已转为后台继续处理。处理完成后会将完整结果发送给您，请耐心等待。\n"
                        
                        from src.runtime.events.agui import (
                            TextMessageContentEvent,
                            TextMessageEndEvent,
                            RunFinishedEvent,
                        )
                        
                        # 确保有消息 ID
                        if not adapter.state.message_started:
                            adapter.state.current_message_id = f"timeout-msg-{agui_request.runId}"
                            adapter.state.message_started = True
                            from src.runtime.events.agui import (
                                TextMessageStartEvent,
                                MessageRole,
                            )
                            msg_start = TextMessageStartEvent(
                                messageId=adapter.state.current_message_id,
                                role=MessageRole.ASSISTANT
                            )
                            yield msg_start.to_sse()
                        
                        # 发送超时提示内容
                        content_event = TextMessageContentEvent(
                            messageId=adapter.state.current_message_id,
                            delta=timeout_msg
                        )
                        yield content_event.to_sse()
                        
                        # 发送消息结束
                        msg_end = TextMessageEndEvent(messageId=adapter.state.current_message_id)
                        yield msg_end.to_sse()
                        
                        # 发送运行结束
                        run_finished = RunFinishedEvent(
                            threadId=agui_request.threadId,
                            runId=agui_request.runId
                        )
                        yield run_finished.to_sse()
                        
                        return
                    
                    # 检查客户端断开
                    if await request.is_disconnected():
                        logger.info("AG-UI client disconnected during streaming")
                        stream_state["client_disconnected"] = True
                        return
                    
                    # 获取消息
                    try:
                        msg_type, msg_data = await asyncio.wait_for(
                            message_queue.get(),
                            timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        continue
                    
                    if msg_type == "done":
                        # 正常完成，发送结束事件
                        end_event = adapter.create_end_event()
                        if end_event:
                            yield end_event
                        break
                    elif msg_type == "error":
                        error_event = adapter.create_error_event(f"处理错误: {msg_data}")
                        yield error_event
                        break
                    elif msg_type == "events":
                        yield msg_data
                        stream_state["sent_count"] = len(stream_state["all_events"])
                        event_count += msg_data.count('\n\n')
                
                logger.info(f"AG-UI stream with callback completed, events sent: {event_count}")
                
            except asyncio.CancelledError:
                logger.info("AG-UI stream generator cancelled")
                stream_state["client_disconnected"] = True
            except Exception as e:
                logger.error(f"AG-UI stream generation error: {e}", exc_info=True)
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Transfer-Encoding": "chunked",
            },
        )

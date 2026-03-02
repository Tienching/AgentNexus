# -*- coding: utf-8 -*-
"""Stream Handler Service

Handle AG-UI protocol streaming responses (Legacy protocol removed)
"""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, Optional

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

    def _build_conversation_history_text(
        self,
        session_id: str,
        max_messages: Optional[int] = 50,
        truncate_each: Optional[int] = 800,
    ) -> str:
        """Build a formatted conversation history text from Redis stored messages."""
        try:
            storage = get_session_storage()
            messages = storage.get_session_messages(session_id)
            if not messages:
                return ""

            selected = messages[-max_messages:] if max_messages and max_messages > 0 else messages

            parts: list[str] = []
            for msg in selected:
                role_label = {"user": "用户", "assistant": "助手"}.get(msg.role, msg.role)
                content = (msg.content or "").strip()
                if not content:
                    continue
                if truncate_each and truncate_each > 0 and len(content) > truncate_each:
                    content = content[:truncate_each] + "…(截断)"
                parts.append(f"[{role_label}] {content}")

            if not parts:
                return ""

            return "\n\n".join(parts)
        except Exception as e:
            logger.error(f"Failed to build conversation history text: {e}")
            return ""

    def _prepare_handoff_prompt(self, session_id: str, target: str, context_mode: str = "full") -> str:
        """Build handoff prompt by fetching conversation history from Redis.

        Args:
            session_id: Current session ID.
            target: Target provider/alias name.
            context_mode: ``"full"`` (default, all messages, no truncation) or
                ``"windowed"`` (last 50 messages, each truncated to 800 chars).
        """
        mode = (context_mode or "full").strip().lower()
        # Backward compat: treat legacy "summary" as "windowed"
        if mode == "summary":
            mode = "windowed"
        if mode not in ("full", "windowed"):
            mode = "full"

        if mode == "windowed":
            conversation_history = self._build_conversation_history_text(
                session_id,
                max_messages=50,
                truncate_each=800,
            )
            if not conversation_history:
                conversation_history = "(对话记录为空，没有可注入的内容)"

            return f"""请整理并输出以下窗口范围内的历史对话上下文，原样保留关键信息与时序。

这个上下文将传递给下一个 Agent ({target}) 作为续聊输入。

请直接输出上下文内容，不要额外解释。

---

以下是最近的对话记录（窗口截断）：

{conversation_history}"""

        # full mode
        conversation_history = self._build_conversation_history_text(
            session_id,
            max_messages=None,
            truncate_each=None,
        )
        if not conversation_history:
            conversation_history = "(对话记录为空，没有可注入的内容)"

        return f"""请整理并输出完整的历史对话上下文，原样保留关键信息与时序，不要省略重要细节。

这个完整上下文将传递给下一个 Agent ({target}) 作为续聊输入。

请直接输出上下文内容，不要额外解释。

---

以下是历史对话记录：

{conversation_history}"""

    def _try_inline_handoff_auto(
        self,
        session_id: str,
        content: str,
        request_model: RequestModel,
    ) -> tuple[str, str | None, str] | None:
        """Try to handle ``/handoff ... -a`` inline in the current request.

        If the slash command is a valid ``/handoff -a`` (auto-summary), this
        method resolves the target, builds the summary prompt and rewrites
        ``request_model.content`` so the request goes through the LLM path
        (not the CLIExecutor path) to generate the summary immediately.

        Returns:
            Tuple of (effective_alias, model, context_mode) if handled, ``None`` otherwise.
        """
        from src.runtime.commands.slash.parser import parse_slash_command, SlashCommandParseError
        from src.runtime.stores.alias_registry import get_alias_registry

        try:
            parsed = parse_slash_command(content)
        except SlashCommandParseError:
            return None  # let CLIExecutor handle and show error

        if parsed.cmd != "handoff":
            return None
        if not parsed.options.get("auto"):
            return None

        alias = parsed.options.get("alias")
        provider_arg = parsed.options.get("provider")
        model_arg = (parsed.options.get("model") or "").strip() or None
        context_mode = (parsed.options.get("context-mode") or "full").strip().lower()
        # Backward compat: treat legacy "summary" as "windowed"
        if context_mode == "summary":
            context_mode = "windowed"
        if context_mode not in ("full", "windowed"):
            context_mode = "full"

        # Resolve target
        alias_registry = get_alias_registry()
        target_alias = None
        target_provider = provider_arg

        if alias:
            resolved = alias_registry.resolve(alias)
            if not resolved:
                return None  # let CLIExecutor handle and show error
            target_provider = resolved
            target_alias = alias

        if not target_provider:
            return None

        effective_alias = target_alias or target_provider.lower()

        logger.info(
            f"Inline /handoff -a detected, generating summary immediately",
            extra={
                "session_id": session_id,
                "target": effective_alias,
            },
        )

        request_model.content = self._prepare_handoff_prompt(session_id, effective_alias, context_mode=context_mode)
        return (effective_alias, model_arg, context_mode)

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
        # Priority: workspace_provider (from /workspace -t) > handoff_provider > request default
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
                else:
                    # No workspace provider — check for handoff provider
                    handoff_prov = storage.get_handoff_provider(session_id)
                    if handoff_prov:
                        hp, ha = handoff_prov
                        logger.info(
                            f"Handoff provider override: {provider} -> {hp}",
                            extra={"session_id": session_id, "handoff_provider": hp, "handoff_alias": ha}
                        )
                        provider = hp
                        workspace_alias = ha  # reuse variable for alias propagation below

                # Also restore the original alias (e.g., 'gemini-internal') for CLI command selection
                if not workspace_alias:
                    workspace_alias = storage.get_workspace_alias(session_id)
                if workspace_alias:
                    logger.info(f"Alias restored: {workspace_alias}")
                # Set exec_dir override (cwd) for non-CLIExecutor executors (e.g., GeminiExecutor)
                exec_dir_override = storage.get_exec_dir_override(session_id)
                if exec_dir_override:
                    request_model.cwd = exec_dir_override
                    request_model.cwd_mode = "inplace"
                    logger.info(f"Workspace exec_dir override: {exec_dir_override}")
            except Exception as e:
                logger.warning(f"Failed to check workspace/handoff provider/alias: {e}")

        request_model.provider = provider
        request_model.agent_type = provider
        # Set alias on request_model so executors (e.g., GeminiExecutor) use the correct CLI command
        if workspace_alias and not getattr(request_model, "alias", None):
            request_model.alias = workspace_alias

        # Extract model from forwardedProps or body_dict and set on request_model
        forwarded = body_dict.get("forwardedProps") or {}
        model_name = (forwarded.get("model") if isinstance(forwarded, dict) else None) or body_dict.get("model") or ""
        model_name = model_name.strip() if model_name else ""
        if model_name:
            request_model.model = model_name

        # In workspace mode, mark as chat_continue so GeminiExecutor adds --resume latest
        if workspace_provider:
            request_model.run_kind = "chat_continue"

        # ---- /handoff -a inline handling ----
        # When the user sends `/handoff ... -a`, we want to generate the summary
        # *in this very request* instead of deferring to the next message.
        # Parse the slash command, detect auto-summary, replace content with
        # summary prompt and let the request proceed through the LLM path.
        handoff_pending_target = None
        handoff_pending_model = None
        content_stripped = (request_model.content or "").strip()
        if session_id and content_stripped.startswith("/handoff") and " -a" in content_stripped:
            try:
                result = self._try_inline_handoff_auto(
                    session_id, content_stripped, request_model
                )
                if result:
                    handoff_pending_target, handoff_pending_model, _handoff_context_mode = result
            except Exception as e:
                logger.warning(f"Failed to process inline handoff auto-summary: {e}")

        # Check for pending handoff summary set by a *previous* request's /handoff -a
        # (backward compat: if something else set pending_summary, pick it up here)
        if not handoff_pending_target and session_id and not content_stripped.startswith("/"):
            try:
                storage = get_session_storage()
                handoff_pending_target = storage.get_handoff_pending_summary(session_id)
                if handoff_pending_target:
                    # Also retrieve model stored with pending summary
                    handoff_pending_model = storage.get_handoff_model(session_id)
                    logger.info(f"Found pending handoff summary: target={handoff_pending_target}, model={handoff_pending_model}", extra={
                        "session_id": session_id,
                    })
                    pending_context_mode = storage.get_handoff_pending_context_mode(session_id)
                    storage.clear_handoff_pending_summary(session_id)
                    request_model.content = self._prepare_handoff_prompt(
                        session_id, handoff_pending_target, context_mode=pending_context_mode
                    )
            except Exception as e:
                logger.warning(f"Failed to check pending handoff summary: {e}")

        # Check one-time bootstrap context for history->runtime promoted sessions.
        # It is injected into the first follow-up message, then cleared.
        # However, if the session has a stored cli_session_id, the CLI will
        # use --resume <UUID> to restore the original conversation natively,
        # so injecting bootstrap context would be redundant and waste tokens.
        if session_id and not content_stripped.startswith("/"):
            try:
                storage = get_session_storage()
                cli_session_id = storage.get_cli_session_id(session_id)
                if cli_session_id:
                    # CLI will --resume into the original session; consume and
                    # discard bootstrap context so it's not injected later.
                    storage.consume_history_bootstrap_context(session_id)
                    logger.info(
                        "Skipped history bootstrap context injection: CLI session will be resumed via --resume %s",
                        cli_session_id,
                    )
                else:
                    bootstrap_context = storage.consume_history_bootstrap_context(session_id)
                    if bootstrap_context:
                        original_content = request_model.content
                        request_model.content = f"""[History Bootstrap Context]

以下是该会话从本地历史迁移到 Runtime 时注入的上下文摘要：

{bootstrap_context}

---

请基于以上历史上下文继续回答用户问题。

用户的当前请求：
{original_content}"""
                        logger.info(
                            "Injected one-time history bootstrap context",
                            extra={"session_id": session_id, "context_length": len(bootstrap_context)},
                        )
            except Exception as e:
                logger.warning(f"Failed to inject history bootstrap context: {e}")

        # Check for handoff context (agent switching via /handoff command)
        # This overrides provider/alias for this request and injects context
        handoff_context = None
        handoff_target = None
        if session_id:
            try:
                storage = get_session_storage()
                handoff_result = storage.get_handoff_context(session_id)
                if handoff_result:
                    handoff_context, handoff_target = handoff_result
                    if handoff_target:
                        # Read handoff model before clearing
                        handoff_model = storage.get_handoff_model(session_id)

                        logger.info(
                            f"Handoff context found, switching provider",
                            extra={
                                "session_id": session_id,
                                "target": handoff_target,
                                "context_length": len(handoff_context) if handoff_context else 0,
                                "model": handoff_model,
                            }
                        )
                        # Clear handoff context after consuming
                        storage.clear_handoff_context(session_id)

                        # Resolve provider from alias
                        from src.runtime.stores.alias_registry import get_alias_registry
                        alias_registry = get_alias_registry()
                        resolved_provider = alias_registry.resolve(handoff_target)
                        if resolved_provider:
                            provider = resolved_provider
                        else:
                            # Try as direct provider name
                            provider = handoff_target

                        request_model.provider = provider
                        request_model.agent_type = provider
                        request_model.alias = handoff_target

                        # Apply handoff model if specified
                        if handoff_model:
                            request_model.model = handoff_model

                        # Persist the new provider/alias at session level so
                        # subsequent requests keep using the switched provider
                        # (without this, handoff only lasts one request).
                        # Uses independent handoff_provider field so it does
                        # not overwrite workspace_provider set by /workspace -t.
                        try:
                            storage.set_handoff_provider(session_id, provider, handoff_target)
                        except Exception as persist_err:
                            logger.warning(f"Failed to persist handoff provider: {persist_err}")

                        # Inject handoff context into user message (only if non-empty)
                        if handoff_context:
                            original_content = request_model.content
                            request_model.content = f"""[Handoff Context - 从上一个 Agent 切换]

以下是上一个 Agent 传递的上下文摘要：

{handoff_context}

---

请基于以上上下文继续工作。

用户的当前请求：
{original_content}"""
            except Exception as e:
                logger.warning(f"Failed to check handoff context: {e}")
        
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
                request, request_model, agui_request, adapter, exec_user, executor, provider,
                handoff_pending_target=handoff_pending_target,
                handoff_pending_model=handoff_pending_model,
                session_id=session_id,
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
                handoff_pending_target=handoff_pending_target,
                handoff_pending_model=handoff_pending_model,
                session_id=session_id,
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
        handoff_pending_target: Optional[str] = None,
        handoff_pending_model: Optional[str] = None,
        session_id: Optional[str] = None,
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
            summary_text_parts = [] if handoff_pending_target else None
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
                                        # Collect text from AG-UI TEXT_MESSAGE_CONTENT events for handoff summary
                                        if summary_text_parts is not None:
                                            try:
                                                payload_data = json.loads(payload)
                                                if payload_data.get("type") == "TEXT_MESSAGE_CONTENT":
                                                    summary_text_parts.append(payload_data.get("delta", ""))
                                            except Exception:
                                                pass
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
                stream_state["error_occurred"] = True
                await message_queue.put(("error", str(e)))
            finally:
                # Store agent-generated summary and send notification BEFORE signaling done
                if handoff_pending_target and summary_text_parts:
                    summary_text = "".join(summary_text_parts).strip()
                    if summary_text:
                        try:
                            storage = get_session_storage()
                            _session_id = session_id or request_model.session_id or agui_request.threadId
                            storage.set_handoff_context(
                                _session_id,
                                summary_text,
                                handoff_pending_target,
                                model=handoff_pending_model,
                            )
                            logger.info(f"Stored handoff summary ({len(summary_text)} chars) for next switch", extra={
                                "session_id": _session_id,
                                "target": handoff_pending_target,
                            })

                            # Build notification text
                            summary_preview = summary_text[:200] + "..." if len(summary_text) > 200 else summary_text
                            notify_text = (
                                f"\n\n---\n"
                                f"✅ **Agent 切换准备完成**\n\n"
                                f"**目标 Agent**: `{handoff_pending_target}`\n"
                                f"**上下文摘要** ({len(summary_text)} 字符):\n"
                                f"> {summary_preview}\n\n"
                                f"请发送下一条消息，将自动切换到 `{handoff_pending_target}` 并携带以上摘要。"
                            )

                            # Inject as AG-UI TEXT_MESSAGE_CONTENT event into the SSE stream
                            msg_id_for_notify = getattr(getattr(adapter, "state", None), "current_message_id", None)
                            if msg_id_for_notify:
                                notify_payload = {
                                    "type": "TEXT_MESSAGE_CONTENT",
                                    "messageId": msg_id_for_notify,
                                    "delta": notify_text,
                                }
                                notify_sse = f"data: {json.dumps(notify_payload, ensure_ascii=False)}\n\n"
                                stream_state["all_events"].append(notify_sse)
                                await message_queue.put(("events", notify_sse))

                            # Proactively send notification via response_url callback
                            # so enterprise WeChat users can see it (SSE stream alone is
                            # consumed by the intermediate proxy, not the end user)
                            if response_url:
                                try:
                                    await self.callback_handler.send_callback(
                                        response_url,
                                        [notify_text],
                                        {
                                            "user": request_model.user,
                                            "msg_id": msg_id or request_model.msg_id,
                                            "session_id": request_model.session_id,
                                            "content": request_model.content,
                                        },
                                    )
                                    logger.info(
                                        "Handoff notification sent via response_url callback",
                                        extra={
                                            "session_id": _session_id,
                                            "target": handoff_pending_target,
                                        },
                                    )
                                except Exception as cb_err:
                                    logger.warning(
                                        f"Failed to send handoff notification via callback: {cb_err}",
                                        extra={
                                            "session_id": _session_id,
                                            "target": handoff_pending_target,
                                        },
                                    )
                        except Exception as e:
                            logger.error(f"Failed to store handoff summary: {e}")

                stream_state["producer_done"] = True
                await message_queue.put(("done", None))
                
                # Finalize archiver
                if not stream_state.get("error_occurred"):
                    await archiver.on_run_finished()
                
                # Send results via response_url callback.
                # - Timeout / disconnect: send unsent (remaining) events.
                # - Handoff summary flow (normal completion): send ALL events
                #   so the enterprise WeChat user sees the handoff notification.
                if response_url and stream_state["all_events"]:
                    if stream_state["stream_timeout"] or stream_state["client_disconnected"]:
                        callback_events = stream_state["all_events"][stream_state["sent_count"]:]
                        label = "remaining"
                    elif handoff_pending_target:
                        callback_events = stream_state["all_events"]
                        label = "all (handoff)"
                    else:
                        callback_events = None
                        label = None

                    if callback_events:
                        logger.info(
                            f"Sending {label} AG-UI events via callback",
                            extra={
                                "event_count": len(callback_events),
                                "total_count": len(stream_state["all_events"]),
                            }
                        )
                        await self.callback_handler.send_agui_callback(
                            response_url,
                            callback_events,
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

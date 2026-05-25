# -*- coding: utf-8 -*-
"""Stream Handler Service

Handle AG-UI protocol streaming responses (Legacy protocol removed)
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import StreamingResponse

from src.runtime.events.agui import AGUIRequest
from src.providers.base import RequestContext
from ..config import settings
from ..logger import get_logger
from .observability import record_sampled_event, telemetry
from ..providers import get_provider_registry
from ..utils.ids import resolve_session_id
from .callback_handler import CallbackHandler
from .media_downloader import download_images
from .stream_archiver import create_archiver
from .session_storage import get_session_storage
from src.providers.dispatcher import (
    normalize_provider,
    create_all_executors,
    create_adapter,
)
from src.runtime.streaming import StreamOrchestrator

logger = get_logger(__name__)

_background_callback_tasks: set[asyncio.Task] = set()


def _track_background_callback_task(task: asyncio.Task) -> None:
    _background_callback_tasks.add(task)
    task.add_done_callback(_background_callback_tasks.discard)


class StreamHandler:
    """流式处理器 - 统一使用 AG-UI 协议"""

    def __init__(self):
        self._executors = create_all_executors()
        self.callback_handler = CallbackHandler()

    def _get_provider(self, request: Request, body_dict: Dict[str, Any]) -> str:
        # Keep existing resolution behavior, but centralize logic in ProviderRegistry.
        reg = get_provider_registry()
        resolved = reg.resolve_provider(request, body_dict)
        return resolved.name

    def _get_executor(self, provider: str, request_model: RequestContext | None = None):
        """Select executor for this request.

        Uses the centralized :mod:`src.providers.dispatcher` for provider
        normalization.  Slash commands always route to the *claude* executor.
        """
        try:
            content = (getattr(request_model, "content", "") or "").strip()
        except Exception:
            content = ""

        if content.startswith("/"):
            return self._executors["claude"]

        key = normalize_provider(provider)
        return self._executors.get(key, self._executors["claude"])

    def _get_agui_adapter(self, provider: str):
        """Create a fresh AG-UI adapter via the centralized dispatcher."""
        return create_adapter(provider)

    def _default_model_for_provider(self, provider: str) -> Optional[str]:
        provider_key = (provider or "").strip().lower()
        if provider_key != "codebuddy" and not provider_key.startswith("codebuddy-"):
            return None
        configured = getattr(settings, "codebuddy_default_model", "")
        if not isinstance(configured, str):
            configured = ""
        return (
            configured.strip()
            or os.environ.get("CODEBUDDY_DEFAULT_MODEL", "").strip()
            or os.environ.get("AGENT_NEXUS_CODEBUDDY_DEFAULT_MODEL", "").strip()
            or None
        )

    def _apply_model_with_change_detection(
        self,
        request_model: RequestContext,
        session_id: str,
        model_name: str,
        storage,
        source: str,
    ) -> None:
        request_model.model = model_name
        if not session_id:
            return
        try:
            storage_obj = storage or get_session_storage()
            active_model = storage_obj.get_active_model(session_id)
            if active_model != model_name:
                request_model.model_changed = True
                logger.info(
                    f"Model changed by {source}: {active_model} -> {model_name}, will start new CLI session",
                    extra={"session_id": session_id},
                )
            else:
                logger.info(
                    f"Model applied by {source}: {model_name}",
                    extra={"session_id": session_id},
                )
        except Exception as e:
            logger.warning(f"Failed to check active model for {source}: {e}")

    def _sync_execution_binding(
        self,
        storage,
        session_id: str,
        provider: str,
        alias: str,
        exec_user: str,
        work_dir: Optional[str],
        cli_session_id: Optional[str],
        session_kind: str = "chat",
        source_type: str = "chat",
    ) -> tuple[Optional[str], Optional[str], list[str]]:
        """Resolve and persist the canonical execution binding for a chat session."""
        compat_hits: list[str] = []
        existing_binding = None
        if storage and session_id:
            try:
                existing_binding = storage.get_execution_binding(session_id)
            except Exception as e:
                logger.debug(
                    "Execution binding lookup failed",
                    extra={"session_id": session_id, "provider": provider, "error": str(e)},
                )

        if existing_binding and getattr(existing_binding, "cli_session_id", None):
            cli_session_id = existing_binding.cli_session_id
            compat_hits.append("binding_cli_session")
        elif storage and session_id and not cli_session_id:
            try:
                fallback_cli = storage.get_cli_session_id(session_id)
                if fallback_cli:
                    cli_session_id = fallback_cli
                    compat_hits.append("resume_storage_lookup")
                else:
                    compat_hits.append("resume_fallback_to_provider_default")
            except Exception as e:
                logger.debug(
                    "CLI session resume lookup failed",
                    extra={"session_id": session_id, "provider": provider, "error": str(e)},
                )
                compat_hits.append("resume_lookup_error")

        effective_work_dir = work_dir
        if not effective_work_dir and existing_binding and getattr(existing_binding, "work_dir", None):
            effective_work_dir = existing_binding.work_dir
            compat_hits.append("binding_work_dir")

        if storage and session_id:
            try:
                storage.upsert_execution_binding(
                    session_id=session_id,
                    cli_session_id=cli_session_id,
                    provider=provider,
                    alias=alias,
                    exec_user=exec_user,
                    work_dir=effective_work_dir,
                    source_type=getattr(existing_binding, "source_type", None) or source_type,
                    source_session_id=getattr(existing_binding, "source_session_id", None),
                    task_id=getattr(existing_binding, "task_id", None),
                    session_kind=session_kind,
                )
            except Exception as e:
                logger.warning(
                    "Failed to persist execution binding",
                    extra={"session_id": session_id, "provider": provider, "error": str(e)},
                )
                compat_hits.append("binding_persist_failed")

        telemetry.increment("stream_handler.binding_resolved")
        for hit in compat_hits:
            telemetry.increment(f"stream_handler.compat.{hit}")
        record_sampled_event(
            "stream_handler.binding_resolved",
            {
                "session_id": session_id,
                "provider": provider,
                "alias": alias,
                "exec_user": exec_user,
                "work_dir": effective_work_dir,
                "cli_session_id_present": bool(cli_session_id),
                "compat_hits": compat_hits,
            },
        )
        return cli_session_id, effective_work_dir, compat_hits

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
        """Build switch prompt by fetching conversation history from Redis.

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

    def _set_request_content(self, request_model: RequestContext, content: str) -> None:
        """Update prompt text while preserving non-text AG-UI media parts."""
        request_model.content = content
        media_parts = [
            part
            for part in (getattr(request_model, "content_parts", None) or [])
            if isinstance(part, dict) and part.get("type") != "text"
        ]
        request_model.content_parts = (
            [{"type": "text", "content": content}] + media_parts
            if media_parts
            else []
        )

    async def _localize_agui_image_parts(
        self,
        request_model: RequestContext,
        session_id: str,
        exec_user: str,
    ) -> None:
        """Download AG-UI image URLs so the CLI receives local image paths."""
        content_parts = [
            part
            for part in (getattr(request_model, "content_parts", None) or [])
            if isinstance(part, dict)
        ]
        image_items = [
            {"url": part["url"], "mime_type": part.get("mime_type")}
            for part in content_parts
            if part.get("type") == "image"
            and isinstance(part.get("url"), str)
            and part["url"].startswith(("http://", "https://"))
        ]
        if not image_items:
            return

        session_dir = Path(settings.user_home_base) / exec_user / ".nexus" / "sessions" / session_id
        dest_dir: str | None = None
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            dest_dir = str(session_dir)
        except OSError as exc:
            logger.warning(
                f"AG-UI image session directory unavailable, using fallback: {exc}",
                extra={"session_id": session_id},
            )

        try:
            image_paths = await download_images(
                image_items,
                dest_dir=dest_dir,
                session_id=session_id,
            )
        except Exception as exc:
            logger.warning(
                f"AG-UI image download failed: {exc}",
                extra={"session_id": session_id},
            )
            return

        if not image_paths:
            return

        url_to_path = {
            item["url"]: path
            for item, path in zip(image_items, image_paths)
        }
        localized_parts: list[dict[str, Any]] = []
        for part in content_parts:
            if part.get("type") == "image" and part.get("url") in url_to_path:
                localized = dict(part)
                localized["path"] = url_to_path[part["url"]]
                localized_parts.append(localized)
            else:
                localized_parts.append(part)

        request_model.content_parts = localized_parts
        existing_paths = [
            path
            for path in (getattr(request_model, "image_paths", None) or [])
            if not (isinstance(path, str) and path.startswith(("http://", "https://")))
        ]
        request_model.image_paths = existing_paths + image_paths
        logger.info(
            f"AG-UI downloaded {len(image_paths)} image(s)",
            extra={"session_id": session_id},
        )

    def _try_inline_handoff_auto(
        self,
        session_id: str,
        content: str,
        request_model: RequestContext,
    ) -> tuple[str, str | None, str] | None:
        """Try to handle ``/switch ... -a`` inline in the current request.

        If the slash command is a valid ``/switch -a`` (auto-summary), this
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

        if parsed.cmd != "switch":
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
            "Inline /switch -a detected, generating summary immediately",
            extra={
                "session_id": session_id,
                "target": effective_alias,
            },
        )

        self._set_request_content(
            request_model,
            self._prepare_handoff_prompt(session_id, effective_alias, context_mode=context_mode),
        )
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
        
        # Normalize session_id: AG-UI 可能传入空 threadId，需统一补齐，避免写入空会话
        resolved_session_id = resolve_session_id(agui_request.threadId)

        request_content_parts = (
            list(agui_request.content_parts)
            if agui_request.content_parts
            else agui_request.get_user_content_parts()
        )
        request_model = RequestContext(
            content=agui_request.get_user_content(),
            user=agui_request.get_username() or "anonymous",
            session_id=resolved_session_id,
            exec_user=exec_user,
            cwd=agui_request.cwd or body_dict.get("cwd"),
            cwd_mode=agui_request.cwd_mode or body_dict.get("cwd_mode") or "",
            run_kind=agui_request.run_kind or body_dict.get("run_kind") or "",
            alias=agui_request.get_alias(),
            cli_session_id=agui_request.cli_session_id or body_dict.get("cli_session_id") or None,
            msg_id=agui_request.get_msg_id() or agui_request.runId,
            response_url=agui_request.get_response_url() or "",
            image_paths=list(agui_request.image_paths or body_dict.get("image_paths") or []),
            file_paths=list(agui_request.file_paths or body_dict.get("file_paths") or []),
            content_parts=request_content_parts,
        )
        await self._localize_agui_image_parts(request_model, resolved_session_id, exec_user)

        requested_cwd_mode = str(body_dict.get("cwd_mode") or getattr(request_model, "cwd_mode", "") or "").strip()
        requested_work_dir = str(body_dict.get("cwd") or getattr(request_model, "cwd", "") or "").strip()
        if requested_work_dir and requested_cwd_mode == "inplace":
            request_model.cwd = requested_work_dir
            request_model.cwd_mode = "inplace"
        agui_request.threadId = resolved_session_id

        # In /workspace -t mode, the workspace provider (stored in Redis session)
        # should override the request-level provider for executor and adapter selection.
        # Without this, a workspace using gemini would get a Claude executor/adapter.
        # Priority: session-level exec_user/provider overrides > workspace_provider > handoff_provider > request default
        session_id = resolved_session_id
        workspace_provider = None
        workspace_alias = None
        storage = None
        if session_id:
            try:
                storage = get_session_storage()

                session_exec_user = storage.get_session_exec_user(session_id)
                if session_exec_user and session_exec_user != exec_user:
                    logger.info(
                        f"Session exec_user override: {exec_user} -> {session_exec_user}",
                        extra={"session_id": session_id, "session_exec_user": session_exec_user},
                    )
                    exec_user = session_exec_user

                workspace_provider = storage.get_workspace_provider(session_id)
                if workspace_provider:
                    logger.info(
                        f"Workspace provider override for executor/adapter selection: {provider} -> {workspace_provider}",
                        extra={"session_id": session_id, "workspace_provider": workspace_provider}
                    )
                    provider = workspace_provider
                else:
                    # No workspace provider — check for switch provider
                    switch_prov = storage.get_handoff_provider(session_id)
                    if switch_prov:
                        hp, ha = switch_prov
                        logger.info(
                            f"Switch provider override: {provider} -> {hp}",
                            extra={"session_id": session_id, "switch_provider": hp, "switch_alias": ha}
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

                effective_work_dir = exec_dir_override or (requested_work_dir if requested_cwd_mode == "inplace" else (request_model.cwd if getattr(request_model, "cwd_mode", "") == "inplace" else None))
                binding_cli_session_id, binding_work_dir, binding_compat_hits = self._sync_execution_binding(
                    storage=storage,
                    session_id=session_id,
                    provider=provider,
                    alias=workspace_alias or provider,
                    exec_user=exec_user,
                    work_dir=effective_work_dir,
                    cli_session_id=getattr(request_model, "cli_session_id", None),
                    session_kind="chat",
                    source_type="chat",
                )
                if binding_cli_session_id:
                    request_model.cli_session_id = binding_cli_session_id
                if binding_work_dir and not effective_work_dir:
                    request_model.cwd = binding_work_dir
                    request_model.cwd_mode = "inplace"
                logger.debug(
                    "Execution binding synced for AG-UI session",
                    extra={
                        "session_id": session_id,
                        "provider": provider,
                        "alias": workspace_alias or provider,
                        "exec_user": exec_user,
                        "cli_session_id_present": bool(binding_cli_session_id),
                        "compat_hits": binding_compat_hits,
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to check workspace/switch provider/alias/exec_user: {e}")

        request_model.exec_user = exec_user
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
            self._apply_model_with_change_detection(request_model, session_id, model_name, storage, "request")

        # Apply persistent model override from /switch -m (if no explicit model in request)
        if session_id and not model_name:
            try:
                storage = storage or get_session_storage()
                model_override = storage.get_model_override(session_id)
                if model_override:
                    self._apply_model_with_change_detection(request_model, session_id, model_override, storage, "session")
                    model_name = model_override
            except Exception as e:
                logger.warning(f"Failed to read model override: {e}")

        if not model_name:
            default_model = self._default_model_for_provider(provider)
            if default_model:
                self._apply_model_with_change_detection(request_model, session_id, default_model, storage, "provider-default")
                model_name = default_model

        # In workspace mode, mark as chat_continue so GeminiExecutor adds --resume latest
        if workspace_provider:
            request_model.run_kind = "chat_continue"

        # ---- /switch -a inline handling ----
        # When the user sends `/switch ... -a`, we want to generate the summary
        # *in this very request* instead of deferring to the next message.
        # Parse the slash command, detect auto-summary, replace content with
        # summary prompt and let the request proceed through the LLM path.
        handoff_pending_target = None
        handoff_pending_model = None
        content_stripped = (request_model.content or "").strip()
        if session_id and content_stripped.startswith("/switch") and " -a" in content_stripped:
            try:
                result = self._try_inline_handoff_auto(
                    session_id, content_stripped, request_model
                )
                if result:
                    handoff_pending_target, handoff_pending_model, _handoff_context_mode = result
            except Exception as e:
                logger.warning(f"Failed to process inline switch auto-summary: {e}")

        # Check for pending switch summary set by a *previous* request's /switch -a
        # (backward compat: if something else set pending_summary, pick it up here)
        if not handoff_pending_target and session_id and not content_stripped.startswith("/"):
            try:
                storage = get_session_storage()
                handoff_pending_target = storage.get_handoff_pending_summary(session_id)
                if handoff_pending_target:
                    # Also retrieve model stored with pending summary
                    handoff_pending_model = storage.get_handoff_model(session_id)
                    logger.info(f"Found pending switch summary: target={handoff_pending_target}, model={handoff_pending_model}", extra={
                        "session_id": session_id,
                    })
                    pending_context_mode = storage.get_handoff_pending_context_mode(session_id)
                    storage.clear_handoff_pending_summary(session_id)
                    self._set_request_content(
                        request_model,
                        self._prepare_handoff_prompt(
                            session_id, handoff_pending_target, context_mode=pending_context_mode
                        ),
                    )
            except Exception as e:
                logger.warning(f"Failed to check pending handoff summary: {e}")

        # Check one-time bootstrap context for history->runtime promoted sessions.
        # It is injected into the first follow-up message, then cleared.
        # However, if the session has a stored cli_session_id, the CLI will
        # use native provider resume flags to restore the original conversation,
        # so injecting bootstrap context would be redundant and waste tokens.
        if session_id and not content_stripped.startswith("/"):
            try:
                storage = get_session_storage()
                cli_session_id = storage.get_cli_session_id(session_id)
                if cli_session_id:
                    # CLI will resume into the original session; consume and
                    # discard bootstrap context so it's not injected later.
                    storage.consume_history_bootstrap_context(session_id)
                    logger.info(
                        "Skipped history bootstrap context injection: CLI session will be resumed natively: %s",
                        cli_session_id,
                    )
                else:
                    bootstrap_context = storage.consume_history_bootstrap_context(session_id)
                    if bootstrap_context:
                        original_content = request_model.content
                        self._set_request_content(request_model, f"""[History Bootstrap Context]

以下是该会话从本地历史迁移到 Runtime 时注入的上下文摘要：

{bootstrap_context}

---

请基于以上历史上下文继续回答用户问题。

用户的当前请求：
{original_content}""")
                        logger.info(
                            "Injected one-time history bootstrap context",
                            extra={"session_id": session_id, "context_length": len(bootstrap_context)},
                        )
            except Exception as e:
                logger.warning(f"Failed to inject history bootstrap context: {e}")

        # Check for switch context (agent switching via /switch command)
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
                        # Read switch model before clearing
                        handoff_model = storage.get_handoff_model(session_id)

                        logger.info(
                            "Switch context found, switching provider",
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

                        # Apply switch model if specified
                        if handoff_model:
                            request_model.model = handoff_model

                        # Persist the new provider/alias at session level so
                        # subsequent requests keep using the switched provider
                        # (without this, handoff only lasts one request).
                        # Uses independent handoff_provider field so it does
                        # not overwrite workspace_provider set by /workspace -t.
                        try:
                            storage.set_handoff_provider(session_id, provider, handoff_target)
                            # Provider switch resets model_override (model is bound to provider)
                            storage.clear_model_override(session_id)
                        except Exception as persist_err:
                            logger.warning(f"Failed to persist switch provider: {persist_err}")

                        # Inject handoff context into user message (only if non-empty)
                        if handoff_context:
                            original_content = request_model.content
                            self._set_request_content(request_model, f"""[Handoff Context - 从上一个 Agent 切换]

以下是上一个 Agent 传递的上下文摘要：

{handoff_context}

---

请基于以上上下文继续工作。

用户的当前请求：
{original_content}""")
            except Exception as e:
                logger.warning(f"Failed to check switch context: {e}")
        
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
        has_user_input = bool(
            (request_model.content or "").strip()
            or getattr(request_model, "content_parts", None)
            or getattr(request_model, "image_paths", None)
            or getattr(request_model, "file_paths", None)
        )
        if not has_user_input:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Missing required field: content (or messages for AG-UI)"
            )

        if session_id:
            def _remember_cli_session_id(cli_session_id: str) -> None:
                cli_session_id = (cli_session_id or "").strip()
                if not cli_session_id:
                    return
                try:
                    storage_obj = storage or get_session_storage()
                    storage_obj.set_cli_session_id(session_id, cli_session_id)
                    active_model = (getattr(request_model, "model", None) or "").strip()
                    if active_model:
                        storage_obj.set_active_model(session_id, active_model)
                    logger.debug(
                        "Saved cli_session_id from provider stream",
                        extra={"session_id": session_id, "cli_session_id": cli_session_id},
                    )
                except Exception:
                    logger.debug("Failed to save cli_session_id from provider stream", exc_info=True)

            request_model.metadata["on_cli_session_id"] = _remember_cli_session_id
        
        # 如果有 response_url 且 response_url_callback_enabled 已启用，进入超时回调模式
        # 默认关闭：即使有 response_url 也走标准 AG-UI 流式处理，不主动断连、不主动通告
        if response_url and settings.response_url_callback_enabled:
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
        request_model: RequestContext,
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
        
        在同步窗口内发送后台化提示并结束 SSE 流，
        后台继续收集 CLI 回复，完成后通过 response_url 发送剩余结果。
        """
        try:
            stream_timeout = float(
                getattr(settings, "response_url_stream_timeout_seconds", 25.0) or 25.0
            )
        except (TypeError, ValueError):
            stream_timeout = 25.0
        if stream_timeout <= 0:
            stream_timeout = 25.0
        try:
            progress_notice_limit = int(getattr(settings, "response_url_stream_progress_notices", 2) or 0)
        except (TypeError, ValueError):
            progress_notice_limit = 2
        if progress_notice_limit < 0:
            progress_notice_limit = 0
        
        response_url = agui_request.get_response_url()
        msg_id = agui_request.get_msg_id()
        
        # Create archiver for session storage
        username = exec_user or request_model.user or "anonymous"
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
            "progress_notices_sent": 0,
            "stream_timeout": False,
            "all_events": [],      # 所有 AG-UI 事件
            "sent_count": 0,       # 已发送的事件数
            "producer_done": False,
            "callback_sent": False,
            "start_time": time.time(),
        }
        has_media_input = bool(
            getattr(request_model, "image_paths", None)
            or getattr(request_model, "file_paths", None)
            or any(
                isinstance(part, dict) and part.get("type") != "text"
                for part in (getattr(request_model, "content_parts", None) or [])
            )
        )

        def build_background_notice_events() -> list[str]:
            from src.runtime.events.agui import (
                MessageRole,
                RunFinishedEvent,
                TextMessageContentEvent,
                TextMessageEndEvent,
                TextMessageStartEvent,
            )

            timeout_msg = "\n\n---\n⏰ **处理时间较长，已转为后台处理**\n\n已连续等待多轮仍未完成，为避免连接超时，已转为后台继续处理。处理完成后会将完整结果发送给您，请耐心等待。\n"
            events: list[str] = []
            if not adapter.state.message_started:
                adapter.state.current_message_id = f"timeout-msg-{agui_request.runId}"
                adapter.state.message_started = True
                events.append(
                    TextMessageStartEvent(
                        messageId=adapter.state.current_message_id,
                        role=MessageRole.ASSISTANT,
                    ).to_sse()
                )
            events.append(
                TextMessageContentEvent(
                    messageId=adapter.state.current_message_id,
                    delta=timeout_msg,
                ).to_sse()
            )
            events.append(TextMessageEndEvent(messageId=adapter.state.current_message_id).to_sse())
            events.append(
                RunFinishedEvent(
                    threadId=agui_request.threadId,
                    runId=agui_request.runId,
                ).to_sse()
            )
            return events
        
        def build_progress_notice_events() -> list[str]:
            from src.runtime.events.agui import (
                MessageRole,
                TextMessageContentEvent,
                TextMessageEndEvent,
                TextMessageStartEvent,
            )

            notice_index = int(stream_state["progress_notices_sent"])
            waited_seconds = int(stream_timeout * notice_index)
            subject = "图片" if has_media_input else "请求"
            message_id = f"progress-msg-{agui_request.runId}-{notice_index}"
            progress_msg = (
                f"\n\n---\n⏳ **{subject}还在处理中**\n\n"
                f"已处理约 {waited_seconds} 秒，系统仍在继续执行。"
                f"有结果会立即返回；若连续多轮仍未完成，会自动转为后台处理。\n"
            )
            return [
                TextMessageStartEvent(
                    messageId=message_id,
                    role=MessageRole.ASSISTANT,
                ).to_sse(),
                TextMessageContentEvent(
                    messageId=message_id,
                    delta=progress_msg,
                ).to_sse(),
                TextMessageEndEvent(messageId=message_id).to_sse(),
            ]

        async def send_callback_events_once() -> None:
            if not response_url or stream_state.get("callback_sent"):
                return

            if stream_state["stream_timeout"] or stream_state["client_disconnected"]:
                callback_events = stream_state["all_events"][stream_state["sent_count"]:]
                label = "remaining"
            elif handoff_pending_target:
                callback_events = stream_state["all_events"]
                label = "all (switch)"
            else:
                return

            if not callback_events:
                return

            stream_state["callback_sent"] = True
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
                        # Collect text from AG-UI TEXT_MESSAGE_CONTENT events for switch summary
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
                            
                            if not (stream_state["stream_timeout"] or stream_state["client_disconnected"]):
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
                            logger.info(f"Stored switch summary ({len(summary_text)} chars) for next switch", extra={
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
                                        "Switch notification sent via response_url callback",
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
                            logger.error(f"Failed to store switch summary: {e}")

                stream_state["producer_done"] = True
                await message_queue.put(("done", None))
                
                # Finalize archiver
                if not stream_state.get("error_occurred"):
                    await archiver.on_run_finished()
                
                # Send results via response_url callback.
                # Producer completion and SSE timeout can race, so both sides call
                # the same one-shot helper.
                await send_callback_events_once()
        
        producer_task = asyncio.create_task(producer())
        _track_background_callback_task(producer_task)
        
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
                    next_notice_deadline = stream_timeout * (
                        int(stream_state["progress_notices_sent"]) + 1
                    )
                    
                    # 超时检查
                    if elapsed_time >= next_notice_deadline:
                        if int(stream_state["progress_notices_sent"]) < progress_notice_limit:
                            stream_state["progress_notices_sent"] = (
                                int(stream_state["progress_notices_sent"]) + 1
                            )
                            logger.info(
                                "AG-UI stream progress notice emitted before background fallback",
                                extra={"notice_count": stream_state["progress_notices_sent"]},
                            )
                            for notice_event in build_progress_notice_events():
                                yield notice_event
                            continue

                        logger.info("AG-UI stream progress notices exhausted, switching to background processing")
                        stream_state["stream_timeout"] = True
                        callback_task = asyncio.create_task(send_callback_events_once())
                        _track_background_callback_task(callback_task)
                        
                        for notice_event in build_background_notice_events():
                            yield notice_event
                        return
                    
                    # 检查客户端断开
                    if await request.is_disconnected():
                        logger.info("AG-UI client disconnected during streaming")
                        stream_state["client_disconnected"] = True
                        callback_task = asyncio.create_task(send_callback_events_once())
                        _track_background_callback_task(callback_task)
                        return
                    
                    # 获取消息；等待时间不能越过后台化阈值，否则慢请求会错过
                    # response_url 兜底窗口。
                    queue_wait_timeout = min(1.0, max(0.0, next_notice_deadline - elapsed_time))
                    if queue_wait_timeout <= 0:
                        continue
                    try:
                        msg_type, msg_data = await asyncio.wait_for(
                            message_queue.get(),
                            timeout=queue_wait_timeout
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

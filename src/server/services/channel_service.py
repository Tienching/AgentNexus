"""Channel 服务 - 集成多平台消息通道

将 channels 模块集成到 virtual-human-sdk 服务中，
实现 Telegram、Slack 等平台的消息接收和 AI 回复。

Supports non-blocking AI processing with real-time progress updates
via the unified notification system.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from ..config import settings
from ..logger import get_logger
from src.channels import (
    ChannelManager,
    InboundMessage,
    OutboundMessage,
    ChannelConfig,
    TelegramConfig,
    SlackConfig,
    DiscordConfig,
    WhatsAppConfig,
    SignalConfig,
    FeishuConfig,
    WeComConfig,
)
from .notification import (
    NotificationTarget,
    UnifiedNotificationHandler,
    get_notification_handler,
)
from src.runtime.stores.session_storage import get_session_storage
from src.runtime.models.session import StoredMessage, MessageStatus
from .media_downloader import download_images, download_files

logger = get_logger(__name__)

CHANNEL_MAX_LENGTH = {
    "telegram": 4000,
    "discord": 1900,
    "slack": 3800,
    "feishu": 3800,
    "wecom": 20480,
    "whatsapp": 65000,
    "signal": 65000,
}

# Progress update interval (seconds) — how often to edit the placeholder message
PROGRESS_UPDATE_INTERVAL = 8

# Type alias for the optional on_text_delta callback
OnTextDelta = Callable[[str], Coroutine[Any, Any, None]]


@dataclass
class ExecutorResult:
    """Unified result from _consume_executor_events()."""
    final_content: str = ""
    is_error: bool = False
    tool_summaries: List[str] = field(default_factory=list)
    tool_call_count: int = 0
    collected_text_parts: List[str] = field(default_factory=list)


# 全局 channel 服务实例
_channel_service: Optional["ChannelService"] = None


class ChannelService:
    """Channel 服务
    
    管理多平台消息通道，将收到的消息转发给 AI 处理，
    并将 AI 回复发送回用户。

    Uses the unified notification system for progress updates and
    completion notifications so users don't stare at a blank screen.
    """
    
    def __init__(self):
        self.manager: Optional[ChannelManager] = None
        self._executor = None  # AI 执行器
        self._active_sessions: Dict[str, Dict[str, Any]] = {}
        self._background_tasks: Dict[str, asyncio.Task] = {}
        
    async def initialize(self) -> bool:
        """初始化 channel 服务
        
        从 settings 读取配置并初始化各个通道。
        """
        configs = {}
        
        # Telegram 配置
        if settings.telegram_bot_token:
            try:
                allowed_list = [
                    u.strip() 
                    for u in settings.telegram_allowed_users.split(",") 
                    if u.strip()
                ]
                
                configs["telegram"] = TelegramConfig(
                    name="telegram",
                    bot_token=settings.telegram_bot_token,
                    allowed_users=allowed_list,
                )
                logger.info("Telegram channel configured")
            except Exception as e:
                logger.error(f"Failed to configure Telegram: {e}")
        
        # Slack 配置
        if settings.slack_bot_token and settings.slack_app_token:
            try:
                configs["slack"] = SlackConfig(
                    name="slack",
                    bot_token=settings.slack_bot_token,
                    app_token=settings.slack_app_token,
                    socket_mode=True,
                )
                logger.info("Slack channel configured")
            except Exception as e:
                logger.error(f"Failed to configure Slack: {e}")
        
        # Discord 配置
        if settings.discord_bot_token:
            try:
                configs["discord"] = DiscordConfig(
                    name="discord",
                    bot_token=settings.discord_bot_token,
                )
                logger.info("Discord channel configured")
            except Exception as e:
                logger.error(f"Failed to configure Discord: {e}")

        # 飞书 配置
        if settings.feishu_app_id and settings.feishu_app_secret:
            try:
                configs["feishu"] = FeishuConfig(
                    name="feishu",
                    app_id=settings.feishu_app_id,
                    app_secret=settings.feishu_app_secret,
                    verification_token=settings.feishu_verification_token,
                    encrypt_key=settings.feishu_encrypt_key,
                    domain=settings.feishu_domain,
                )
                logger.info("Feishu channel configured")
            except Exception as e:
                logger.error(f"Failed to configure Feishu: {e}")

        # WhatsApp 配置
        if settings.whatsapp_bridge_url:
            try:
                configs["whatsapp"] = WhatsAppConfig(
                    name="whatsapp",
                    bridge_url=settings.whatsapp_bridge_url,
                    bridge_auth_token=settings.whatsapp_bridge_auth_token,
                    session_name=settings.whatsapp_session_name or "default",
                )
                logger.info("WhatsApp channel configured")
            except Exception as e:
                logger.error(f"Failed to configure WhatsApp: {e}")

        # Signal 配置
        if settings.signal_phone_number:
            try:
                configs["signal"] = SignalConfig(
                    name="signal",
                    api_url=settings.signal_api_url,
                    phone_number=settings.signal_phone_number,
                )
                logger.info("Signal channel configured")
            except Exception as e:
                logger.error(f"Failed to configure Signal: {e}")

        # 企业微信智能机器人配置
        if settings.wecom_token and settings.wecom_encoding_aes_key:
            try:
                configs["wecom"] = WeComConfig(
                    name="wecom",
                    token=settings.wecom_token,
                    encoding_aes_key=settings.wecom_encoding_aes_key,
                    aibot_id=settings.wecom_aibot_id,
                )
                logger.info("WeCom AI Bot channel configured")
            except Exception as e:
                logger.error(f"Failed to configure WeCom: {e}")
        
        if not configs:
            logger.info("No channel configured, channel service disabled")
            return False
        
        # 创建管理器
        self.manager = ChannelManager(configs)
        self.manager.on_message = self._handle_message
        self.manager.on_error = self._handle_error
        
        return True
    
    async def start(self) -> None:
        """启动所有通道"""
        if not self.manager:
            return
            
        await self.manager.initialize()
        await self.manager.start()
        logger.info(f"Channel service started with {len(self.manager.channels)} channel(s)")
    
    async def stop(self) -> None:
        """停止所有通道"""
        # Cancel background processing tasks
        for key, task in list(self._background_tasks.items()):
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(
                *self._background_tasks.values(), return_exceptions=True
            )
            self._background_tasks.clear()

        if self.manager:
            await self.manager.stop()
            logger.info("Channel service stopped")

    # ------------------------------------------------------------------
    # Shared helpers — build request & consume executor events
    # ------------------------------------------------------------------

    async def _build_request(
        self,
        message: InboundMessage,
        session_id: str,
    ):
        """Build a RequestModel from an InboundMessage (shared across all channels).

        Handles: image/file download, model/provider overrides, model_changed detection.
        """
        from ..services import CLIExecutor  # noqa: F811
        from ..models import RequestModel

        exec_user = settings.exec_user or "ubuntu"
        session_dir = Path(settings.user_home_base) / exec_user / ".nexus" / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Download media
        image_paths: list[str] = []
        file_paths: list[str] = []
        _decrypt_fn = None
        if message.channel == "wecom" and self.manager:
            _ch = self.manager.get_channel("wecom")
            _crypto = getattr(_ch, "_crypto", None) if _ch else None
            _decrypt_fn = _crypto.decrypt_file if _crypto else None
        if message.media:
            image_items = [
                {"url": m.url, "mime_type": m.mime_type}
                for m in message.media
                if m.url and (not m.mime_type or "image" in (m.mime_type or ""))
            ]
            file_items = [
                {"url": m.url, "file_name": m.file_name}
                for m in message.media
                if m.url and m.mime_type and "image" not in (m.mime_type or "")
            ]
            if image_items:
                try:
                    image_paths = await download_images(image_items, dest_dir=str(session_dir), session_id=session_id, decrypt_fn=_decrypt_fn)
                    if image_paths:
                        logger.info(f"[{message.channel}] Downloaded {len(image_paths)} image(s)", extra={"session_id": session_id})
                except Exception as e:
                    logger.warning(f"[{message.channel}] Failed to download images: {e}")
            if file_items:
                try:
                    file_paths = await download_files(file_items, dest_dir=str(session_dir), session_id=session_id, decrypt_fn=_decrypt_fn)
                    if file_paths:
                        logger.info(f"[{message.channel}] Downloaded {len(file_paths)} file(s)", extra={"session_id": session_id})
                except Exception as e:
                    logger.warning(f"[{message.channel}] Failed to download files: {e}")

        content = message.content
        if not content.strip() and image_paths:
            content = ""

        request = RequestModel(
            content=content,
            user=f"{message.channel}_{message.sender_id}",
            session_id=session_id,
            msg_id=f"msg-{uuid.uuid4().hex[:8]}",
            image_paths=image_paths,
            file_paths=file_paths,
        )

        # Apply model / provider overrides (from /switch)
        try:
            storage = get_session_storage()
            model_override = storage.get_model_override(session_id)
            if model_override:
                request.model = model_override
                active_model = storage.get_active_model(session_id)
                if active_model != model_override:
                    request.model_changed = True
                    logger.info(
                        f"[{message.channel}] Model changed: {active_model} -> {model_override}",
                        extra={"session_id": session_id},
                    )
                else:
                    logger.info(
                        f"[{message.channel}] Model override applied: {model_override}",
                        extra={"session_id": session_id},
                    )
            handoff_prov = storage.get_handoff_provider(session_id)
            if handoff_prov:
                hp_provider, hp_alias = handoff_prov
                request.provider = hp_provider
                request.alias = hp_alias
                logger.info(
                    f"[{message.channel}] Provider override: provider={hp_provider}, alias={hp_alias}",
                    extra={"session_id": session_id},
                )
        except Exception as e:
            logger.warning(f"[{message.channel}] Failed to read session overrides: {e}")

        return request

    async def _consume_executor_events(
        self,
        message: InboundMessage,
        session_id: str,
        request,
        *,
        on_text_delta: Optional[OnTextDelta] = None,
        on_tool_summary: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None,
    ) -> ExecutorResult:
        """Consume raw executor events — **single source of truth** for all channels.

        Responsibilities:
        1. Drive ``executor.execute()`` iteration
        2. Parse stream_event / assistant / result event types
        3. Track tool calls (AG-UI + legacy)
        4. Deduplicate text (has_streamed_text flag)
        5. Archive user + assistant messages to Redis on ``result``

        Channel-specific behaviour is injected via callbacks:
        - *on_text_delta(text)*: called for each incremental text chunk (wecom writes to StreamBuffer)
        - *on_tool_summary(summary)*: called when a tool call is finalised (wecom appends to StreamBuffer)
        """
        from ..services import CLIExecutor

        executor = CLIExecutor(config=settings)
        exec_user = settings.exec_user or "ubuntu"
        timeout = settings.cli_timeout or 120

        result = ExecutorResult()
        tool_block_buffer: Dict[int, Dict[str, str]] = {}
        agui_tool_buffer: Dict[str, Dict[str, str]] = {}
        has_streamed_text = False

        try:
            async with asyncio.timeout(timeout):
                async for output in executor.execute(request, exec_user=exec_user, output_format="raw"):
                    if not output:
                        continue
                    try:
                        data = json.loads(output)
                        if not isinstance(data, dict):
                            continue
                    except json.JSONDecodeError:
                        continue

                    event_type = data.get("type", "")

                    # --- stream_event ---
                    if event_type == "stream_event":
                        event = data.get("event", {})
                        evt_type = event.get("type", "")

                        if evt_type == "content_block_delta":
                            delta = event.get("delta", {})
                            delta_type = delta.get("type", "")
                            if delta_type == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    result.collected_text_parts.append(text)
                                    has_streamed_text = True
                                    if on_text_delta:
                                        await on_text_delta(text)
                            elif delta_type == "input_json_delta":
                                index = event.get("index", 0)
                                partial = delta.get("partial_json", "")
                                if partial and index in tool_block_buffer:
                                    tool_block_buffer[index]["json_buf"] += partial

                        # AG-UI tool tracking
                        elif evt_type == "TOOL_CALL_START":
                            tool_name = event.get("toolCallName", "unknown")
                            tool_id = event.get("toolCallId", "")
                            result.tool_call_count += 1
                            if tool_id:
                                agui_tool_buffer[tool_id] = {"name": tool_name, "args": ""}

                        elif evt_type == "TOOL_CALL_ARGS":
                            tool_id = event.get("toolCallId", "")
                            delta_str = event.get("delta", "")
                            if tool_id and delta_str and tool_id in agui_tool_buffer:
                                agui_tool_buffer[tool_id]["args"] += delta_str

                        elif evt_type in ("TOOL_CALL_END", "TOOL_CALL_RESULT"):
                            tool_id = event.get("toolCallId", "")
                            if tool_id and tool_id in agui_tool_buffer:
                                entry = agui_tool_buffer.pop(tool_id)
                                params_obj = {}
                                if entry["args"]:
                                    try:
                                        params_obj = json.loads(entry["args"])
                                    except (json.JSONDecodeError, TypeError):
                                        pass
                                display = self._get_tool_display_name(entry["name"], params_obj)
                                summary = f"🔧 `{display}`"
                                result.tool_summaries.append(summary)
                                if on_tool_summary:
                                    await on_tool_summary(summary)

                        # Legacy tool blocks
                        elif evt_type == "content_block_start":
                            content_block = event.get("content_block", {})
                            if content_block.get("type") == "tool_use":
                                tool_name = content_block.get("name", "unknown")
                                index = event.get("index", 0)
                                result.tool_call_count += 1
                                tool_block_buffer[index] = {"name": tool_name, "json_buf": ""}

                        elif evt_type == "content_block_stop":
                            index = event.get("index", 0)
                            if index in tool_block_buffer:
                                entry = tool_block_buffer.pop(index)
                                params_obj = {}
                                if entry["json_buf"]:
                                    try:
                                        params_obj = json.loads(entry["json_buf"])
                                    except (json.JSONDecodeError, TypeError):
                                        pass
                                display = self._get_tool_display_name(entry["name"], params_obj)
                                summary = f"🔧 `{display}`"
                                result.tool_summaries.append(summary)
                                if on_tool_summary:
                                    await on_tool_summary(summary)

                    # --- assistant event (skip if already streamed) ---
                    elif event_type == "assistant":
                        if not has_streamed_text:
                            msg = data.get("message", {})
                            msg_content = msg.get("content", [])
                            if isinstance(msg_content, list):
                                for item in msg_content:
                                    if isinstance(item, dict) and item.get("type") == "text":
                                        text = item.get("text", "")
                                        if text:
                                            result.collected_text_parts.append(text)
                                            if on_text_delta:
                                                await on_text_delta(text)

                    # --- result event ---
                    elif event_type == "result":
                        is_error = data.get("is_error", False)
                        content = data.get("content", "") or data.get("result", "")
                        if not content and is_error:
                            errors = data.get("errors", [])
                            if errors:
                                content = "❌ " + "; ".join(str(e) for e in errors[:3])
                        result.final_content = content or ""
                        result.is_error = is_error
                        break  # result is terminal

        except TimeoutError:
            logger.error(f"[{message.channel}] AI execution timed out after {timeout}s")
            result.is_error = True
            result.final_content = ""
        except Exception as e:
            logger.error(f"[{message.channel}] AI processing error: {e}", exc_info=True)
            result.is_error = True
            result.final_content = f"❌ 处理出错：{str(e)[:200]}"

        # --- Unified archival: store user + assistant messages to Redis ---
        final = result.final_content or "".join(result.collected_text_parts).strip()
        if final:
            try:
                storage = get_session_storage()
                storage.add_session_message(
                    session_id,
                    StoredMessage(
                        id=f"ch-u-{uuid.uuid4().hex[:8]}",
                        role="user",
                        content=message.content or "",
                        status=MessageStatus.COMPLETE,
                    ),
                )
                storage.add_session_message(
                    session_id,
                    StoredMessage(
                        id=f"ch-a-{uuid.uuid4().hex[:8]}",
                        role="assistant",
                        content=final,
                        status=MessageStatus.COMPLETE,
                    ),
                )
            except Exception as e:
                logger.warning(f"[{message.channel}] Failed to archive messages: {e}")

        return result

    async def _handle_message(self, message: InboundMessage) -> None:
        """处理收到的消息（非阻塞模式）

        1. 立即发送 "⏳ 正在处理…" 占位消息（非企微通道）
        2. 后台异步执行 AI 处理
        3. 定期更新占位消息显示进度
        4. 完成后编辑占位消息（短回复）或发送新消息（长回复）

        企微通道使用流式被动回复，AI 增量内容写入 StreamBuffer，
        由企微流式刷新回调取走。
        """
        logger.info(f"[{message.channel}] Message from {message.sender_id}: {message.content[:100]}")

        session_id = f"channel_{message.channel}_{message.chat_id}"

        handler = get_notification_handler()
        target = handler.build_target_from_channel(
            channel_name=message.channel,
            chat_id=message.chat_id,
        )

        # 企微通道：使用流式被动回复，不发进度消息
        if message.channel == "wecom":
            stream_id = message.metadata.get("stream_id", "")
            task = asyncio.create_task(
                self._process_wecom_stream(message, session_id, stream_id)
            )
        else:
            # 其他通道：发进度占位消息
            progress_result = await handler.notify_progress(
                target, "⏳ 正在处理，请稍候…"
            )
            if progress_result.success and progress_result.message_id:
                target.message_id = progress_result.message_id

            task = asyncio.create_task(
                self._process_and_notify(message, session_id, target, handler)
            )

        task_key = f"{message.channel}_{message.chat_id}_{message.internal_id}"
        self._background_tasks[task_key] = task

        def _cleanup(t: asyncio.Task, key: str = task_key):
            self._background_tasks.pop(key, None)
        task.add_done_callback(_cleanup)

    async def _process_wecom_stream(
        self,
        message: InboundMessage,
        session_id: str,
        stream_id: str,
    ) -> None:
        """企微专用：流式处理 AI 事件，text_delta 实时写入 StreamBuffer。

        Uses the shared ``_consume_executor_events()`` loop; channel-specific
        behaviour is injected via callbacks.
        """
        channel = self.manager.get_channel("wecom") if self.manager else None
        if not channel:
            logger.error("[wecom] Channel not found for stream processing")
            return

        buf = channel.get_stream_buffer_by_id(stream_id)
        if not buf:
            logger.error(f"[wecom] StreamBuffer not found: {stream_id}")
            return

        request = await self._build_request(message, session_id)

        # Callbacks: write text deltas and tool summaries to StreamBuffer in real time
        async def _on_text(text: str) -> None:
            buf.append(text)

        async def _on_tool(summary: str) -> None:
            buf.append(f"\n\n{summary}")

        try:
            result = await self._consume_executor_events(
                message, session_id, request,
                on_text_delta=_on_text,
                on_tool_summary=_on_tool,
            )

            content = result.final_content
            if content:
                content = self._truncate_response(content, "wecom")
                if result.tool_call_count > 0 and result.tool_summaries:
                    tool_section = "\n".join(result.tool_summaries)
                    content = tool_section + "\n\n---\n\n" + content
                buf.set_final(content)
            elif result.is_error and not result.final_content:
                buf.append("\n\n⏰ 处理超时，请稍后重试。")
        except Exception as e:
            logger.error(f"[wecom] AI processing error: {e}", exc_info=True)
            buf.set_final(f"❌ 处理出错：{str(e)[:200]}")
        finally:
            buf.mark_finished()

    async def _process_and_notify(
        self,
        message: InboundMessage,
        session_id: str,
        target: NotificationTarget,
        handler: UnifiedNotificationHandler,
    ) -> None:
        """Background task: run AI processing with progress updates."""
        try:
            response = await self._process_with_ai(message, session_id, target, handler)

            if response:
                # Edit the progress placeholder with the final result,
                # or send new message(s) if the response is too long.
                max_len = CHANNEL_MAX_LENGTH.get(message.channel, 4000)
                if len(response) <= max_len and target.message_id:
                    await handler.notify_completion(target, response, success=True)
                else:
                    # For long responses, edit placeholder to summary, then send full content
                    if target.message_id:
                        summary = response[:200] + "…" if len(response) > 200 else response
                        await handler.notify_progress(target, f"✅ 处理完成（共 {len(response)} 字符）\n\n{summary}")
                    # Send full response via send_text (auto-splits)
                    full_target = handler.build_target_from_channel(
                        channel_name=message.channel,
                        chat_id=message.chat_id,
                    )
                    await handler.notify(full_target, response)
            else:
                # No response content
                await handler.notify_progress(target, "⚠️ 未能获取有效回复，请重试。")

        except Exception as e:
            logger.error(f"Error in background processing: {e}", exc_info=True)
            try:
                await handler.notify_progress(target, f"❌ 处理出错：{str(e)[:200]}")
            except Exception:
                pass

    def _truncate_response(self, content: str, channel: str) -> str:
        """根据通道限制截断响应"""
        max_len = CHANNEL_MAX_LENGTH.get(channel, 4000)
        if len(content) > max_len:
            return content[:max_len] + "\n\n... (响应被截断)"
        return content

    @staticmethod
    def _get_tool_display_name(tool_name: str, params: dict) -> str:
        """Generate a semantic display title for a tool call, matching AGUI style.

        Produces titles like ``Read: /home/ubuntu/app.py`` or ``Bash: 安装依赖包``
        instead of the raw tool name.  Falls back to the original tool name when
        no meaningful context can be extracted from *params*.
        """
        if not isinstance(params, dict):
            return tool_name

        if tool_name in ("Task", "task"):
            subagent = params.get("subagent_type", params.get("subagent_name", ""))
            desc = params.get("description", "")
            if subagent and desc:
                return f"Task: {subagent} - {desc}"
            elif subagent:
                return f"Task: {subagent}"
            elif desc:
                return f"Task: {desc}"

        elif tool_name in ("Skill", "use_skill"):
            skill = params.get("skill", params.get("command", ""))
            if skill:
                return f"Skill: {skill}"

        elif tool_name in ("Read", "read_file"):
            fp = params.get("file_path", params.get("filePath", ""))
            if fp:
                return f"Read: {fp}"

        elif tool_name in ("Write", "write_to_file"):
            fp = params.get("file_path", params.get("filePath", ""))
            if fp:
                return f"Write: {fp}"

        elif tool_name in ("Edit", "replace_in_file"):
            fp = params.get("file_path", params.get("filePath", ""))
            if fp:
                return f"Edit: {fp}"

        elif tool_name in ("Grep", "search_content"):
            path = params.get("path", params.get("directory", ""))
            if path:
                return f"Grep: {path}"

        elif tool_name in ("Glob", "search_file"):
            path = params.get("path", params.get("target_directory", ""))
            pattern = params.get("pattern", "")
            if path and pattern:
                return f"Glob: {pattern} in {path}"
            elif path:
                return f"Glob: {path}"
            elif pattern:
                return f"Glob: {pattern}"

        elif tool_name in ("Bash", "execute_command"):
            explanation = params.get("explanation", params.get("description", ""))
            if explanation:
                return f"Bash: {explanation}"
            command = params.get("command", "")
            if command:
                if len(command) > 60:
                    command = command[:60] + "…"
                return f"Bash: {command}"

        elif tool_name in ("TodoWrite", "todo_write"):
            todos_str = params.get("todos", "")
            if todos_str:
                try:
                    todos = json.loads(todos_str) if isinstance(todos_str, str) else todos_str
                    if isinstance(todos, list) and todos:
                        total = len(todos)
                        current_index = 0
                        current_content = ""
                        for i, todo in enumerate(todos):
                            if isinstance(todo, dict) and todo.get("status") == "in_progress":
                                current_index = i + 1
                                current_content = todo.get("content", "")
                                break
                        if current_index > 0 and current_content:
                            return f"Todos: {current_index}/{total} - {current_content}"
                        elif current_index > 0:
                            return f"Todos: {current_index}/{total}"
                        else:
                            return f"Todos: {total} items"
                except (json.JSONDecodeError, TypeError):
                    pass

        elif tool_name in ("WebSearch", "web_search"):
            query = params.get("query", params.get("searchTerm", ""))
            if query:
                if len(query) > 60:
                    query = query[:60] + "…"
                return f"Search: {query}"

        elif tool_name in ("WebFetch", "web_fetch"):
            url = params.get("url", "")
            if url:
                if len(url) > 60:
                    url = url[:60] + "…"
                return f"Fetch: {url}"

        # mcp__xxx and other tools — keep original name
        return tool_name

    async def _process_with_ai(
        self,
        message: InboundMessage,
        session_id: str,
        target: NotificationTarget,
        handler: UnifiedNotificationHandler,
    ) -> Optional[str]:
        """Process message with AI for non-streaming channels (Telegram, Slack, etc.).

        Uses the shared ``_consume_executor_events()`` loop; injects a progress
        callback so the user sees periodic "⏳ processing…" updates.
        """
        request = await self._build_request(message, session_id)

        last_progress_time = time.time()
        collected_chars = 0

        async def _on_text(text: str) -> None:
            nonlocal last_progress_time, collected_chars
            collected_chars += len(text)
            now = time.time()
            if now - last_progress_time >= PROGRESS_UPDATE_INTERVAL:
                last_progress_time = now
                await handler.notify_progress(
                    target,
                    f"⏳ 正在处理… 已收集 {collected_chars} 字符"
                )

        result = await self._consume_executor_events(
            message, session_id, request,
            on_text_delta=_on_text,
        )

        content = result.final_content
        if not content:
            # No result event — fall back to collected text parts
            content = "".join(result.collected_text_parts).strip()

        if not content:
            if result.is_error:
                return "抱歉，处理超时，请稍后重试。"
            return None

        content = self._truncate_response(content, message.channel)
        if result.tool_call_count > 0 and result.tool_summaries:
            tool_section = "\n".join(result.tool_summaries)
            content = tool_section + "\n\n---\n\n" + content

        return content
    
    async def _send_typing_indicator(self, message: InboundMessage) -> None:
        """发送输入中指示"""
        if not self.manager:
            return

        channel = self.manager.get_channel(message.channel)
        if not channel:
            return

        try:
            await channel.send_typing(message.chat_id)
        except Exception as e:
            logger.debug(f"Failed to send typing indicator: {e}")
    
    async def _handle_error(self, error: Exception, channel: str) -> None:
        """处理通道错误"""
        logger.error(f"Channel error [{channel}]: {error}")


def get_channel_service() -> Optional[ChannelService]:
    """获取全局 channel 服务实例"""
    return _channel_service


async def create_channel_service() -> Optional[ChannelService]:
    """创建并初始化 channel 服务"""
    global _channel_service
    
    service = ChannelService()
    if await service.initialize():
        _channel_service = service
        return service
    
    return None

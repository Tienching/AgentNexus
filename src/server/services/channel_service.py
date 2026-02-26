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
from typing import Any, Dict, Optional

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
)
from .notification import (
    NotificationTarget,
    UnifiedNotificationHandler,
    get_notification_handler,
)

logger = get_logger(__name__)

CHANNEL_MAX_LENGTH = {
    "telegram": 4000,
    "discord": 1900,
    "slack": 39000,
    "whatsapp": 65000,
    "signal": 65000,
}

# Progress update interval (seconds) — how often to edit the placeholder message
PROGRESS_UPDATE_INTERVAL = 8

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
    
    async def _handle_message(self, message: InboundMessage) -> None:
        """处理收到的消息（非阻塞模式）

        1. 立即发送 "⏳ 正在处理…" 占位消息
        2. 后台异步执行 AI 处理
        3. 定期更新占位消息显示进度
        4. 完成后编辑占位消息（短回复）或发送新消息（长回复）
        """
        logger.info(f"[{message.channel}] Message from {message.sender_id}: {message.content[:100]}")

        session_id = f"channel_{message.channel}_{message.chat_id}"

        # 1. Send an immediate "processing" placeholder
        handler = get_notification_handler()
        target = handler.build_target_from_channel(
            channel_name=message.channel,
            chat_id=message.chat_id,
        )
        progress_result = await handler.notify_progress(
            target, "⏳ 正在处理，请稍候…"
        )
        if progress_result.success and progress_result.message_id:
            target.message_id = progress_result.message_id

        # 2. Launch background processing task
        task = asyncio.create_task(
            self._process_and_notify(message, session_id, target, handler)
        )
        task_key = f"{message.channel}_{message.chat_id}_{message.internal_id}"
        self._background_tasks[task_key] = task

        # Cleanup on completion
        def _cleanup(t: asyncio.Task, key: str = task_key):
            self._background_tasks.pop(key, None)
        task.add_done_callback(_cleanup)

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

    async def _process_with_ai(
        self,
        message: InboundMessage,
        session_id: str,
        target: NotificationTarget,
        handler: UnifiedNotificationHandler,
    ) -> Optional[str]:
        """使用 AI 处理消息，带进度更新"""
        from ..services import CLIExecutor
        from ..models import RequestModel
        
        # 构建请求
        request = RequestModel(
            content=message.content,
            user=f"{message.channel}_{message.sender_id}",
            session_id=session_id,
            msg_id=f"msg-{uuid.uuid4().hex[:8]}",
        )
        
        # 创建执行器
        executor = CLIExecutor(config=settings)
        
        # 使用配置的 exec_user 名称（默认是 "ubuntu"）
        exec_user = settings.exec_user or "ubuntu"
        
        # 收集响应
        response_parts = []
        
        timeout = settings.cli_timeout or 120

        last_progress_time = time.time()
        collected_chars = 0

        try:
            async with asyncio.timeout(timeout):
                async for output in executor.execute(request, exec_user=exec_user, output_format="raw"):
                    if not output:
                        continue

                    logger.debug(f"CLI output: {output[:200] if len(output) > 200 else output}")

                    try:
                        data = json.loads(output)

                        # 提取文本内容
                        if isinstance(data, dict):
                            event_type = data.get("type", "")

                            # stream_event 包含实际的文本
                            if event_type == "stream_event":
                                event = data.get("event", {})
                                if event.get("type") == "content_block_delta":
                                    delta = event.get("delta", {})
                                    if delta.get("type") == "text_delta":
                                        text = delta.get("text", "")
                                        if text:
                                            response_parts.append(text)
                                            collected_chars += len(text)

                                            # Periodic progress update
                                            now = time.time()
                                            if now - last_progress_time >= PROGRESS_UPDATE_INTERVAL:
                                                last_progress_time = now
                                                await handler.notify_progress(
                                                    target,
                                                    f"⏳ 正在处理… 已收集 {collected_chars} 字符"
                                                )

                            # result 事件包含完整的回复
                            elif event_type == "result":
                                content = data.get("content", "") or data.get("result", "")
                                if content:
                                    content = self._truncate_response(content, message.channel)
                                    return content

                    except json.JSONDecodeError:
                        continue

        except TimeoutError:
            logger.error(f"AI execution timed out after {timeout}s")
            # If we have partial content, return it
            if response_parts:
                partial = "".join(response_parts).strip()
                if partial:
                    return f"⏰ **处理超时** (已收集部分结果)\n\n{self._truncate_response(partial, message.channel)}"
            return "抱歉，处理超时，请稍后重试。"
        except Exception as e:
            logger.error(f"AI execution error: {e}")
            return None
        
        # 合并响应
        full_response = "".join(response_parts).strip()
        
        full_response = self._truncate_response(full_response, message.channel)
        
        return full_response if full_response else None
    
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

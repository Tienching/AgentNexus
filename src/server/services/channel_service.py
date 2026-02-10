"""Channel 服务 - 集成多平台消息通道

将 channels 模块集成到 virtual-human-sdk 服务中，
实现 Telegram、Slack 等平台的消息接收和 AI 回复。
"""

import asyncio
import json
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

logger = get_logger(__name__)

CHANNEL_MAX_LENGTH = {
    "telegram": 4000,
    "discord": 1900,
    "slack": 39000,
    "whatsapp": 65000,
    "signal": 65000,
}

# 全局 channel 服务实例
_channel_service: Optional["ChannelService"] = None


class ChannelService:
    """Channel 服务
    
    管理多平台消息通道，将收到的消息转发给 AI 处理，
    并将 AI 回复发送回用户。
    """
    
    def __init__(self):
        self.manager: Optional[ChannelManager] = None
        self._executor = None  # AI 执行器
        self._active_sessions: Dict[str, Dict[str, Any]] = {}
        
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
        if self.manager:
            await self.manager.stop()
            logger.info("Channel service stopped")
    
    async def _handle_message(self, message: InboundMessage) -> None:
        """处理收到的消息
        
        将消息转发给 AI 执行器处理，并返回结果。
        """
        logger.info(f"[{message.channel}] Message from {message.sender_id}: {message.content[:100]}")
        
        # 生成会话 ID（基于 channel + chat_id）
        session_id = f"channel_{message.channel}_{message.chat_id}"
        
        # 发送"正在处理"提示
        if message.content:
            await self._send_typing_indicator(message)
        
        try:
            # 调用 AI 处理消息
            response = await self._process_with_ai(message, session_id)
            
            # 发送回复
            if response:
                reply = OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content=response,
                    reply_to=message.message_id,
                )
                await self.manager.send(message.channel, reply)
                
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            
            # 发送错误提示
            error_reply = OutboundMessage(
                channel=message.channel,
                chat_id=message.chat_id,
                content="抱歉，处理消息时出现错误，请稍后重试。",
                reply_to=message.message_id,
            )
            await self.manager.send(message.channel, error_reply)
    
    def _truncate_response(self, content: str, channel: str) -> str:
        """根据通道限制截断响应"""
        max_len = CHANNEL_MAX_LENGTH.get(channel, 4000)
        if len(content) > max_len:
            return content[:max_len] + "\n\n... (响应被截断)"
        return content

    async def _process_with_ai(self, message: InboundMessage, session_id: str) -> Optional[str]:
        """使用 AI 处理消息"""
        from ..services import CCRExecutor
        from ..models import RequestModel
        
        # 构建请求
        request = RequestModel(
            content=message.content,
            user=f"{message.channel}_{message.sender_id}",
            session_id=session_id,
            msg_id=f"msg-{uuid.uuid4().hex[:8]}",
        )
        
        # 创建执行器
        executor = CCRExecutor(config=settings)
        
        # 使用配置的 exec_user 名称（默认是 "ubuntu"）
        exec_user = settings.exec_user or "ubuntu"
        
        # 收集响应
        response_parts = []
        
        timeout = settings.ccr_timeout or 120

        try:
            async with asyncio.timeout(timeout):
                async for output in executor.execute(request, exec_user=exec_user, output_format="raw"):
                    if not output:
                        continue

                    logger.debug(f"CCR output: {output[:200] if len(output) > 200 else output}")

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
                                            logger.debug(f"Found text_delta: {text}")
                                            response_parts.append(text)

                            # result 事件包含完整的回复
                            elif event_type == "result":
                                content = data.get("content", "") or data.get("result", "")
                                if content:
                                    logger.debug(f"Found result content: {content[:100]}")
                                    content = self._truncate_response(content, message.channel)
                                    return content

                    except json.JSONDecodeError as e:
                        logger.debug(f"Failed to parse JSON: {e}")
                        continue

        except TimeoutError:
            logger.error(f"AI execution timed out after {timeout}s")
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

# -*- coding: utf-8 -*-
"""
企业微信 Channel 实现
"""

import hashlib
from typing import AsyncIterator, Optional, Any, Dict
from dataclasses import dataclass

from ..base import Channel, InboundMessage, OutboundMessage, MessageFormat


@dataclass
class WeWorkConfig:
    """企微配置"""
    corp_id: str = ""
    agent_id: str = ""
    secret: str = ""
    token: str = ""
    encoding_aes_key: str = ""


class WeWorkChannel:
    """企业微信 Channel"""
    
    name: str = "wecom"
    
    def __init__(self, config: Optional[WeWorkConfig] = None):
        self.config = config or WeWorkConfig()
        self._capabilities = {
            "markdown": True,
            "embeds": False,
            "buttons": False,
            "threads": False,
            "reactions": False,
        }
        self._message_queue: list[InboundMessage] = []
    
    def supports_capability(self, cap: str) -> bool:
        """检查能力支持"""
        return self._capabilities.get(cap, False)
    
    def get_session_key(self, msg: InboundMessage) -> str:
        """生成 session key
        
        基于 Clawdbot 的设计：session_key = hash(channel + corp_id + user_id)
        确保同一用户在同一企业的消息路由到同一会话。
        """
        parts = [
            self.name,
            self.config.corp_id,
            msg.peer_id,
        ]
        # 如果是群消息，加入群 ID
        if msg.group_id:
            parts.append(msg.group_id)
        
        key_str = ":".join(parts)
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]
    
    async def receive(self) -> AsyncIterator[InboundMessage]:
        """接收消息
        
        实际场景中，这里会处理企微 webhook 推送的消息。
        当前实现为演示用，消息由外部 push 到队列。
        """
        while self._message_queue:
            yield self._message_queue.pop(0)
    
    def push_message(self, msg: InboundMessage) -> None:
        """外部推送消息到队列（供 webhook 调用）"""
        self._message_queue.append(msg)
    
    async def send(self, message: OutboundMessage) -> bool:
        """发送消息到企微
        
        实际场景中，这里会调用企微 API 发送消息。
        当前实现为演示用，仅打印日志。
        """
        # TODO: 实现实际的企微 API 调用
        # 1. 获取 access_token
        # 2. 构造消息体
        # 3. 调用企微消息推送 API
        
        print(f"[WeWork] Sending message to {message.peer_id}: {message.content[:50]}...")
        return True
    
    def parse_webhook_message(self, data: Dict[str, Any]) -> Optional[InboundMessage]:
        """解析企微 webhook 消息
        
        Args:
            data: 企微推送的 XML/JSON 数据（已解密）
        
        Returns:
            InboundMessage 或 None
        """
        msg_type = data.get("MsgType", "")
        if msg_type != "text":
            # 暂只支持文本消息
            return None
        
        return InboundMessage(
            channel=self.name,
            peer_id=data.get("FromUserName", ""),
            content=data.get("Content", ""),
            message_id=data.get("MsgId", ""),
            group_id=data.get("ChatId"),  # 群聊 ID
            metadata={
                "corp_id": self.config.corp_id,
                "agent_id": data.get("AgentID", ""),
                "create_time": data.get("CreateTime", 0),
            },
        )

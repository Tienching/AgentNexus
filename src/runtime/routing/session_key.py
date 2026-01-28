# -*- coding: utf-8 -*-
"""
Session Key 路由

基于 Clawdbot 的确定性路由设计。
"""

from typing import Optional
from dataclasses import dataclass

from ..channels import InboundMessage, get_channel_registry
from ..runtime import SessionManager, Session


@dataclass
class RouteResult:
    """路由结果"""
    session_id: str
    session: Session
    is_new: bool
    channel: str


class SessionKeyRouter:
    """Session Key 路由器
    
    根据 Channel 生成的 session_key 确定性路由到会话。
    """
    
    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
        self.channel_registry = get_channel_registry()
    
    def route(
        self,
        message: InboundMessage,
        provider: str = "claude",
        agent: Optional[str] = None,
    ) -> RouteResult:
        """路由消息到会话
        
        1. 获取 Channel
        2. 生成 session_key
        3. 获取或创建 Session
        
        Args:
            message: 入站消息
            provider: 默认 Provider
            agent: 默认 Agent
        
        Returns:
            RouteResult
        """
        channel = self.channel_registry.get(message.channel)
        if not channel:
            # 使用默认 session_key 生成
            session_key = f"{message.channel}:{message.peer_id}"
        else:
            session_key = channel.get_session_key(message)
        
        # 获取或创建会话
        existing = self.session_manager.get(session_key)
        if existing:
            return RouteResult(
                session_id=session_key,
                session=existing,
                is_new=False,
                channel=message.channel,
            )
        
        # 创建新会话
        session = self.session_manager.create(
            session_id=session_key,
            provider=provider,
            agent=agent,
            metadata={
                "channel": message.channel,
                "peer_id": message.peer_id,
                "group_id": message.group_id,
            },
        )
        
        return RouteResult(
            session_id=session_key,
            session=session,
            is_new=True,
            channel=message.channel,
        )

# -*- coding: utf-8 -*-
"""Callback Handler Service

Handle callbacks after client disconnection
"""

import asyncio
import json
import httpx
from typing import List, Dict, Any, Optional

from ..logger import get_logger

logger = get_logger(__name__)

# 回调配置
CALLBACK_TIMEOUT = 30.0  # HTTP 请求超时时间（秒）
CALLBACK_MAX_RETRIES = 3  # 最大重试次数


class CallbackHandler:
    """回调处理器"""

    async def send_callback(
        self,
        response_url: str,
        messages: List[str],
        request_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        发送回调消息到 response_url

        Args:
            response_url: 回调 URL
            messages: 收集的消息列表
            request_data: 原始请求数据

        Returns:
            是否发送成功
        """
        if not response_url:
            logger.warning("No response_url provided, skipping callback")
            return False

        if not messages:
            logger.warning("No messages to send, skipping callback")
            return False

        callback_data = self._build_callback_payload(messages, request_data)
        full_response = callback_data.get("markdown", {}).get("content", "")

        logger.info(
            "Sending callback to response_url",
            extra={
                "response_url": response_url[:100],
                "message_count": len(messages),
                "total_length": len(full_response),
            }
        )

        for attempt in range(CALLBACK_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=CALLBACK_TIMEOUT) as client:
                    response = await client.post(
                        response_url,
                        json=callback_data,
                        headers={"Content-Type": "application/json"},
                    )

                    if 200 <= response.status_code < 300:
                        logger.info(
                            "Callback sent successfully",
                            extra={
                                "response_url": response_url[:100],
                                "status_code": response.status_code,
                                "attempt": attempt + 1,
                            }
                        )
                        return True
                    else:
                        logger.warning(
                            "Callback failed with status code",
                            extra={
                                "response_url": response_url[:100],
                                "status_code": response.status_code,
                                "attempt": attempt + 1,
                            }
                        )

            except httpx.TimeoutException as e:
                logger.warning(f"Callback timeout on attempt {attempt + 1}", extra={"error": str(e)})
            except httpx.RequestError as e:
                logger.warning(f"Callback request error on attempt {attempt + 1}", extra={"error": str(e)})
            except Exception as e:
                logger.error(f"Unexpected error during callback on attempt {attempt + 1}", exc_info=True)

            if attempt < CALLBACK_MAX_RETRIES - 1:
                wait_time = (attempt + 1) * 2
                logger.info(f"Retrying callback in {wait_time} seconds...")
                await asyncio.sleep(wait_time)

        logger.error("All callback attempts failed", extra={"max_retries": CALLBACK_MAX_RETRIES})
        return False

    async def send_disconnect_callback(
        self,
        response_url: str,
        pending_messages: List[str],
        user: str,
        msg_id: str,
        session_id: str,
        content: str,
        exec_user: str,
    ) -> None:
        """在客户端断开后发送回调"""
        if not pending_messages:
            logger.info("No pending messages to send in callback", extra={"exec_user": exec_user})
            return

        logger.info(
            "Sending disconnect callback",
            extra={
                "api_user": user,
                "exec_user": exec_user,
                "response_url": response_url[:100] if response_url else "",
                "pending_messages_count": len(pending_messages),
            }
        )

        request_data = {
            "user": user,
            "msg_id": msg_id,
            "session_id": session_id,
            "content": content,
        }

        success = await self.send_callback(response_url, pending_messages, request_data)

        if success:
            logger.info("Disconnect callback sent successfully", extra={"exec_user": exec_user})
        else:
            logger.error("Failed to send disconnect callback", extra={"exec_user": exec_user})

    async def send_timeout_callback(
        self,
        response_url: str,
        user: str,
        msg_id: str,
        session_id: str,
        content: str,
        exec_user: str,
    ) -> None:
        """在 response_url 即将超时时发送超时提示回调"""
        if not response_url:
            return

        logger.info("Sending timeout callback", extra={"exec_user": exec_user})

        timeout_message = "⏰ **处理超时**\n\n很抱歉，由于处理时间过长（超过1小时），无法返回完整结果。\n\n请尝试：\n1. 简化您的问题\n2. 分步骤提问\n3. 稍后重试"

        success = await self.send_callback(
            response_url,
            [timeout_message],
            {
                "user": user,
                "msg_id": msg_id,
                "session_id": session_id,
                "content": content,
            },
        )

        if success:
            logger.info("Timeout callback sent successfully", extra={"exec_user": exec_user})
        else:
            logger.error("Failed to send timeout callback", extra={"exec_user": exec_user})

    def _build_callback_payload(
        self,
        messages: List[str],
        request_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构建回调请求体（企业微信 AI 助手格式）"""
        MAX_CONTENT_BYTES = 20000

        message_bytes = [(msg, len(msg.encode('utf-8'))) for msg in messages]
        total_bytes = sum(byte_count for _, byte_count in message_bytes)

        response_content = ""
        omitted_chars = 0

        if total_bytes <= MAX_CONTENT_BYTES:
            response_content = "".join(messages)
        else:
            available_bytes = MAX_CONTENT_BYTES - 200
            kept_messages = []
            current_bytes = 0

            for msg, byte_count in reversed(message_bytes):
                if current_bytes + byte_count <= available_bytes:
                    kept_messages.insert(0, msg)
                    current_bytes += byte_count
                else:
                    break

            skipped_count = len(messages) - len(kept_messages)
            for i in range(skipped_count):
                omitted_chars += len(messages[i])

            if kept_messages:
                response_content = "".join(kept_messages)
            else:
                last_msg = messages[-1] if messages else ""
                response_content = self._truncate_utf8_from_start(last_msg, available_bytes)
                omitted_chars = sum(len(msg) for msg in messages) - len(response_content)

            omit_notice = f"⚠️ **内容过长，已省略前面 {omitted_chars} 个字符**\n\n---\n\n"
            response_content = omit_notice + response_content

            logger.warning(f"Response content too long ({total_bytes} bytes), truncated from beginning")

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": response_content,
            }
        }

        if request_data and request_data.get("msg_id"):
            payload["markdown"]["feedback"] = {
                "id": request_data.get("msg_id", "")
            }

        return payload

    def _truncate_utf8_from_start(self, text: str, max_bytes: int) -> str:
        """从开头截断 UTF-8 字符串，保留末尾指定字节数"""
        encoded = text.encode('utf-8')
        if len(encoded) <= max_bytes:
            return text

        truncated = encoded[-max_bytes:]
        return truncated.decode('utf-8', errors='ignore')

    def agui_events_to_markdown(self, events: List[str]) -> List[str]:
        """将 AG-UI SSE 事件转换为 markdown 文本列表
        
        Args:
            events: AG-UI SSE 事件字符串列表（格式：data: {...}）
            
        Returns:
            markdown 文本片段列表
        """
        markdown_parts = []
        
        for event_str in events:
            if not event_str or not event_str.strip():
                continue
            
            # 解析 SSE 格式：data: {...}
            lines = event_str.strip().split('\n')
            for line in lines:
                if line.startswith('data:'):
                    json_str = line[5:].strip()
                    if not json_str:
                        continue
                    
                    try:
                        event_data = json.loads(json_str)
                        event_type = event_data.get("type", "")
                        
                        # 提取文本内容
                        if event_type == "TEXT_MESSAGE_CONTENT":
                            delta = event_data.get("delta", "")
                            if delta:
                                markdown_parts.append(delta)
                        
                        # 工具调用开始
                        elif event_type == "TOOL_CALL_START":
                            tool_name = event_data.get("toolCallName", "未知工具")
                            markdown_parts.append(f"\n🛠️ **[调用工具: {tool_name}]**\n")
                        
                        # 工具调用结果
                        elif event_type == "TOOL_CALL_RESULT":
                            content = event_data.get("content", "")
                            if content:
                                # 截断过长的工具结果
                                if len(content) > 500:
                                    content = content[:500] + "...(结果已截断)"
                                markdown_parts.append(f"```\n{content}\n```\n")
                        
                    except json.JSONDecodeError:
                        continue
        
        return markdown_parts

    async def send_agui_callback(
        self,
        response_url: str,
        agui_events: List[str],
        request_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """发送 AG-UI 事件回调（转换为 markdown 格式）
        
        Args:
            response_url: 回调 URL
            agui_events: AG-UI SSE 事件列表
            request_data: 原始请求数据
            
        Returns:
            是否发送成功
        """
        if not response_url:
            logger.warning("No response_url provided for AG-UI callback")
            return False
        
        if not agui_events:
            logger.info("No AG-UI events to send in callback")
            return False
        
        # 转换为 markdown
        markdown_parts = self.agui_events_to_markdown(agui_events)
        
        if not markdown_parts:
            logger.info("No markdown content extracted from AG-UI events")
            return False
        
        logger.info(
            "Sending AG-UI callback",
            extra={
                "response_url": response_url[:100],
                "event_count": len(agui_events),
                "markdown_parts": len(markdown_parts),
            }
        )
        
        return await self.send_callback(response_url, markdown_parts, request_data)

# -*- coding: utf-8 -*-
"""Task Completion Notification Service

Sends notifications to users when background tasks complete.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from ...runtime.models.session import StoredMessage, MessageStatus
from .callback_handler import CallbackHandler
from .session_storage import get_session_storage

logger = logging.getLogger(__name__)


class TaskNotifier:
    """任务完成通知器"""

    def __init__(self):
        self.callback_handler = CallbackHandler()

    async def notify_task_completion(
        self,
        task_id: str,
        session_id: str,
        response_url: Optional[str],
        callback_msg_id: Optional[str] = None,
        callback_user: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        source_session_id: Optional[str] = None,
    ) -> bool:
        """发送任务完成通知

        Args:
            task_id: 任务 ID
            session_id: 任务执行的会话 ID (用于获取任务上下文/最后回复)
            response_url: 回调 URL
            callback_msg_id: 原始消息 ID
            callback_user: 用户标识
            success: 任务是否成功
            error_message: 失败时的错误信息
            source_session_id: 发起任务的原始会话 ID (用于归档通知消息)

        Returns:
            是否发送成功
        """
        if not response_url:
            logger.debug(f"Task {task_id}: no response_url, skip notification")
            return False

        # 构建通知内容
        messages = await self._build_notification_content(
            task_id=task_id,
            session_id=session_id,
            success=success,
            error_message=error_message,
        )

        if not messages:
            logger.warning(f"Task {task_id}: no content to notify")
            return False

        # 1. 归档到 Session (让 Nexus 可见)
        # 优先归档到 source_session_id (用户主会话)，否则归档到 session_id (任务会话)
        target_session_id = source_session_id or session_id
        try:
            storage = get_session_storage()
            full_content = "".join(messages)

            archive_msg = StoredMessage(
                id=f"notify-{uuid.uuid4()}",
                role="assistant",
                content=full_content,
                status=MessageStatus.COMPLETE,
                created_at=int(datetime.now(timezone.utc).timestamp() * 1000)
            )

            # 归档到目标 session
            storage.add_session_message(target_session_id, archive_msg)
            logger.info(f"Task {task_id}: notification archived to session {target_session_id}")

        except Exception as e:
            logger.error(f"Task {task_id}: failed to archive notification: {e}")

        # 2. 发送回调
        request_data = {
            "msg_id": callback_msg_id,
            "user": callback_user,
            "session_id": target_session_id,  # Use target session for context in callback
        }

        try:
            result = await self.callback_handler.send_callback(
                response_url=response_url,
                messages=messages,
                request_data=request_data,
            )
            if result:
                logger.info(f"Task {task_id}: notification sent successfully")
            return result
        except Exception as e:
            logger.error(f"Task {task_id}: failed to send notification: {e}")
            return False

    async def _build_notification_content(
        self,
        task_id: str,
        session_id: str,
        success: bool,
        error_message: Optional[str],
    ) -> List[str]:
        """构建通知内容

        从 Redis 会话存储中提取最后的 assistant 回复
        """
        messages: List[str] = []

        # 添加任务状态标题
        if success:
            messages.append(f"✅ **任务 #{task_id} 已完成**\n\n")
        else:
            messages.append(f"❌ **任务 #{task_id} 执行失败**\n\n")
            if error_message:
                messages.append(f"**错误信息:** {error_message}\n\n")

        # 从会话存储获取最后的回复内容
        try:
            storage = get_session_storage()
            stored_messages = storage.get_session_messages(session_id)

            if stored_messages:
                # 提取最后的 assistant 消息
                assistant_msgs = [
                    m for m in stored_messages
                    if getattr(m, "role", "").lower() == "assistant"
                ]

                if assistant_msgs:
                    last_msg = assistant_msgs[-1]
                    content = getattr(last_msg, "content", "") or ""
                    if content:
                        messages.append("---\n\n")
                        messages.append(content)

        except Exception as e:
            logger.warning(f"Failed to get session messages for {session_id}: {e}")

        return messages

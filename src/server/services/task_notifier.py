# -*- coding: utf-8 -*-
"""Task Completion Notification Service

Sends notifications to users when background tasks complete.
Uses the unified notification system to support both HTTP webhooks
and messaging channels (Telegram, Slack, etc.).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from ...runtime.models.session import StoredMessage, MessageStatus
from .observability import record_sampled_event, telemetry
from .callback_handler import CallbackHandler
from .session_storage import get_session_storage
from .notification import (
    NotificationTarget,
    UnifiedNotificationHandler,
    get_notification_handler,
)

logger = logging.getLogger(__name__)


class TaskNotifier:
    """任务完成通知器

    Supports two notification paths:
    1. Unified notification (via NotificationTarget): Telegram, Slack, HTTP webhook, etc.
    2. Legacy HTTP webhook (via response_url): backward compatible with existing callers.
    """

    def __init__(self):
        self.callback_handler = CallbackHandler()

    def _resolve_writeback_session(self, session_id: str, source_session_id: Optional[str]) -> tuple[str, str]:
        """Resolve where the final assistant result should be written back."""
        target_session_id = source_session_id or session_id
        writeback_scope = "source_session" if source_session_id and source_session_id != session_id else "task_session"
        return target_session_id, writeback_scope

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
        notification_target: Optional[NotificationTarget] = None,
    ) -> bool:
        """发送任务完成通知

        Args:
            task_id: 任务 ID
            session_id: 任务执行的会话 ID
            response_url: 回调 URL (legacy)
            callback_msg_id: 原始消息 ID
            callback_user: 用户标识
            success: 任务是否成功
            error_message: 失败时的错误信息
            source_session_id: 发起任务的原始会话 ID
            notification_target: Unified notification target (takes priority over response_url)

        Returns:
            是否发送成功
        """
        # If no target and no response_url, nothing to do
        if not notification_target and not response_url:
            logger.debug(f"Task {task_id}: no notification target, skip")
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
        target_session_id, writeback_scope = self._resolve_writeback_session(session_id, source_session_id)
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

            storage.add_session_message(target_session_id, archive_msg)
            telemetry.increment("task_notification.writeback.total")
            telemetry.increment(f"task_notification.writeback.{writeback_scope}")
            record_sampled_event(
                "task_notification.writeback",
                {
                    "task_id": task_id,
                    "source_session_id": source_session_id,
                    "target_session_id": target_session_id,
                    "writeback_scope": writeback_scope,
                },
            )
            logger.info(
                "Task notification archived",
                extra={
                    "task_id": task_id,
                    "source_session_id": source_session_id,
                    "target_session_id": target_session_id,
                    "writeback_scope": writeback_scope,
                },
            )

        except Exception as e:
            telemetry.increment("task_notification.writeback.failed")
            logger.error(
                "Task notification archive failed",
                extra={
                    "task_id": task_id,
                    "source_session_id": source_session_id,
                    "target_session_id": target_session_id,
                    "writeback_scope": writeback_scope,
                    "error": str(e),
                },
            )

        # 2. Send notification via unified handler or legacy callback
        full_content = "".join(messages)

        # Prefer unified notification target
        if notification_target:
            try:
                handler = get_notification_handler()
                result = await handler.notify_completion(
                    notification_target, full_content, success=success
                )
                if result.success:
                    telemetry.increment("task_notification.delivery.success")
                    logger.info(
                        "Task notification sent",
                        extra={
                            "task_id": task_id,
                            "sink_type": notification_target.sink_type,
                            "delivery": "unified",
                        },
                    )
                    return True
                else:
                    telemetry.increment("task_notification.delivery.failed")
                    logger.warning(
                        "Task notification unified delivery failed",
                        extra={
                            "task_id": task_id,
                            "sink_type": notification_target.sink_type,
                            "error": result.error,
                        },
                    )
            except Exception as e:
                telemetry.increment("task_notification.delivery.failed")
                logger.error(
                    "Task notification unified delivery error",
                    extra={
                        "task_id": task_id,
                        "sink_type": getattr(notification_target, "sink_type", None),
                        "error": str(e),
                    },
                )

        # Fallback to legacy HTTP webhook
        if response_url:
            request_data = {
                "msg_id": callback_msg_id,
                "user": callback_user,
                "session_id": target_session_id,
            }
            try:
                result = await self.callback_handler.send_callback(
                    response_url=response_url,
                    messages=messages,
                    request_data=request_data,
                )
                if result:
                    telemetry.increment("task_notification.delivery.success")
                    logger.info(
                        "Task notification sent",
                        extra={
                            "task_id": task_id,
                            "delivery": "response_url",
                            "target_session_id": target_session_id,
                        },
                    )
                return result
            except Exception as e:
                telemetry.increment("task_notification.delivery.failed")
                logger.error(
                    "Task notification delivery failed",
                    extra={
                        "task_id": task_id,
                        "delivery": "response_url",
                        "target_session_id": target_session_id,
                        "error": str(e),
                    },
                )
                return False

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
                        telemetry.increment("task_notification.content.had_assistant_reply")
                        record_sampled_event(
                            "task_notification.content.extracted",
                            {
                                "session_id": session_id,
                                "assistant_message_id": getattr(last_msg, "id", None),
                                "content_length": len(content),
                            },
                        )

        except Exception as e:
            telemetry.increment("task_notification.content.read_failed")
            logger.warning(
                "Failed to get session messages for notification",
                extra={"session_id": session_id, "error": str(e)},
            )

        return messages

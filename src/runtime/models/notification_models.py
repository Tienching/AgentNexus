# -*- coding: utf-8 -*-
"""Domain-neutral notification data models used by runtime and server layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class TaskNotificationConfig(BaseModel):
    """Application-layer notification transport metadata for a task.

    Runtime tasks keep this configuration as a single nested object so the task
    domain is no longer forced to model transport fields as first-class state.
    Legacy top-level task attributes still proxy into this model for API
    compatibility.
    """

    response_url: Optional[str] = Field(None, description="Legacy callback URL")
    callback_msg_id: Optional[str] = Field(None, description="Opaque upstream message id")
    callback_user: Optional[str] = Field(None, description="Opaque upstream user id")
    sink_type: Optional[str] = Field(None, description="Unified notification sink type")
    channel_name: Optional[str] = Field(None, description="Logical channel name")
    chat_id: Optional[str] = Field(None, description="Channel/chat identifier")
    message_id: Optional[str] = Field(None, description="Editable progress message id")

    model_config = ConfigDict(extra="ignore")

    def is_empty(self) -> bool:
        """Return True when no delivery metadata is configured."""
        return not any(
            [
                self.response_url,
                self.callback_msg_id,
                self.callback_user,
                self.sink_type,
                self.channel_name,
                self.chat_id,
                self.message_id,
            ]
        )

    def build_request_data(
        self,
        *,
        session_id: Optional[str] = None,
        source_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build request metadata carried alongside a notification target."""
        return {
            "msg_id": self.callback_msg_id,
            "user": self.callback_user,
            "session_id": source_session_id or session_id,
        }

    def to_target(
        self,
        *,
        session_id: Optional[str] = None,
        source_session_id: Optional[str] = None,
    ) -> Optional["NotificationTarget"]:
        """Convert task notification config into a delivery target."""
        sink_type = self.sink_type or ("response_url" if self.response_url else None)
        if not sink_type:
            return None

        if sink_type == "response_url" and not self.response_url:
            return None

        return NotificationTarget(
            sink_type=sink_type,
            response_url=self.response_url or "",
            channel_name=self.channel_name or sink_type,
            chat_id=self.chat_id or "",
            message_id=self.message_id or "",
            request_data=self.build_request_data(
                session_id=session_id,
                source_session_id=source_session_id,
            ),
        )


@dataclass
class NotificationTarget:
    """Notification delivery target descriptor."""

    sink_type: str
    response_url: str = ""
    channel_name: str = ""
    chat_id: str = ""
    message_id: str = ""
    request_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationResult:
    """Result of a notification delivery attempt."""

    success: bool
    sink_type: str
    message_id: Optional[str] = None
    error: Optional[str] = None

# -*- coding: utf-8 -*-
"""Execution binding models.

These models describe the control-plane mapping between an upper session
(chat/task/session record) and the lower-level CLI session that actually
executes the work.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ConfigDict


def _now_ms() -> int:
    return int(time.time() * 1000)


class ExecutionBinding(BaseModel):
    """Control-plane metadata for a session↔CLI mapping."""

    session_id: str = Field(..., description="Upper-level session ID")
    cli_session_id: Optional[str] = Field(None, description="Underlying CLI session UUID")
    session_kind: Optional[str] = Field(None, description="Session kind: chat | task | history")
    provider: Optional[str] = Field(None, description="Provider or base provider")
    alias: Optional[str] = Field(None, description="Alias used for execution")
    exec_user: Optional[str] = Field(None, description="Linux exec user")
    work_dir: Optional[str] = Field(None, description="Execution working directory")
    source_type: Optional[str] = Field(None, description="Origin of the binding: history | task | chat | runtime")
    source_session_id: Optional[str] = Field(None, description="Upstream source session ID")
    task_id: Optional[str] = Field(None, description="Associated task ID, if any")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional control-plane metadata")
    created_at: int = Field(default_factory=_now_ms, description="Creation timestamp (ms)")
    updated_at: int = Field(default_factory=_now_ms, description="Update timestamp (ms)")
    expires_at: Optional[float] = Field(None, description="Expiry timestamp (unix seconds)")

    model_config = ConfigDict(extra="ignore")

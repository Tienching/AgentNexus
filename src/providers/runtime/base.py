# -*- coding: utf-8 -*-
"""
Provider 基础接口
"""

from dataclasses import dataclass, field
from typing import Protocol, AsyncIterator, Any, Optional, runtime_checkable
from pathlib import Path

from src.runtime.events import Event


@dataclass
class RunContext:
    """执行上下文"""
    session_id: str
    workspace: Optional[Path] = None
    exec_user: Optional[str] = None
    model: Optional[str] = None
    max_turns: int = 10
    permission_mode: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "workspace": str(self.workspace) if self.workspace else None,
            "exec_user": self.exec_user,
            "model": self.model,
            "max_turns": self.max_turns,
            "permission_mode": self.permission_mode,
            "metadata": self.metadata,
        }


@runtime_checkable
class Executor(Protocol):
    """执行器接口 - 负责实际执行"""
    
    async def run(
        self,
        prompt: str,
        context: RunContext,
    ) -> AsyncIterator[dict[str, Any]]:
        """执行并产出 raw 事件（provider 原始格式）"""
        ...


@runtime_checkable
class Provider(Protocol):
    """Provider 接口 - 负责执行 + 翻译成统一事件"""
    
    name: str
    
    async def execute(
        self,
        prompt: str,
        context: RunContext,
    ) -> AsyncIterator[Event]:
        """执行并产出统一事件流"""
        ...
    
    def supports_capability(self, capability: str) -> bool:
        """检查是否支持某能力"""
        ...
    
    def get_executor(self) -> Executor:
        """获取底层执行器"""
        ...

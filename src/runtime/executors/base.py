# -*- coding: utf-8 -*-
"""
Base executor interface for CLI subprocess execution.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pwd
import shlex
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ExecutorConfig:
    """Configuration for CLI executors."""
    
    timeout: float = 600.0
    user_home_base: str = "/home"
    
    # Additional config fields
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RequestContext:
    """Unified request context for CLI execution.
    
    This replaces the tight coupling to RequestModel from API layer.
    """
    
    content: str
    user: str = "anonymous"
    session_id: str = "default"
    exec_user: str = "default"
    cwd: Optional[str] = None
    cwd_mode: str = ""
    run_kind: str = ""
    model: Optional[str] = None  # LLM model name override
    cli_session_id: Optional[str] = None  # CLI session UUID for precise resume
    session_cleared: bool = False  # True if /clear was just executed; skip resume
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_request_model(cls, model_obj: Any, exec_user: str = "default") -> "RequestContext":
        """Create from legacy RequestModel for backward compatibility."""
        return cls(
            content=getattr(model_obj, "content", "") or "",
            user=getattr(model_obj, "user", None) or "anonymous",
            session_id=getattr(model_obj, "session_id", None) or "default",
            exec_user=exec_user,
            cwd=getattr(model_obj, "cwd", None),
            cwd_mode=getattr(model_obj, "cwd_mode", "") or "",
            run_kind=getattr(model_obj, "run_kind", "") or "",
            model=getattr(model_obj, "model", None) or None,
            cli_session_id=getattr(model_obj, "cli_session_id", None) or None,
        )


class BaseExecutor(ABC):
    """Base class for CLI subprocess executors.
    
    Provides common functionality for:
    - Working directory resolution
    - Process execution with timeout
    - Stream reading
    - Error handling
    """
    
    def __init__(self, config: Optional[ExecutorConfig] = None):
        self.config = config or ExecutorConfig()
    
    @abstractmethod
    async def execute(
        self,
        context: RequestContext,
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Execute CLI and yield stream output.
        
        Args:
            context: Unified request context
            output_format: "raw" (JSON lines) or "legacy" (event:delta SSE)
            
        Yields:
            Output lines (format depends on output_format)
        """
        pass
    
    @abstractmethod
    def _build_command(self, context: RequestContext) -> List[str]:
        """Build the CLI command to execute."""
        pass
    
    def resolve_exec_dir(self, context: RequestContext) -> Path:
        """Resolve the execution directory.
        
        Logic mirrors CLIExecutor behavior:
        - If cwd_mode="inplace" and cwd is set, use that directly
        - Otherwise, use session-based directory under user home
        """
        if context.cwd_mode == "inplace" and context.cwd:
            return Path(str(context.cwd))
        
        base = self.config.user_home_base
        preferred_dir = Path(base) / context.exec_user / ".nexus" / "sessions" / context.session_id
        
        current_user = pwd.getpwuid(os.getuid()).pw_name
        if current_user != context.exec_user and os.geteuid() != 0:
            # Non-root fallback
            exec_dir = Path.home() / context.exec_user / ".nexus" / "sessions" / context.session_id
        else:
            exec_dir = preferred_dir
        
        exec_dir.mkdir(parents=True, exist_ok=True)
        return exec_dir
    
    def wrap_command_for_user(
        self,
        cmd: List[str],
        exec_dir: Path,
        target_user: str,
    ) -> List[str]:
        """Wrap command with cd and optionally su.
        
        Returns:
            Shell command list ready for execution
        """
        current_user = pwd.getpwuid(os.getuid()).pw_name
        cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
        full_cmd = f"cd {shlex.quote(str(exec_dir))} && {cmd_str}"
        
        if current_user == target_user:
            return ["bash", "-c", full_cmd]
        else:
            return ["su", "-", target_user, "-c", full_cmd]
    
    async def run_subprocess(
        self,
        final_cmd: List[str],
        timeout: Optional[float] = None,
    ) -> asyncio.subprocess.Process:
        """Create and return a subprocess.
        
        Args:
            final_cmd: Command list to execute
            timeout: Optional timeout override
            
        Returns:
            Running subprocess
        """
        return await asyncio.create_subprocess_exec(
            *final_cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=10 * 1024 * 1024,
        )
    
    async def read_stream(
        self,
        process: asyncio.subprocess.Process,
        timeout: float,
    ) -> AsyncGenerator[bytes, None]:
        """Read lines from process stdout with timeout.
        
        Args:
            process: Running subprocess
            timeout: Line read timeout
            
        Yields:
            Raw line bytes
        """
        while True:
            try:
                line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except Exception:
                    pass
                raise
            
            if not line:
                break
            
            yield line
    
    async def drain_stderr(self, process: asyncio.subprocess.Process) -> Optional[str]:
        """Best-effort stderr drain.
        
        Returns:
            Stderr content (truncated) or None
        """
        try:
            if process.stderr:
                stderr_data = await process.stderr.read()
                if isinstance(stderr_data, (bytes, bytearray)) and stderr_data:
                    return stderr_data[:1000].decode("utf-8", errors="replace")
        except Exception:
            pass
        return None

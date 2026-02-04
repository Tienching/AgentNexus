# -*- coding: utf-8 -*-
"""Codex CLI Executor

This executor runs Codex CLI via MCP JSON-RPC protocol.
Based on AionUI's CodexAgent implementation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from ..base import BaseExecutor, ExecutorConfig, RequestContext
from .connection import CodexConnection, CodexConnectionConfig, CodexEvent

logger = logging.getLogger(__name__)


class CodexExecutorConfig(ExecutorConfig):
    """Codex-specific configuration."""
    
    def __init__(
        self,
        timeout: float = 120.0,
        user_home_base: str = "/home",
        codex_command: str = "codex",
        mcp_server_mode: str = "auto",
        approval_policy: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(timeout=timeout, user_home_base=user_home_base)
        self.codex_command = codex_command
        self.mcp_server_mode = mcp_server_mode
        self.approval_policy = approval_policy  # untrusted, on-failure, on-request, never
        self.extra.update(kwargs)


class CodexExecutor(BaseExecutor):
    """Codex CLI executor via MCP JSON-RPC.
    
    Unlike CCR/Gemini executors that use command-line streaming,
    Codex uses MCP protocol for bidirectional communication.
    """
    
    def __init__(self, config: Optional[CodexExecutorConfig] = None):
        super().__init__(config or CodexExecutorConfig())
        self._connection: Optional[CodexConnection] = None
    
    @property
    def codex_config(self) -> CodexExecutorConfig:
        """Get Codex-specific config."""
        return self.config  # type: ignore
    
    async def execute(
        self,
        context: RequestContext,
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Execute Codex command and yield stream output.
        
        Args:
            context: Request context
            output_format: "raw" yields Codex events as JSON lines
            
        Yields:
            JSON-encoded Codex events
        """
        start_time = time.time()
        
        # Validate
        if not context.content:
            raise ValueError("Missing required field: content")
        
        # Resolve execution directory
        exec_dir = self.resolve_exec_dir(context)
        
        logger.info(
            f"Starting Codex processing",
            extra={
                "process_type": "codex_start",
                "agent_name": context.agent_name,
                "content_preview": context.content[:100] if len(context.content) > 100 else context.content,
                "exec_dir": str(exec_dir),
            }
        )
        
        # Initialize connection
        conn_config = CodexConnectionConfig(
            cli_path=self.codex_config.codex_command,
            request_timeout=self.codex_config.timeout,
            approval_policy=self.codex_config.approval_policy,
        )
        self._connection = CodexConnection(conn_config)
        
        try:
            # Start codex process
            mcp_args = None
            if (self.codex_config.mcp_server_mode or "auto").strip().lower() != "auto":
                mcp_args = self._build_mcp_server_command()[1:]
            await self._connection.start(str(exec_dir), args=mcp_args)
            
            # Initialize MCP
            await self._connection.request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "virtual-human-sdk",
                    "version": "1.0.0"
                }
            })
            
            # Create session and send prompt via tools/call
            session_id = context.session_id or str(uuid.uuid4())
            
            # Call the codex tool to start a session
            result = await self._connection.request("tools/call", {
                "name": "codex",
                "arguments": {
                    "prompt": context.content,
                    "session_id": session_id,
                }
            })
            
            # Yield initial result if any
            if result:
                yield json.dumps({
                    "type": "init",
                    "session_id": session_id,
                    "result": result,
                })
            
            # Read events from the connection
            async for event in self._connection.read_events():
                if event.method == "codex/event":
                    # Yield the event as JSON
                    event_data = {
                        "type": "codex_event",
                        "method": event.method,
                        "params": event.params,
                    }
                    yield json.dumps(event_data)
                    
                    # Check for task completion
                    if event.params and isinstance(event.params, dict):
                        msg = event.params.get("msg", {})
                        if isinstance(msg, dict):
                            msg_type = msg.get("type")
                            if msg_type == "task_complete":
                                break
                            elif msg_type in ("exec_approval_request", "apply_patch_approval_request"):
                                # For permission requests, we need to handle them
                                # In auto-approve mode, we auto-respond
                                if self.codex_config.approval_policy == "never":
                                    call_id = msg.get("call_id")
                                    if call_id:
                                        self._connection.respond_elicitation(
                                            event.params.get("_meta", {}).get("requestId", 0),
                                            "approved"
                                        )
                
                elif event.method == "elicitation/create":
                    # Permission request - yield for frontend handling
                    yield json.dumps({
                        "type": "permission_request",
                        "method": event.method,
                        "params": event.params,
                    })
            
            duration = time.time() - start_time
            logger.info(f"Codex processing completed", extra={
                "process_type": "codex_complete",
                "duration_ms": int(duration * 1000),
            })
            
        except asyncio.TimeoutError:
            logger.error(f"Codex command timeout", extra={"timeout_seconds": self.config.timeout})
            yield json.dumps({"type": "error", "message": "处理超时，请重试"})
            
        except Exception as e:
            logger.error(f"Codex process error: {e}", exc_info=True)
            yield json.dumps({"type": "error", "message": str(e)})
            
        finally:
            if self._connection:
                await self._connection.stop()
                self._connection = None
    
    def _build_command(self, context: RequestContext) -> List[str]:
        """Build codex command (for reference, not used in MCP mode)."""
        return self._build_mcp_server_command()

    def _build_mcp_server_command(self) -> List[str]:
        """Build codex MCP server command."""
        base_cmd = [self.codex_config.codex_command]
        mode = (self.codex_config.mcp_server_mode or "auto").strip().lower()
        if mode in ("auto", "mcp-server", "mcp_server", "mcpserver"):
            return base_cmd + ["mcp-server"]
        if mode in ("mcp", "mcp-serve", "mcp serve", "serve"):
            return base_cmd + ["mcp", "serve"]
        # Fallback: split custom mode string
        return base_cmd + mode.split()
    
    async def send_prompt(self, prompt: str) -> None:
        """Send additional prompt to existing session.
        
        Args:
            prompt: The prompt text
        """
        if not self._connection or not self._connection.is_connected:
            raise RuntimeError("No active connection")
        
        await self._connection.request("tools/call", {
            "name": "codex",
            "arguments": {
                "prompt": prompt,
            }
        })
    
    def resolve_permission(self, call_id: str, approved: bool) -> None:
        """Resolve a permission request.
        
        Args:
            call_id: The permission request call ID
            approved: Whether to approve or deny
        """
        if not self._connection or not self._connection.is_connected:
            return
        
        decision = "approved" if approved else "denied"
        # Note: In actual implementation, we need to track the request ID
        # This is a simplified version
        logger.info(f"Permission resolved: {call_id} -> {decision}")

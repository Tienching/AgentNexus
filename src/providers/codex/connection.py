# -*- coding: utf-8 -*-
"""Codex MCP Connection

JSON-RPC over stdin/stdout communication with codex mcp-server.
Based on AionUI's CodexConnection implementation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

JSONRPC_VERSION = "2.0"


@dataclass
class CodexEvent:
    """Codex event envelope from JSON-RPC notification."""
    method: str
    params: Optional[Dict[str, Any]] = None


@dataclass 
class CodexConnectionConfig:
    """Connection configuration."""
    cli_path: str = "codex"
    startup_timeout: float = 10.0
    request_timeout: float = 200.0
    approval_policy: Optional[str] = None  # untrusted, on-failure, on-request, never


class CodexConnection:
    """MCP JSON-RPC connection manager for Codex CLI.
    
    Handles:
    - Starting codex mcp-server subprocess
    - JSON-RPC request/response over stdin/stdout
    - Event stream reading
    - Permission request handling
    """
    
    def __init__(self, config: Optional[CodexConnectionConfig] = None):
        self.config = config or CodexConnectionConfig()
        self._process: Optional[asyncio.subprocess.Process] = None
        self._next_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._detected_version: Optional[str] = None
        self._read_task: Optional[asyncio.Task] = None
        self._event_queue: asyncio.Queue[CodexEvent] = asyncio.Queue()
        self._is_running = False
        
        # Callbacks
        self.on_event: Optional[Callable[[CodexEvent], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
    
    @property
    def is_connected(self) -> bool:
        """Check if connection is active."""
        return self._process is not None and self._process.returncode is None
    
    @property
    def version(self) -> Optional[str]:
        """Get detected Codex version."""
        return self._detected_version

    def _build_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build JSON-RPC request payload."""
        request_id = self._next_id
        self._next_id += 1
        payload: Dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        return payload

    def _build_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build JSON-RPC notification payload."""
        payload: Dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        return payload
    
    def _detect_mcp_command(self) -> List[str]:
        """Detect MCP command based on Codex version.
        
        - Version >= 0.40.0: use 'mcp-server'
        - Version < 0.40.0: use 'mcp serve'
        """
        try:
            import subprocess
            result = subprocess.run(
                [self.config.cli_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version_output = result.stdout.strip()
            
            # Extract version number
            match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_output)
            if match:
                self._detected_version = match.group(0)
                major = int(match.group(1))
                minor = int(match.group(2))
                
                # Version 0.40.0+ uses mcp-server
                if major > 0 or (major == 0 and minor >= 40):
                    return ["mcp-server"]
                else:
                    return ["mcp", "serve"]
        except Exception as e:
            logger.warning(f"Failed to detect codex version: {e}")
        
        # Default to mcp-server (newer versions)
        return ["mcp-server"]
    
    async def start(self, cwd: str, args: Optional[List[str]] = None) -> None:
        """Start codex mcp-server subprocess.
        
        Args:
            cwd: Working directory for the codex process
            args: Optional additional arguments
        """
        if self.is_connected:
            logger.warning("Connection already active, stopping first")
            await self.stop()
        
        # Detect MCP command
        mcp_args = args if args else self._detect_mcp_command()
        
        # Add approval policy if configured
        if self.config.approval_policy:
            mcp_args = [*mcp_args, "-c", f"approval_policy={self.config.approval_policy}"]
        
        cmd = [self.config.cli_path] + mcp_args
        
        logger.info(f"Starting codex process: {' '.join(cmd)} in {cwd}")
        
        # Clean environment for subprocess
        env = {**os.environ}
        for key in ["NODE_OPTIONS", "NODE_INSPECT", "NODE_DEBUG"]:
            env.pop(key, None)
        env["CODEX_NO_INTERACTIVE"] = "1"
        env["CODEX_AUTO_CONTINUE"] = "1"
        
        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                limit=10 * 1024 * 1024,
            )
            
            self._is_running = True
            
            # Start background reader task
            self._read_task = asyncio.create_task(self._read_loop())
            
            # Wait for startup
            await asyncio.sleep(1.0)
            
            if self._process.returncode is not None:
                stderr = await self._process.stderr.read() if self._process.stderr else b""
                raise RuntimeError(f"Codex process exited immediately: {stderr.decode()}")
            
            logger.info(f"Codex process started, version: {self._detected_version}")
            
        except FileNotFoundError:
            raise RuntimeError(f"Codex CLI not found at: {self.config.cli_path}")
        except Exception as e:
            self._is_running = False
            raise RuntimeError(f"Failed to start codex: {e}")
    
    async def stop(self) -> None:
        """Stop the codex process."""
        self._is_running = False
        
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None
        
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            except Exception:
                pass
            self._process = None
        
        # Reject all pending requests
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError("Connection closed"))
        self._pending.clear()
        
        logger.info("Codex connection stopped")
    
    async def request(
        self, 
        method: str, 
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Send JSON-RPC request and wait for response.
        
        Args:
            method: RPC method name
            params: Optional parameters
            timeout: Request timeout (default from config)
            
        Returns:
            Response result
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to codex")
        
        request = self._build_request(method, params)
        request_id = request["id"]

        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        # Send request
        line = json.dumps(request) + "\n"
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()
        
        # Wait for response
        try:
            result = await asyncio.wait_for(
                future,
                timeout=timeout or self.config.request_timeout
            )
            return result
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise RuntimeError(f"Request timed out: {method}")
    
    def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Send JSON-RPC notification (no response expected).
        
        Args:
            method: RPC method name
            params: Optional parameters
        """
        if not self.is_connected:
            return
        
        notification = self._build_notification(method, params)
        line = json.dumps(notification) + "\n"
        self._process.stdin.write(line.encode())
        # Don't await drain for notifications
    
    def respond_elicitation(
        self, 
        request_id: int, 
        decision: str,
    ) -> None:
        """Respond to an elicitation/permission request.
        
        Args:
            request_id: The JSON-RPC request ID to respond to
            decision: One of 'approved', 'approved_for_session', 'denied', 'abort'
        """
        if not self.is_connected:
            return
        
        response = {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": {"decision": decision},
        }
        
        line = json.dumps(response) + "\n"
        self._process.stdin.write(line.encode())
    
    async def read_events(self) -> AsyncGenerator[CodexEvent, None]:
        """Read events from the event queue.
        
        Yields:
            CodexEvent objects
        """
        while self._is_running:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=1.0
                )
                yield event
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
    
    async def _read_loop(self) -> None:
        """Background task to read and process stdout."""
        buffer = ""
        
        try:
            while self._is_running and self._process:
                try:
                    line = await asyncio.wait_for(
                        self._process.stdout.readline(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                if not line:
                    # Process ended
                    break
                
                line_str = line.decode().strip()
                if not line_str:
                    continue
                
                # Try to parse as JSON-RPC
                if line_str.startswith("{") and line_str.endswith("}"):
                    try:
                        msg = json.loads(line_str)
                        await self._handle_message(msg)
                    except json.JSONDecodeError:
                        logger.debug(f"Non-JSON output: {line_str[:100]}")
                else:
                    # Handle non-JSON output (startup messages, etc.)
                    logger.debug(f"Codex output: {line_str[:200]}")
                    
                    # Auto-press Enter for interactive prompts
                    if "Press Enter to continue" in line_str:
                        self._process.stdin.write(b"\n")
                        await self._process.stdin.drain()
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in read loop: {e}")
            if self.on_error:
                self.on_error(str(e))
    
    async def _handle_message(self, msg: Dict[str, Any]) -> None:
        """Handle incoming JSON-RPC message."""
        # Response to a request
        if "id" in msg and ("result" in msg or "error" in msg):
            request_id = msg["id"]
            future = self._pending.pop(request_id, None)
            
            if future and not future.done():
                if "error" in msg:
                    error = msg["error"]
                    error_msg = error.get("message", str(error))
                    future.set_exception(RuntimeError(error_msg))
                else:
                    future.set_result(msg.get("result"))
            return
        
        # Event/notification
        if "method" in msg:
            event = CodexEvent(
                method=msg["method"],
                params=msg.get("params")
            )
            
            # Put in queue for async iteration
            await self._event_queue.put(event)
            
            # Also call callback if set
            if self.on_event:
                self.on_event(event)

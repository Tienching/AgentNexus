# -*- coding: utf-8 -*-
"""Codex -> AG-UI Protocol Adapter

Converts Codex MCP events to AG-UI protocol format.
Based on Codex event types from AionUI.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

from ..base import BaseAdapter, ProtocolType, AdapterState
from src.runtime.events.agui import (
    MessageRole,
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    build_tool_call_start_metadata,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    StateSnapshotEvent,
    CustomEvent,
)

logger = logging.getLogger(__name__)


class CodexAdapterState(AdapterState):
    """Extended state for Codex adapter."""
    
    def __init__(self, thread_id: str, run_id: str):
        super().__init__(thread_id, run_id)
        self.reasoning_message_id: Optional[str] = None
        self.reasoning_started = False
        self.pending_tool_calls: Dict[str, Dict[str, Any]] = {}  # call_id -> tool info


class CodexAGUIAdapter(BaseAdapter):
    """Codex event to AG-UI protocol adapter.
    
    Handles conversion of Codex MCP events to AG-UI SSE format.
    
    Codex Event Types:
    - task_started: Task begins
    - task_complete: Task ends
    - agent_message_delta: Streaming text output
    - agent_message: Complete text output
    - agent_reasoning_delta: Thinking/reasoning text
    - exec_command_begin/end: Shell command execution
    - patch_apply_begin/end: File modification
    - mcp_tool_call_begin/end: MCP tool invocation
    - web_search_begin/end: Web search
    - exec_approval_request: Permission request for command
    - apply_patch_approval_request: Permission request for file edit
    """
    
    def __init__(self):
        super().__init__()
        self._state: Optional[CodexAdapterState] = None
    
    @property
    def state(self) -> Optional[CodexAdapterState]:
        return self._state
    
    @state.setter
    def state(self, value: Optional[AdapterState]) -> None:
        if value is None:
            self._state = None
        elif isinstance(value, CodexAdapterState):
            self._state = value
        else:
            # Convert base AdapterState to CodexAdapterState
            self._state = CodexAdapterState(value.thread_id, value.run_id)
    
    def init_state(self, thread_id: str, run_id: str) -> None:
        """Initialize adapter state."""
        self._state = CodexAdapterState(thread_id, run_id)
    
    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.AGUI
    
    def _generate_message_id(self) -> str:
        """Generate unique message ID."""
        return f"codex-msg-{uuid.uuid4().hex[:12]}"
    
    def _generate_tool_call_id(self) -> str:
        """Generate unique tool call ID."""
        return f"codex-tool-{uuid.uuid4().hex[:12]}"
    
    def convert(self, codex_event: Dict[str, Any]) -> Optional[str]:
        """Convert Codex event to AG-UI format.
        
        Args:
            codex_event: Codex event from MCP stream
            
        Returns:
            AG-UI SSE formatted string or None
        """
        if not self._state:
            return None
        
        event_type = codex_event.get("type")
        
        # Handle wrapper types from executor
        if event_type == "init":
            return self._handle_init(codex_event)
        elif event_type == "codex_event":
            return self._handle_codex_event(codex_event)
        elif event_type == "permission_request":
            return self._handle_permission_request(codex_event)
        elif event_type == "error":
            return self.create_error_event(codex_event.get("message", "Unknown error"))
        
        # Handle raw Codex event types (if passed directly)
        return self._convert_raw_event(codex_event)
    
    def _handle_init(self, event: Dict[str, Any]) -> Optional[str]:
        """Handle init event from executor."""
        if self._state.run_started:
            return None
        return self.create_start_event()
    
    def _handle_codex_event(self, event: Dict[str, Any]) -> Optional[str]:
        """Handle codex/event method."""
        params = event.get("params", {})
        msg = params.get("msg", {})
        
        if not isinstance(msg, dict):
            return None
        
        return self._convert_raw_event(msg)
    
    def _handle_permission_request(self, event: Dict[str, Any]) -> Optional[str]:
        """Handle permission/elicitation request."""
        params = event.get("params", {})
        
        # Create custom event for permission request
        custom = CustomEvent(
            name="permission_request",
            value={
                "type": params.get("type", "unknown"),
                "call_id": params.get("call_id") or params.get("codex_call_id"),
                "data": params,
            }
        )
        return custom.to_sse()
    
    def _convert_raw_event(self, msg: Dict[str, Any]) -> Optional[str]:
        """Convert raw Codex event message."""
        msg_type = msg.get("type")
        
        if not msg_type:
            return None
        
        # Task lifecycle
        if msg_type == "task_started":
            return self._handle_task_started(msg)
        elif msg_type == "task_complete":
            return self._handle_task_complete(msg)
        
        # Text messages
        elif msg_type == "agent_message_delta":
            return self._handle_message_delta(msg)
        elif msg_type == "agent_message":
            # Final complete message - usually ignored as we use delta
            return None
        
        # Reasoning/thinking
        elif msg_type == "agent_reasoning_delta":
            return self._handle_reasoning_delta(msg)
        elif msg_type == "agent_reasoning_section_break":
            return self._handle_reasoning_break(msg)
        
        # Command execution
        elif msg_type == "exec_command_begin":
            return self._handle_exec_begin(msg)
        elif msg_type == "exec_command_output_delta":
            return self._handle_exec_output(msg)
        elif msg_type == "exec_command_end":
            return self._handle_exec_end(msg)
        
        # File operations
        elif msg_type == "patch_apply_begin":
            return self._handle_patch_begin(msg)
        elif msg_type == "patch_apply_end":
            return self._handle_patch_end(msg)
        
        # MCP tool calls
        elif msg_type == "mcp_tool_call_begin":
            return self._handle_mcp_tool_begin(msg)
        elif msg_type == "mcp_tool_call_end":
            return self._handle_mcp_tool_end(msg)
        
        # Web search
        elif msg_type == "web_search_begin":
            return self._handle_web_search_begin(msg)
        elif msg_type == "web_search_end":
            return self._handle_web_search_end(msg)
        
        # Permission requests
        elif msg_type == "exec_approval_request":
            return self._handle_exec_approval(msg)
        elif msg_type == "apply_patch_approval_request":
            return self._handle_patch_approval(msg)
        
        # Turn diff (file changes summary)
        elif msg_type == "turn_diff":
            return self._handle_turn_diff(msg)
        
        # Ignored types
        elif msg_type in ("session_configured", "token_count", "agent_reasoning", "user_message"):
            return None
        
        # Unknown - log and skip
        logger.debug(f"Unknown Codex event type: {msg_type}")
        return None
    
    def _handle_task_started(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle task_started event."""
        results = []
        
        # Emit RUN_STARTED if not already done
        if not self._state.run_started:
            results.append(self.create_start_event())
        
        # Create state snapshot with model info
        model_window = msg.get("model_context_window")
        if model_window:
            snapshot = StateSnapshotEvent(
                snapshot={"model_context_window": model_window}
            )
            results.append(snapshot.to_sse())
        
        return "".join(results) if results else None
    
    def _handle_task_complete(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle task_complete event."""
        return self.create_end_event(is_error=False)
    
    def _handle_message_delta(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle agent_message_delta event."""
        delta = msg.get("delta", "")
        if not delta:
            return None
        
        results = []
        
        # Start message if needed
        if not self._state.message_started:
            self._state.current_message_id = self._generate_message_id()
            self._state.message_started = True
            results.append(TextMessageStartEvent(
                messageId=self._state.current_message_id,
                role=MessageRole.ASSISTANT,
            ).to_sse())
        
        # Emit content delta
        results.append(TextMessageContentEvent(
            messageId=self._state.current_message_id,
            delta=delta,
        ).to_sse())
        
        return "".join(results)
    
    def _handle_reasoning_delta(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle agent_reasoning_delta event."""
        delta = msg.get("delta", "")
        if not delta:
            return None
        
        results = []
        
        # Start reasoning message if needed
        if not self._state.reasoning_started:
            self._state.reasoning_message_id = self._generate_message_id()
            self._state.reasoning_started = True
            # Use custom event for reasoning
            results.append(CustomEvent(
                name="reasoning_start",
                value={"messageId": self._state.reasoning_message_id}
            ).to_sse())
        
        # Emit reasoning content
        results.append(CustomEvent(
            name="reasoning_content",
            value={
                "messageId": self._state.reasoning_message_id,
                "delta": delta,
            }
        ).to_sse())
        
        return "".join(results)
    
    def _handle_reasoning_break(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle agent_reasoning_section_break event."""
        if self._state.reasoning_started:
            self._state.reasoning_started = False
            return CustomEvent(
                name="reasoning_end",
                value={"messageId": self._state.reasoning_message_id}
            ).to_sse()
        return None
    
    def _handle_exec_begin(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle exec_command_begin event."""
        call_id = msg.get("call_id", self._generate_tool_call_id())
        command = msg.get("command", [])
        cwd = msg.get("cwd", "")
        
        # Format command string
        if isinstance(command, list):
            cmd_str = " ".join(command)
        else:
            cmd_str = str(command)
        
        # Store pending tool call
        self._state.pending_tool_calls[call_id] = {
            "name": "Shell",
            "command": cmd_str,
            "cwd": cwd,
        }
        
        results = []
        
        # Emit tool call start
        shell_display_name = f"Shell: {cmd_str[:50]}"
        results.append(ToolCallStartEvent(
            toolCallId=call_id,
            toolCallName=shell_display_name,
            parentMessageId=self._state.current_message_id,
            **build_tool_call_start_metadata(
                "Shell",
                {"command": cmd_str},
                display_name=shell_display_name,
            ),
        ).to_sse())
        
        # Emit args
        args = json.dumps({"command": cmd_str, "cwd": cwd}, ensure_ascii=False)
        results.append(ToolCallArgsEvent(
            toolCallId=call_id,
            delta=args,
        ).to_sse())
        
        return "".join(results)
    
    def _handle_exec_output(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle exec_command_output_delta event."""
        # Output deltas are usually base64 encoded, we can emit as custom event
        call_id = msg.get("call_id")
        chunk = msg.get("chunk", "")
        stream = msg.get("stream", "stdout")
        
        if not chunk:
            return None
        
        return CustomEvent(
            name="exec_output",
            value={
                "call_id": call_id,
                "stream": stream,
                "chunk": chunk,
            }
        ).to_sse()
    
    def _handle_exec_end(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle exec_command_end event."""
        call_id = msg.get("call_id")
        stdout = msg.get("stdout", "")
        stderr = msg.get("stderr", "")
        exit_code = msg.get("exit_code", 0)
        formatted_output = msg.get("formatted_output", stdout)
        
        # Clean up pending
        self._state.pending_tool_calls.pop(call_id, None)
        
        results = []
        
        # Emit tool result
        if self._state.current_message_id:
            result_content = formatted_output or stdout
            if exit_code != 0 and stderr:
                result_content += f"\nError: {stderr}"
            
            results.append(ToolCallResultEvent(
                messageId=self._state.current_message_id,
                toolCallId=call_id,
                content=result_content[:2000],  # Truncate long output
            ).to_sse())
        
        # Emit tool end
        results.append(ToolCallEndEvent(
            toolCallId=call_id,
            result=f"exit_code={exit_code}",
        ).to_sse())
        
        return "".join(results)
    
    def _handle_patch_begin(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle patch_apply_begin event."""
        call_id = msg.get("call_id", self._generate_tool_call_id())
        changes = msg.get("changes", {})
        
        # Format file list
        files = list(changes.keys()) if changes else []
        
        self._state.pending_tool_calls[call_id] = {
            "name": "Edit",
            "files": files,
        }
        
        results = []
        
        edit_display_name = f"Edit: {len(files)} file(s)"
        results.append(ToolCallStartEvent(
            toolCallId=call_id,
            toolCallName=edit_display_name,
            parentMessageId=self._state.current_message_id,
            **build_tool_call_start_metadata(
                "Edit",
                {"description": ", ".join(files) if files else ""},
                display_name=edit_display_name,
            ),
        ).to_sse())
        
        args = json.dumps({"files": files}, ensure_ascii=False)
        results.append(ToolCallArgsEvent(
            toolCallId=call_id,
            delta=args,
        ).to_sse())
        
        return "".join(results)
    
    def _handle_patch_end(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle patch_apply_end event."""
        call_id = msg.get("call_id")
        success = msg.get("success", True)
        stdout = msg.get("stdout", "")
        stderr = msg.get("stderr", "")
        
        self._state.pending_tool_calls.pop(call_id, None)
        
        results = []
        
        result_content = stdout if success else f"Failed: {stderr}"
        
        if self._state.current_message_id:
            results.append(ToolCallResultEvent(
                messageId=self._state.current_message_id,
                toolCallId=call_id,
                content=result_content,
            ).to_sse())
        
        results.append(ToolCallEndEvent(
            toolCallId=call_id,
            result="success" if success else "failed",
        ).to_sse())
        
        return "".join(results)
    
    def _handle_mcp_tool_begin(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle mcp_tool_call_begin event."""
        invocation = msg.get("invocation", {})
        call_id = msg.get("call_id", self._generate_tool_call_id())
        
        server = invocation.get("server", "unknown")
        tool = invocation.get("tool", "unknown")
        arguments = invocation.get("arguments", {})
        
        self._state.pending_tool_calls[call_id] = {
            "name": f"MCP:{server}/{tool}",
            "server": server,
            "tool": tool,
        }
        
        results = []
        
        mcp_display_name = f"MCP: {server}/{tool}"
        results.append(ToolCallStartEvent(
            toolCallId=call_id,
            toolCallName=mcp_display_name,
            parentMessageId=self._state.current_message_id,
            **build_tool_call_start_metadata(
                "MCP",
                arguments,
                display_name=mcp_display_name,
            ),
        ).to_sse())
        
        if arguments:
            args = json.dumps(arguments, ensure_ascii=False)
            results.append(ToolCallArgsEvent(
                toolCallId=call_id,
                delta=args,
            ).to_sse())
        
        return "".join(results)
    
    def _handle_mcp_tool_end(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle mcp_tool_call_end event."""
        call_id = msg.get("call_id")
        result = msg.get("result", {})
        error = msg.get("error")
        
        self._state.pending_tool_calls.pop(call_id, None)
        
        results = []
        
        # Extract result content
        if error:
            result_content = f"Error: {error}"
        elif isinstance(result, dict):
            ok_result = result.get("Ok", {})
            content_list = ok_result.get("content", [])
            if content_list:
                text_parts = []
                for item in content_list:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                result_content = "\n".join(text_parts)[:2000]
            else:
                result_content = json.dumps(result, ensure_ascii=False)[:2000]
        else:
            result_content = str(result)[:2000]
        
        if self._state.current_message_id:
            results.append(ToolCallResultEvent(
                messageId=self._state.current_message_id,
                toolCallId=call_id,
                content=result_content,
            ).to_sse())
        
        results.append(ToolCallEndEvent(
            toolCallId=call_id,
            result="error" if error else "success",
        ).to_sse())
        
        return "".join(results)
    
    def _handle_web_search_begin(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle web_search_begin event."""
        call_id = msg.get("call_id", self._generate_tool_call_id())
        query = msg.get("query", "")
        
        self._state.pending_tool_calls[call_id] = {"name": "WebSearch"}
        
        return ToolCallStartEvent(
            toolCallId=call_id,
            toolCallName="Web Search",
            parentMessageId=self._state.current_message_id,
            **build_tool_call_start_metadata("Web Search", {"query": query}),
        ).to_sse()
    
    def _handle_web_search_end(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle web_search_end event."""
        call_id = msg.get("call_id")
        query = msg.get("query", "")
        
        self._state.pending_tool_calls.pop(call_id, None)
        
        results = []
        
        if self._state.current_message_id:
            results.append(ToolCallResultEvent(
                messageId=self._state.current_message_id,
                toolCallId=call_id,
                content=f"Searched: {query}",
            ).to_sse())
        
        results.append(ToolCallEndEvent(
            toolCallId=call_id,
            result="completed",
        ).to_sse())
        
        return "".join(results)
    
    def _handle_exec_approval(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle exec_approval_request event."""
        call_id = msg.get("call_id")
        command = msg.get("command", [])
        cwd = msg.get("cwd", "")
        reason = msg.get("reason", "")
        
        cmd_str = " ".join(command) if isinstance(command, list) else str(command)
        
        return CustomEvent(
            name="permission_request",
            value={
                "type": "exec_approval",
                "call_id": call_id,
                "command": cmd_str,
                "cwd": cwd,
                "reason": reason,
            }
        ).to_sse()
    
    def _handle_patch_approval(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle apply_patch_approval_request event."""
        call_id = msg.get("call_id")
        changes = msg.get("changes", {}) or msg.get("codex_changes", {})
        reason = msg.get("reason", "")
        
        files = list(changes.keys()) if changes else []
        
        return CustomEvent(
            name="permission_request",
            value={
                "type": "patch_approval",
                "call_id": call_id,
                "files": files,
                "reason": reason,
            }
        ).to_sse()
    
    def _handle_turn_diff(self, msg: Dict[str, Any]) -> Optional[str]:
        """Handle turn_diff event."""
        unified_diff = msg.get("unified_diff", "")
        
        if not unified_diff:
            return None
        
        return CustomEvent(
            name="turn_diff",
            value={"unified_diff": unified_diff}
        ).to_sse()
    
    def format_sse(self, data: Any) -> str:
        """Format data as SSE."""
        if hasattr(data, "to_sse"):
            return data.to_sse()
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    
    def create_start_event(self) -> Optional[str]:
        """Create run started event."""
        if not self._state or self._state.run_started:
            return None
        
        self._state.run_started = True
        return RunStartedEvent(
            threadId=self._state.thread_id,
            runId=self._state.run_id,
        ).to_sse()
    
    def create_end_event(self, is_error: bool = False, error_msg: str = "") -> str:
        """Create run finished event."""
        if not self._state:
            return ""
        
        results = []
        
        # Close any open message
        if self._state.message_started and self._state.current_message_id:
            results.append(TextMessageEndEvent(
                messageId=self._state.current_message_id
            ).to_sse())
            self._state.message_started = False
        
        # Close any open reasoning
        if self._state.reasoning_started and self._state.reasoning_message_id:
            results.append(CustomEvent(
                name="reasoning_end",
                value={"messageId": self._state.reasoning_message_id}
            ).to_sse())
            self._state.reasoning_started = False
        
        # Close any pending tool calls
        for call_id in list(self._state.pending_tool_calls.keys()):
            results.append(ToolCallEndEvent(
                toolCallId=call_id,
                result="interrupted"
            ).to_sse())
        self._state.pending_tool_calls.clear()
        
        # Error event if needed
        if is_error:
            results.append(RunErrorEvent(
                threadId=self._state.thread_id,
                runId=self._state.run_id,
                message=error_msg,
            ).to_sse())
        
        # Run finished
        results.append(RunFinishedEvent(
            threadId=self._state.thread_id,
            runId=self._state.run_id,
        ).to_sse())
        
        self._state.run_finished = True
        return "".join(results)
    
    def create_error_event(self, error_msg: str) -> str:
        """Create error event."""
        if not self._state:
            from src.runtime.utils.ids import gen_session_id, gen_run_id
            thread_id = gen_session_id()
            run_id = gen_run_id()
        else:
            thread_id = self._state.thread_id
            run_id = self._state.run_id
        
        return RunErrorEvent(
            threadId=thread_id,
            runId=run_id,
            message=error_msg,
        ).to_sse()

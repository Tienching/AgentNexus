# -*- coding: utf-8 -*-
"""Codex CLI -> AG-UI Protocol Adapter

Converts Codex `exec --json` output to AG-UI protocol format.
Based on OpenAI Codex documentation: https://developers.openai.com/codex/noninteractive

Codex exec --json event types:
- thread.started: Session started
- turn.started: Turn begins
- item.started: Item processing begins
- item.completed: Item processing completes
- turn.completed: Turn ends with usage stats
- error: Error occurred

Item types (in item.started/completed):
- agent_message: Text output from agent
- reasoning: Agent's reasoning/thinking
- command_execution: Shell command execution
- file_changes: File modifications
- mcp_tool_call: MCP tool invocation
- web_search: Web search operation
- plan_updates: Plan updates
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

from ..base import BaseAdapter, ProtocolType, AdapterState
from src.runtime.events.agui import (
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    CustomEvent,
    MessageRole,
)

logger = logging.getLogger(__name__)


class CodexCLIAdapterState(AdapterState):
    """Extended state for Codex CLI adapter."""
    
    def __init__(self, thread_id: str, run_id: str):
        super().__init__(thread_id, run_id)
        self.reasoning_message_id: Optional[str] = None
        self.reasoning_started = False
        self.pending_items: Dict[str, Dict[str, Any]] = {}  # item_id -> item info
        self.codex_thread_id: Optional[str] = None


class CodexCLIAGUIAdapter(BaseAdapter):
    """Codex CLI exec --json to AG-UI protocol adapter.
    
    Handles conversion of Codex exec JSON events to AG-UI SSE format.
    """
    
    def __init__(self):
        super().__init__()
        self._state: Optional[CodexCLIAdapterState] = None
    
    @property
    def state(self) -> Optional[CodexCLIAdapterState]:
        return self._state
    
    @state.setter
    def state(self, value: Optional[AdapterState]) -> None:
        if value is None:
            self._state = None
        elif isinstance(value, CodexCLIAdapterState):
            self._state = value
        else:
            # Convert base AdapterState to CodexCLIAdapterState
            self._state = CodexCLIAdapterState(value.thread_id, value.run_id)
    
    def init_state(self, thread_id: str, run_id: str) -> None:
        """Initialize adapter state."""
        self._state = CodexCLIAdapterState(thread_id, run_id)
    
    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.AGUI
    
    def _generate_message_id(self) -> str:
        """Generate unique message ID."""
        return f"codex-msg-{uuid.uuid4().hex[:12]}"
    
    def _generate_tool_call_id(self, item_id: str) -> str:
        """Generate tool call ID from item ID."""
        return f"codex-tool-{item_id}"
    
    def convert(self, event: Dict[str, Any]) -> Optional[str]:
        """Convert Codex exec JSON event to AG-UI format.
        
        Args:
            event: Codex exec JSON event
            
        Returns:
            AG-UI SSE formatted string or None
        """
        if not self._state:
            return None
        
        if not isinstance(event, dict):
            return None
        
        event_type = event.get("type")
        
        if not event_type:
            return None
        
        # Thread lifecycle
        if event_type == "thread.started":
            return self._handle_thread_started(event)
        
        # Turn lifecycle
        elif event_type == "turn.started":
            return self._handle_turn_started(event)
        elif event_type == "turn.completed":
            return self._handle_turn_completed(event)
        elif event_type == "turn.failed":
            return self._handle_turn_failed(event)
        
        # Item lifecycle
        elif event_type == "item.started":
            return self._handle_item_started(event)
        elif event_type == "item.completed":
            return self._handle_item_completed(event)
        
        # Error
        elif event_type == "error":
            return self.create_error_event(event.get("message", "Unknown error"))
        
        # Unknown - log and skip
        logger.debug(f"Unknown Codex exec event type: {event_type}")
        return None
    
    def _handle_thread_started(self, event: Dict[str, Any]) -> Optional[str]:
        """Handle thread.started event."""
        self._state.codex_thread_id = event.get("thread_id")
        
        if not self._state.run_started:
            return self.create_start_event()
        return None
    
    def _handle_turn_started(self, event: Dict[str, Any]) -> Optional[str]:
        """Handle turn.started event."""
        # Ensure run is started
        if not self._state.run_started:
            return self.create_start_event()
        return None
    
    def _handle_turn_completed(self, event: Dict[str, Any]) -> Optional[str]:
        """Handle turn.completed event."""
        results = []
        
        # Close any open message
        if self._state.message_started and self._state.current_message_id:
            results.append(TextMessageEndEvent(
                messageId=self._state.current_message_id
            ).to_sse())
            self._state.message_started = False
        
        # Emit usage stats as custom event
        usage = event.get("usage")
        if usage:
            results.append(CustomEvent(
                name="usage_stats",
                value=usage
            ).to_sse())
        
        return "".join(results) if results else None
    
    def _handle_turn_failed(self, event: Dict[str, Any]) -> Optional[str]:
        """Handle turn.failed event."""
        error_msg = event.get("error", "Turn failed")
        return self.create_error_event(error_msg)
    
    def _handle_item_started(self, event: Dict[str, Any]) -> Optional[str]:
        """Handle item.started event."""
        item = event.get("item", {})
        if not isinstance(item, dict):
            return None
        
        item_id = item.get("id")
        item_type = item.get("type")
        
        if not item_id or not item_type:
            return None
        
        # Store pending item
        self._state.pending_items[item_id] = item
        
        # Handle different item types
        if item_type == "command_execution":
            return self._handle_command_start(item)
        elif item_type == "file_changes":
            return self._handle_file_changes_start(item)
        elif item_type == "mcp_tool_call":
            return self._handle_mcp_tool_start(item)
        elif item_type == "web_search":
            return self._handle_web_search_start(item)
        
        return None
    
    def _handle_item_completed(self, event: Dict[str, Any]) -> Optional[str]:
        """Handle item.completed event."""
        item = event.get("item", {})
        if not isinstance(item, dict):
            return None
        
        item_id = item.get("id")
        item_type = item.get("type")
        
        if not item_type:
            return None
        
        # Remove from pending
        if item_id:
            self._state.pending_items.pop(item_id, None)
        
        # Handle different item types
        if item_type == "agent_message":
            return self._handle_agent_message(item)
        elif item_type == "reasoning":
            return self._handle_reasoning(item)
        elif item_type == "command_execution":
            return self._handle_command_end(item)
        elif item_type == "file_changes":
            return self._handle_file_changes_end(item)
        elif item_type == "mcp_tool_call":
            return self._handle_mcp_tool_end(item)
        elif item_type == "web_search":
            return self._handle_web_search_end(item)
        
        return None
    
    def _handle_agent_message(self, item: Dict[str, Any]) -> Optional[str]:
        """Handle agent_message item."""
        text = item.get("text", "")
        if not text:
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
        
        # Emit content
        results.append(TextMessageContentEvent(
            messageId=self._state.current_message_id,
            delta=text,
        ).to_sse())
        
        return "".join(results)
    
    def _handle_reasoning(self, item: Dict[str, Any]) -> Optional[str]:
        """Handle reasoning item."""
        text = item.get("text", "")
        if not text:
            return None
        
        results = []
        
        # Start reasoning if needed
        if not self._state.reasoning_started:
            self._state.reasoning_message_id = self._generate_message_id()
            self._state.reasoning_started = True
            results.append(CustomEvent(
                name="reasoning_start",
                value={"messageId": self._state.reasoning_message_id}
            ).to_sse())
        
        # Emit reasoning content
        results.append(CustomEvent(
            name="reasoning_content",
            value={
                "messageId": self._state.reasoning_message_id,
                "delta": text,
            }
        ).to_sse())
        
        return "".join(results) if results else None
    
    def _handle_command_start(self, item: Dict[str, Any]) -> Optional[str]:
        """Handle command_execution start."""
        item_id = item.get("id")
        command = item.get("command", "")
        
        tool_call_id = self._generate_tool_call_id(item_id)
        
        results = []
        results.append(ToolCallStartEvent(
            toolCallId=tool_call_id,
            toolCallName="bash",
            parentMessageId=self._state.current_message_id,
        ).to_sse())
        
        if command:
            results.append(ToolCallArgsEvent(
                toolCallId=tool_call_id,
                delta=json.dumps({"command": command}, ensure_ascii=False),
            ).to_sse())
        
        return "".join(results)
    
    def _handle_command_end(self, item: Dict[str, Any]) -> Optional[str]:
        """Handle command_execution end."""
        item_id = item.get("id")
        output = item.get("aggregated_output", "")
        exit_code = item.get("exit_code")
        
        tool_call_id = self._generate_tool_call_id(item_id)
        
        result_data = {
            "output": output,
            "exit_code": exit_code,
        }
        
        return ToolCallEndEvent(
            toolCallId=tool_call_id,
            result=json.dumps(result_data, ensure_ascii=False),
        ).to_sse()
    
    def _handle_file_changes_start(self, item: Dict[str, Any]) -> Optional[str]:
        """Handle file_changes start."""
        item_id = item.get("id")
        tool_call_id = self._generate_tool_call_id(item_id)
        
        return ToolCallStartEvent(
            toolCallId=tool_call_id,
            toolCallName="apply_patch",
            parentMessageId=self._state.current_message_id,
        ).to_sse()
    
    def _handle_file_changes_end(self, item: Dict[str, Any]) -> Optional[str]:
        """Handle file_changes end."""
        item_id = item.get("id")
        tool_call_id = self._generate_tool_call_id(item_id)
        
        # Extract file changes info
        changes = item.get("changes", [])
        result_data = {"files_changed": len(changes) if isinstance(changes, list) else 0}
        
        return ToolCallEndEvent(
            toolCallId=tool_call_id,
            result=json.dumps(result_data, ensure_ascii=False),
        ).to_sse()
    
    def _handle_mcp_tool_start(self, item: Dict[str, Any]) -> Optional[str]:
        """Handle mcp_tool_call start."""
        item_id = item.get("id")
        tool_name = item.get("tool_name", "mcp_tool")
        tool_call_id = self._generate_tool_call_id(item_id)
        
        results = []
        results.append(ToolCallStartEvent(
            toolCallId=tool_call_id,
            toolCallName=tool_name,
            parentMessageId=self._state.current_message_id,
        ).to_sse())
        
        # Add arguments if available
        arguments = item.get("arguments")
        if arguments:
            results.append(ToolCallArgsEvent(
                toolCallId=tool_call_id,
                delta=json.dumps(arguments, ensure_ascii=False),
            ).to_sse())
        
        return "".join(results)
    
    def _handle_mcp_tool_end(self, item: Dict[str, Any]) -> Optional[str]:
        """Handle mcp_tool_call end."""
        item_id = item.get("id")
        tool_call_id = self._generate_tool_call_id(item_id)
        result = item.get("result", "")
        
        return ToolCallEndEvent(
            toolCallId=tool_call_id,
            result=str(result) if result else "",
        ).to_sse()
    
    def _handle_web_search_start(self, item: Dict[str, Any]) -> Optional[str]:
        """Handle web_search start."""
        item_id = item.get("id")
        query = item.get("query", "")
        tool_call_id = self._generate_tool_call_id(item_id)
        
        results = []
        results.append(ToolCallStartEvent(
            toolCallId=tool_call_id,
            toolCallName="web_search",
            parentMessageId=self._state.current_message_id,
        ).to_sse())
        
        if query:
            results.append(ToolCallArgsEvent(
                toolCallId=tool_call_id,
                delta=json.dumps({"query": query}, ensure_ascii=False),
            ).to_sse())
        
        return "".join(results)
    
    def _handle_web_search_end(self, item: Dict[str, Any]) -> Optional[str]:
        """Handle web_search end."""
        item_id = item.get("id")
        tool_call_id = self._generate_tool_call_id(item_id)
        results_data = item.get("results", [])
        
        return ToolCallEndEvent(
            toolCallId=tool_call_id,
            result=json.dumps(results_data, ensure_ascii=False) if results_data else "",
        ).to_sse()
    
    # BaseAdapter required methods
    
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
            runId=self._state.run_id
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
        
        # Close reasoning if open
        if self._state.reasoning_started and self._state.reasoning_message_id:
            results.append(CustomEvent(
                name="reasoning_end",
                value={"messageId": self._state.reasoning_message_id}
            ).to_sse())
            self._state.reasoning_started = False
        
        if is_error:
            results.append(RunErrorEvent(
                threadId=self._state.thread_id,
                runId=self._state.run_id,
                message=error_msg,
            ).to_sse())
        
        results.append(RunFinishedEvent(
            threadId=self._state.thread_id,
            runId=self._state.run_id
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
            self._state.has_error = True
        
        return RunErrorEvent(
            threadId=thread_id,
            runId=run_id,
            message=error_msg
        ).to_sse()

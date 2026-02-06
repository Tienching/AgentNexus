# -*- coding: utf-8 -*-
"""Codebuddy CLI -> AG-UI adapter"""

import json
import uuid
from typing import Any, Dict, Optional

from src.runtime.adapters import BaseAdapter, ProtocolType
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
    MessageRole,
)


class CodebuddyAGUIAdapter(BaseAdapter):
    """Codebuddy CLI stream-json to AG-UI adapter"""

    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.AGUI

    def _generate_message_id(self) -> str:
        return f"codebuddy-msg-{uuid.uuid4().hex}"

    def convert(self, event: Dict[str, Any]) -> Optional[str]:
        if not self.state or not isinstance(event, dict):
            return None

        event_type = event.get("type")

        if event_type == "system" and event.get("subtype") == "init":
            if not self.state.run_started:
                return self.create_start_event()
            return None

        if event_type == "init":
            if not self.state.run_started:
                return self.create_start_event()
            return None

        if event_type == "topic":
            return None

        if event_type == "error":
            msg = event.get("message") or "Codebuddy CLI error"
            return self.create_error_event(msg)

        if event_type in ("assistant", "user"):
            message = event.get("message")
            if not isinstance(message, dict):
                return None
            contents = message.get("content")
            if not isinstance(contents, list):
                return None
            results = []
            
            # Separate text and tool_use items to handle them properly
            text_items = [item for item in contents if isinstance(item, dict) and item.get("type") == "text"]
            tool_use_items = [item for item in contents if isinstance(item, dict) and item.get("type") == "tool_use"]
            tool_result_items = [item for item in contents if isinstance(item, dict) and item.get("type") == "tool_result"]
            
            # Process text items first
            for item in text_items:
                text = item.get("text", "")
                if not text:
                    continue
                if not self.state.message_started:
                    self.state.current_message_id = self._generate_message_id()
                    self.state.message_started = True
                    results.append(
                        TextMessageStartEvent(
                            messageId=self.state.current_message_id,
                            role=MessageRole.ASSISTANT,
                        ).to_sse()
                    )
                results.append(
                    TextMessageContentEvent(
                        messageId=self.state.current_message_id,
                        delta=text,
                    ).to_sse()
                )
            
            # Process tool_use items - these are part of the same message
            for item in tool_use_items:
                tool_id = item.get("id") or item.get("tool_use_id")
                tool_name = item.get("name") or "unknown"
                parameters = item.get("input")
                if tool_id:
                    # Ensure we have a message context for the tool call
                    if not self.state.current_message_id:
                        self.state.current_message_id = self._generate_message_id()
                        self.state.message_started = True
                        results.append(
                            TextMessageStartEvent(
                                messageId=self.state.current_message_id,
                                role=MessageRole.ASSISTANT,
                            ).to_sse()
                        )
                    
                    if tool_id not in self.state.active_tool_calls:
                        self.state.active_tool_calls[tool_id] = tool_name
                        results.append(
                            ToolCallStartEvent(
                                toolCallId=tool_id,
                                toolCallName=tool_name,
                                parentMessageId=self.state.current_message_id,
                            ).to_sse()
                        )
                    if parameters is not None:
                        args_json = json.dumps(parameters, ensure_ascii=False)
                        results.append(
                            ToolCallArgsEvent(
                                toolCallId=tool_id,
                                delta=args_json,
                            ).to_sse()
                        )
            
            # Process tool_result items
            for item in tool_result_items:
                tool_id = item.get("tool_use_id") or item.get("id")
                output = item.get("content")
                if not tool_id:
                    continue
                if not self.state.current_message_id:
                    self.state.current_message_id = self._generate_message_id()
                    self.state.message_started = True
                content_text = ""
                if isinstance(output, list):
                    parts = []
                    for out_item in output:
                        if isinstance(out_item, dict) and out_item.get("type") == "text":
                            parts.append(out_item.get("text", ""))
                        else:
                            parts.append(str(out_item))
                    content_text = "".join(parts)
                else:
                    content_text = "" if output is None else str(output)
                results.append(
                    ToolCallResultEvent(
                        messageId=self.state.current_message_id,
                        toolCallId=tool_id,
                        content=content_text,
                    ).to_sse()
                )
                results.append(ToolCallEndEvent(toolCallId=tool_id, result=content_text).to_sse())
            return "".join(results) if results else None

        if event_type == "message":
            role = event.get("role")
            if role != "assistant":
                return None
            content = event.get("content", "")
            if not content:
                return None
            results = []
            if not self.state.message_started:
                self.state.current_message_id = self._generate_message_id()
                self.state.message_started = True
                results.append(
                    TextMessageStartEvent(
                        messageId=self.state.current_message_id,
                        role=MessageRole.ASSISTANT,
                    ).to_sse()
                )
            results.append(
                TextMessageContentEvent(
                    messageId=self.state.current_message_id,
                    delta=content,
                ).to_sse()
            )
            return "".join(results)

        if event_type == "tool_use":
            tool_id = event.get("tool_id")
            tool_name = event.get("tool_name") or "unknown"
            parameters = event.get("parameters")
            results = []
            if tool_id:
                if tool_id not in self.state.active_tool_calls:
                    self.state.active_tool_calls[tool_id] = tool_name
                    results.append(
                        ToolCallStartEvent(
                            toolCallId=tool_id,
                            toolCallName=tool_name,
                            parentMessageId=self.state.current_message_id,
                        ).to_sse()
                    )
                if parameters is not None:
                    args_json = json.dumps(parameters, ensure_ascii=False)
                    results.append(
                        ToolCallArgsEvent(
                            toolCallId=tool_id,
                            delta=args_json,
                        ).to_sse()
                    )
            return "".join(results) if results else None

        if event_type == "tool_result":
            tool_id = event.get("tool_id")
            output = event.get("output")
            if not tool_id:
                return None
            if not self.state.current_message_id:
                self.state.current_message_id = self._generate_message_id()
                self.state.message_started = True
            content = "" if output is None else str(output)
            results = [
                ToolCallResultEvent(
                    messageId=self.state.current_message_id,
                    toolCallId=tool_id,
                    content=content,
                ).to_sse(),
                ToolCallEndEvent(toolCallId=tool_id, result=content).to_sse(),
            ]
            return "".join(results)

        if event_type == "result" and event.get("subtype") == "slash_command":
            content = event.get("content") or ""
            if not content:
                return None
            results = []
            if not self.state.message_started:
                self.state.current_message_id = self._generate_message_id()
                self.state.message_started = True
                results.append(
                    TextMessageStartEvent(
                        messageId=self.state.current_message_id,
                        role=MessageRole.ASSISTANT,
                    ).to_sse()
                )
            results.append(
                TextMessageContentEvent(
                    messageId=self.state.current_message_id,
                    delta=content,
                ).to_sse()
            )
            results.append(TextMessageEndEvent(messageId=self.state.current_message_id).to_sse())
            self.state.message_started = False
            return "".join(results)

        # Handle result event (success/error) - this marks the end of a turn
        if event_type == "result":
            subtype = event.get("subtype")
            results = []
            
            # If there's an ongoing message, end it
            if self.state.message_started and self.state.current_message_id:
                results.append(TextMessageEndEvent(messageId=self.state.current_message_id).to_sse())
                self.state.message_started = False
            
            # For error results, emit an error event
            if subtype == "error" or event.get("is_error"):
                error_msg = event.get("result") or event.get("message") or "Unknown error"
                results.append(self.create_error_event(str(error_msg)))
            
            return "".join(results) if results else None

        return None

    def format_sse(self, data: Any) -> str:
        if hasattr(data, "to_sse"):
            return data.to_sse()
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def create_start_event(self) -> Optional[str]:
        if not self.state or self.state.run_started:
            return None
        self.state.run_started = True
        return RunStartedEvent(threadId=self.state.thread_id, runId=self.state.run_id).to_sse()

    def create_end_event(self, is_error: bool = False, error_msg: str = "") -> str:
        if not self.state:
            return ""
        results = []
        if self.state.message_started and self.state.current_message_id:
            results.append(TextMessageEndEvent(messageId=self.state.current_message_id).to_sse())
            self.state.message_started = False
        if is_error:
            results.append(
                RunErrorEvent(
                    threadId=self.state.thread_id,
                    runId=self.state.run_id,
                    message=error_msg,
                ).to_sse()
            )
        results.append(RunFinishedEvent(threadId=self.state.thread_id, runId=self.state.run_id).to_sse())
        self.state.run_finished = True
        return "".join(results)

    def create_error_event(self, error_msg: str) -> str:
        if not self.state:
            thread_id = f"error-{uuid.uuid4()}"
            run_id = f"error-run-{uuid.uuid4()}"
        else:
            thread_id = self.state.thread_id
            run_id = self.state.run_id
        return RunErrorEvent(threadId=thread_id, runId=run_id, message=error_msg).to_sse()

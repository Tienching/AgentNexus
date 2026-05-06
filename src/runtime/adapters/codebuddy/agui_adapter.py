# -*- coding: utf-8 -*-
"""Codebuddy CLI -> AG-UI adapter"""

import json
import re
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
    build_tool_call_name,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    MessageRole,
)


class CodebuddyAGUIAdapter(BaseAdapter):
    """Codebuddy CLI stream-json to AG-UI adapter"""
    
    def __init__(self):
        super().__init__()
        self._reset_tracking_state()
    
    def _reset_tracking_state(self):
        """Reset tracking state (called before each request)"""
        self._in_thinking_block: bool = False
        self._thinking_buffer: str = ""
        self._has_streamed_text_content: bool = False
        self._tool_start_sent: set = set()

    def init_state(self, thread_id: str, run_id: str) -> None:
        """Initialize adapter state (override parent method)"""
        super().init_state(thread_id, run_id)
        self._reset_tracking_state()

    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.AGUI

    def _sanitize_text(self, text: str) -> str:
        """Sanitize text by removing thinking tags.
        
        Handles split thinking tags across stream events.
        """
        if not text:
            return ""
        
        # Append new text to buffer
        self._thinking_buffer += text
        
        # Process thinking tags in buffer
        result_parts = []
        buffer = self._thinking_buffer
        
        while buffer:
            if self._in_thinking_block:
                # In thinking block, look for end tag
                end_match = re.search(r'</think\s*>', buffer)
                if end_match:
                    # Found end tag, skip the thinking block
                    buffer = buffer[end_match.end():]
                    self._in_thinking_block = False
                else:
                    # Still waiting for end tag
                    break
            else:
                # Not in thinking block, look for start tag
                start_match = re.search(r'<think[^>]*>', buffer)
                if start_match:
                    # Found start tag, output content before it
                    result_parts.append(buffer[:start_match.start()])
                    buffer = buffer[start_match.end():]
                    self._in_thinking_block = True
                else:
                    # No start tag, check for partial tag at end
                    partial_match = re.search(r'<(?:thi|th|t)$', buffer)
                    if partial_match:
                        result_parts.append(buffer[:partial_match.start()])
                        self._thinking_buffer = buffer[partial_match.start():]
                        result = "".join(result_parts)
                        return result
                    else:
                        # No partial tag, output all
                        result_parts.append(buffer)
                        buffer = ""
        
        # Update buffer
        self._thinking_buffer = buffer
        
        # Combine results
        result = "".join(result_parts)
        
        return result

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

        # Handle stream_event (primary output format from codebuddy CLI)
        if event_type == "stream_event":
            return self._handle_stream_event(event)

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
                self._has_streamed_text_content = True

            # Close text message before tool calls if no tool_use items follow.
            # If tool_use items follow, keep message open so tool calls can
            # reference the current parentMessageId; the result event or
            # create_end_event() will close it later.
            if (
                not tool_use_items
                and not tool_result_items
                and self.state.message_started
                and self.state.current_message_id
            ):
                results.append(
                    TextMessageEndEvent(
                        messageId=self.state.current_message_id
                    ).to_sse()
                )
                self.state.message_started = False

            # Process tool_use items - these are part of the same message
            for item in tool_use_items:
                tool_id = item.get("id") or item.get("tool_use_id")
                tool_name = item.get("name") or "unknown"
                parameters = item.get("input")
                if tool_id:
                    # Ensure we have a message context for the tool call
                    if not self.state.current_message_id:
                        self.state.current_message_id = self._generate_message_id()
                    
                    if tool_id not in self.state.active_tool_calls:
                        self.state.active_tool_calls[tool_id] = tool_name
                        results.append(
                            ToolCallStartEvent(
                                toolCallId=tool_id,
                                toolCallName=build_tool_call_name(tool_name, parameters),
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
            self._has_streamed_text_content = True
            # Close the message — "message" events deliver complete content
            results.append(
                TextMessageEndEvent(
                    messageId=self.state.current_message_id
                ).to_sse()
            )
            self.state.message_started = False
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
                            toolCallName=build_tool_call_name(tool_name, parameters),
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
            self._has_streamed_text_content = True
            results.append(TextMessageEndEvent(messageId=self.state.current_message_id).to_sse())
            self.state.message_started = False
            return "".join(results)

        # Handle result event (success/error) - this marks the end of a turn
        if event_type == "result":
            subtype = event.get("subtype")
            result_text = event.get("content") or event.get("result") or ""
            results = []

            # Compatibility: when provider only returns final text in result/success,
            # convert it into visible text content before run finishes.
            if (
                subtype == "success"
                and result_text
                and not self._has_streamed_text_content
            ):
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
                        delta=str(result_text),
                    ).to_sse()
                )
                self._has_streamed_text_content = True

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
            from src.runtime.utils.ids import gen_session_id, gen_run_id
            thread_id = gen_session_id()
            run_id = gen_run_id()
        else:
            thread_id = self.state.thread_id
            run_id = self.state.run_id
        return RunErrorEvent(threadId=thread_id, runId=run_id, message=error_msg).to_sse()

    # ============ stream_event handlers ============

    def _handle_stream_event(self, event: Dict[str, Any]) -> Optional[str]:
        """Handle stream_event events from codebuddy CLI"""
        inner_event = event.get("event", {})
        if not isinstance(inner_event, dict):
            return None

        inner_type = inner_event.get("type")

        if inner_type == "content_block_start":
            return self._handle_content_block_start(inner_event)
        elif inner_type == "content_block_delta":
            return self._handle_content_block_delta(inner_event)
        elif inner_type == "content_block_stop":
            return self._handle_content_block_stop(inner_event)

        return None

    def _handle_content_block_start(self, event: Dict[str, Any]) -> Optional[str]:
        """Handle content_block_start event"""
        content_block = event.get("content_block", {})
        if not isinstance(content_block, dict):
            return None

        block_type = content_block.get("type")
        index = event.get("index", 0)

        if block_type == "tool_use":
            # Tool call start
            tool_name = content_block.get("name", "unknown")
            tool_id = content_block.get("id", str(uuid.uuid4()))

            # Store in buffer
            self.state.tool_input_buffer[index] = (tool_name, tool_id, "")
            self.state.active_tool_calls[tool_id] = tool_name

            # Delay sending ToolCallStart until we have args
            return None

        elif block_type == "text":
            # Text block start - send TextMessageStart if not started
            if not self.state.message_started:
                self.state.current_message_id = self._generate_message_id()
                self.state.message_started = True

                msg_start = TextMessageStartEvent(
                    messageId=self.state.current_message_id,
                    role=MessageRole.ASSISTANT
                )
                return msg_start.to_sse()

        return None

    def _handle_content_block_delta(self, event: Dict[str, Any]) -> Optional[str]:
        """Handle content_block_delta event"""
        delta = event.get("delta", {})
        if not isinstance(delta, dict):
            return None

        delta_type = delta.get("type")
        index = event.get("index", 0)

        if delta_type == "text_delta":
            # Text delta
            text = delta.get("text", "")
            # Sanitize thinking tags
            text = self._sanitize_text(text)
            
            # Skip empty text
            if not text or not text.strip():
                return None

            # Ensure message started
            if not self.state.message_started:
                self.state.current_message_id = self._generate_message_id()
                self.state.message_started = True

                results = []
                msg_start = TextMessageStartEvent(
                    messageId=self.state.current_message_id,
                    role=MessageRole.ASSISTANT
                )
                results.append(msg_start.to_sse())

                content_event = TextMessageContentEvent(
                    messageId=self.state.current_message_id,
                    delta=text,
                )
                results.append(content_event.to_sse())
                self._has_streamed_text_content = True
                return "".join(results)

            content_event = TextMessageContentEvent(
                messageId=self.state.current_message_id,
                delta=text,
            )
            return content_event.to_sse()

        elif delta_type == "input_json_delta":
            # Tool args delta
            partial_json = delta.get("partial_json", "")
            if not partial_json:
                return None

            # Find the tool_id for this index
            if index in self.state.tool_input_buffer:
                tool_name, tool_id, existing = self.state.tool_input_buffer[index]
                new_params = existing + partial_json
                self.state.tool_input_buffer[index] = (tool_name, tool_id, new_params)

                results = []

                # Send ToolCallStart first if not sent
                if tool_id not in self._tool_start_sent:
                    tool_label = build_tool_call_name(tool_name, new_params)
                    tool_key = (tool_name or "").strip().lower()
                    should_send = tool_key not in ("skill", "use_skill", "task")
                    if tool_label != tool_name:
                        should_send = True

                    if should_send:
                        self._tool_start_sent.add(tool_id)
                        self.state.active_tool_calls[tool_id] = tool_name
                        results.append(
                            ToolCallStartEvent(
                                toolCallId=tool_id,
                                toolCallName=tool_label,
                                parentMessageId=self.state.current_message_id,
                            ).to_sse()
                        )
                        results.append(
                            ToolCallArgsEvent(
                                toolCallId=tool_id,
                                delta=new_params,
                            ).to_sse()
                        )
                    return "".join(results) if results else None

                # Send args delta
                results.append(
                    ToolCallArgsEvent(
                        toolCallId=tool_id,
                        delta=partial_json,
                    ).to_sse()
                )

                return "".join(results) if results else None

        return None

    def _handle_content_block_stop(self, event: Dict[str, Any]) -> Optional[str]:
        """Handle content_block_stop event"""
        index = event.get("index", 0)

        # Check if this was a tool_use block
        if index in self.state.tool_input_buffer:
            tool_name, tool_id, params = self.state.tool_input_buffer.pop(index, (None, None, None))
            if tool_id and tool_id not in self._tool_start_sent:
                self._tool_start_sent.add(tool_id)
                results = [
                    ToolCallStartEvent(
                        toolCallId=tool_id,
                        toolCallName=build_tool_call_name(tool_name, params),
                        parentMessageId=self.state.current_message_id,
                    ).to_sse()
                ]
                if params:
                    results.append(
                        ToolCallArgsEvent(
                            toolCallId=tool_id,
                            delta=params,
                        ).to_sse()
                    )
                return "".join(results)

        return None

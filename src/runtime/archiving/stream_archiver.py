# -*- coding: utf-8 -*-
"""Stream Archiver Service

Archives AGUI stream events to Redis for later viewing in the Web UI.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from ..models.session import (
    SessionMeta,
    SessionStatus,
    StoredMessage,
    MessageStatus,
    StoredToolCall,
    ToolCallStatus,
    ContentSegment,
)
from ..stores.session_storage import SessionStorage, get_session_storage

logger = logging.getLogger(__name__)


class StreamArchiver:
    """Archives AGUI stream events to Redis
    
    This class is designed to be used within the AGUI stream handler.
    It processes events asynchronously to avoid blocking the SSE stream.
    """

    def __init__(
        self,
        session_id: str,
        thread_id: str,
        run_id: Optional[str],
        username: str,
        agent_name: Optional[str] = None,
        provider: Optional[str] = None,
        storage: Optional[SessionStorage] = None,
    ):
        """Initialize stream archiver
        
        Args:
            session_id: Session ID (typically same as thread_id)
            thread_id: AG-UI thread ID
            run_id: AG-UI run ID
            username: Username
            agent_name: Optional agent name
            provider: Optional provider (e.g., claude, gemini)
            storage: Optional SessionStorage instance
        """
        self.session_id = session_id
        self.thread_id = thread_id
        self.run_id = run_id
        self.username = username
        self.agent_name = agent_name
        self.provider = provider
        self._storage = storage or get_session_storage()
        
        # State tracking
        self._current_message_id: Optional[str] = None
        self._current_message_content: str = ""
        self._current_tool_call_id: Optional[str] = None
        self._current_tool_args: str = ""
        self._pending_tool_calls: List[str] = []
        self._first_user_message: Optional[str] = None
        self._initialized = False
        
        # Content segments tracking for ordering text and tool calls
        self._content_segments: List[ContentSegment] = []
        self._segment_sequence: int = 0
        self._last_text_content: str = ""  # Track text content before tool call

    async def on_run_started(self, initial_messages: Optional[List[Dict[str, Any]]] = None):
        """Called when a run starts
        
        Creates or updates session metadata and stores initial messages.
        
        Args:
            initial_messages: Optional list of initial messages from the request
        """
        try:
            # Check if session already exists
            existing = self._storage.get_session_meta(self.session_id)
            
            if existing:
                # Update existing session
                self._storage.update_session_status(self.session_id, SessionStatus.RUNNING)
                if self.provider and not existing.provider:
                    existing.provider = self.provider
                    existing.updated_at = int(time.time() * 1000)
                    self._storage.save_session_meta(existing)
                self._initialized = True
            else:
                # Create new session
                title = "New Session"
                
                # Extract title from first user message
                if initial_messages:
                    for msg in initial_messages:
                        if msg.get("role") == "user":
                            content = msg.get("content", "")
                            if content:
                                # Use first 50 chars as title
                                title = content[:50] + ("..." if len(content) > 50 else "")
                                self._first_user_message = content
                                break
                
                meta = SessionMeta(
                    id=self.session_id,
                    thread_id=self.thread_id,
                    run_id=self.run_id,
                    title=title,
                    username=self.username,
                    agent_name=self.agent_name,
                    provider=self.provider,
                    status=SessionStatus.RUNNING,
                )
                self._storage.save_session_meta(meta)
                self._initialized = True

            # Store initial messages (for new sessions and follow-ups)
            if initial_messages:
                existing_ids = set()
                try:
                    existing_ids = {m.id for m in self._storage.get_session_messages(self.session_id)}
                except Exception:
                    existing_ids = set()

                for msg in initial_messages:
                    msg_id = msg.get("id") or f"init-{int(time.time() * 1000)}"
                    if msg_id in existing_ids:
                        continue

                    role = msg.get("role", "user")
                    if role not in ("user", "assistant", "system"):
                        role = "user"

                    stored_msg = StoredMessage(
                        id=msg_id,
                        role=role,
                        content=msg.get("content", ""),
                        status=MessageStatus.COMPLETE,
                    )
                    self._storage.add_session_message(self.session_id, stored_msg)
            
            logger.debug(f"Run started for session: {self.session_id}")
            
        except Exception as e:
            logger.error(f"Failed to handle run started: {e}")

    async def on_run_finished(self):
        """Called when a run finishes successfully"""
        try:
            # Finalize any pending message
            await self._finalize_current_message()
            
            # Update session status
            self._storage.update_session_status(self.session_id, SessionStatus.COMPLETED)
            
            logger.debug(f"Run finished for session: {self.session_id}")
            
        except Exception as e:
            logger.error(f"Failed to handle run finished: {e}")

    async def on_run_error(self, error: str):
        """Called when a run encounters an error
        
        Args:
            error: Error message
        """
        try:
            # Finalize any pending message with error status
            if self._current_message_id:
                msg = StoredMessage(
                    id=self._current_message_id,
                    role="assistant",
                    content=self._current_message_content,
                    status=MessageStatus.ERROR,
                    tool_call_ids=self._pending_tool_calls if self._pending_tool_calls else None,
                )
                self._storage.update_message(self.session_id, msg)
            
            # Update session status
            self._storage.update_session_status(self.session_id, SessionStatus.ERROR)
            
            logger.debug(f"Run error for session: {self.session_id}: {error}")
            
        except Exception as e:
            logger.error(f"Failed to handle run error: {e}")

    async def archive_event(self, event_data: Dict[str, Any]):
        """Archive a single event (non-blocking)
        
        This method dispatches to specific handlers based on event type.
        
        Args:
            event_data: Raw event data from CCR
        """
        try:
            event_type = event_data.get("type", "")
            
            # Log all events for debugging
            if event_type in ("TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"):
                logger.info(f"[Archiver] archive_event: type={event_type}, messageId={event_data.get('messageId')}, session={self.session_id}")

            # ================= AG-UI events =================
            # We archive based on the already-converted AG-UI event stream to ensure
            # what the client sees is what we persist.
            if event_type == "TEXT_MESSAGE_START":
                message_id = event_data.get("messageId") or f"msg-{int(time.time() * 1000)}"
                self._current_message_id = message_id
                self._current_message_content = ""

                msg = StoredMessage(
                    id=message_id,
                    role="assistant",
                    content="",
                    status=MessageStatus.STREAMING,
                )
                self._storage.add_session_message(self.session_id, msg)
                return

            if event_type == "TEXT_MESSAGE_CONTENT":
                # Delta text
                msg_id = event_data.get("messageId")
                if msg_id and msg_id != self._current_message_id:
                    # Switch message context
                    await self._finalize_current_message()
                    self._current_message_id = msg_id
                    self._current_message_content = ""
                    msg = StoredMessage(
                        id=msg_id,
                        role="assistant",
                        content="",
                        status=MessageStatus.STREAMING,
                    )
                    self._storage.add_session_message(self.session_id, msg)

                delta = event_data.get("delta", "")
                if delta:
                    await self._handle_text_event({"content": delta})
                return

            if event_type == "TEXT_MESSAGE_END":
                await self._finalize_current_message()
                return

            if event_type == "TOOL_CALL_START":
                tool_id = event_data.get("toolCallId") or f"tool-{int(time.time() * 1000)}"
                tool_name = event_data.get("toolCallName", "unknown")
                parent_id = event_data.get("parentMessageId") or self._current_message_id

                # Save current text content as a segment before tool call
                if self._current_message_content and self._current_message_content != self._last_text_content:
                    # Only add text that hasn't been saved yet
                    new_text = self._current_message_content[len(self._last_text_content):]
                    if new_text.strip():
                        self._content_segments.append(ContentSegment(
                            type="text",
                            content=new_text,
                            sequence=self._segment_sequence
                        ))
                        self._segment_sequence += 1
                    self._last_text_content = self._current_message_content

                # Add tool call segment
                self._content_segments.append(ContentSegment(
                    type="tool_call",
                    tool_call_id=tool_id,
                    sequence=self._segment_sequence
                ))
                self._segment_sequence += 1

                tool_call = StoredToolCall(
                    id=tool_id,
                    tool_name=tool_name,
                    args={},
                    args_string="",
                    status=ToolCallStatus.EXECUTING,
                    parent_message_id=parent_id,
                )
                self._storage.save_tool_call(self.session_id, tool_call)
                self._pending_tool_calls.append(tool_id)
                self._current_tool_call_id = tool_id
                return

            if event_type == "TOOL_CALL_ARGS":
                tool_id = event_data.get("toolCallId", self._current_tool_call_id)
                if not tool_id:
                    return
                delta = event_data.get("delta", "")
                if not delta:
                    return

                tool_call = self._storage.get_tool_call(self.session_id, tool_id)
                if tool_call:
                    tool_call.args_string = (tool_call.args_string or "") + delta
                    self._storage.update_tool_call(self.session_id, tool_call)
                return

            if event_type in ("TOOL_CALL_END", "TOOL_CALL_RESULT"):
                tool_id = event_data.get("toolCallId", self._current_tool_call_id)
                if not tool_id:
                    return

                tool_call = self._storage.get_tool_call(self.session_id, tool_id)
                if tool_call:
                    tool_call.status = ToolCallStatus.COMPLETED
                    tool_call.end_time = int(time.time() * 1000)
                    if event_type == "TOOL_CALL_END":
                        tool_call.result = event_data.get("result")
                    else:
                        tool_call.result = event_data.get("content")
                    self._storage.update_tool_call(self.session_id, tool_call)

                self._current_tool_call_id = None
                return

            # ================= Legacy/Raw events =================
            # Text message events
            if event_type == "text":
                await self._handle_text_event(event_data)
            
            # Tool call events (from Claude Code)
            elif event_type == "tool_use":
                await self._handle_tool_use_event(event_data)
            elif event_type == "tool_result":
                await self._handle_tool_result_event(event_data)
            
            # System events
            elif event_type == "system":
                await self._handle_system_event(event_data)
            
            # Result events
            elif event_type == "result":
                await self._handle_result_event(event_data)
                
        except Exception as e:
            logger.warning(f"Failed to archive event: {e}")

    async def _handle_text_event(self, event_data: Dict[str, Any]):
        """Handle text content event"""
        content = event_data.get("content", "")
        if not content:
            return
        
        # If no current message, create one
        if not self._current_message_id:
            self._current_message_id = f"msg-{int(time.time() * 1000)}"
            self._current_message_content = ""
            
            # Create initial message
            msg = StoredMessage(
                id=self._current_message_id,
                role="assistant",
                content="",
                status=MessageStatus.STREAMING,
            )
            self._storage.add_session_message(self.session_id, msg)
        
        # Append content
        self._current_message_content += content
        
        # Save streaming content (for recovery)
        self._storage.save_streaming_content(
            self.session_id,
            self._current_message_id,
            self._current_message_content
        )

    async def _handle_tool_use_event(self, event_data: Dict[str, Any]):
        """Handle tool use start event"""
        tool_id = event_data.get("id", f"tool-{int(time.time() * 1000)}")
        tool_name = event_data.get("name", "unknown")
        args = event_data.get("input", {})
        
        # Save current text content as a segment before tool call
        if self._current_message_content and self._current_message_content != self._last_text_content:
            new_text = self._current_message_content[len(self._last_text_content):]
            if new_text.strip():
                self._content_segments.append(ContentSegment(
                    type="text",
                    content=new_text,
                    sequence=self._segment_sequence
                ))
                self._segment_sequence += 1
            self._last_text_content = self._current_message_content
        
        # Add tool call segment
        self._content_segments.append(ContentSegment(
            type="tool_call",
            tool_call_id=tool_id,
            sequence=self._segment_sequence
        ))
        self._segment_sequence += 1
        
        # Create tool call record
        tool_call = StoredToolCall(
            id=tool_id,
            tool_name=tool_name,
            args=args if isinstance(args, dict) else {},
            args_string=json.dumps(args, ensure_ascii=False) if args else "",
            status=ToolCallStatus.EXECUTING,
            parent_message_id=self._current_message_id,
        )
        self._storage.save_tool_call(self.session_id, tool_call)
        
        # Track for current message
        self._pending_tool_calls.append(tool_id)
        self._current_tool_call_id = tool_id

    async def _handle_tool_result_event(self, event_data: Dict[str, Any]):
        """Handle tool result event"""
        tool_id = event_data.get("tool_use_id", self._current_tool_call_id)
        if not tool_id:
            return
        
        # Get existing tool call
        tool_call = self._storage.get_tool_call(self.session_id, tool_id)
        if tool_call:
            # Update with result
            tool_call.status = ToolCallStatus.COMPLETED
            tool_call.result = event_data.get("content", "")
            tool_call.end_time = int(time.time() * 1000)
            
            # Check for error
            if event_data.get("is_error"):
                tool_call.status = ToolCallStatus.FAILED
                tool_call.error = str(event_data.get("content", ""))
            
            self._storage.update_tool_call(self.session_id, tool_call)
        
        self._current_tool_call_id = None

    async def _handle_system_event(self, event_data: Dict[str, Any]):
        """Handle system event"""
        # System events can be logged but typically not stored
        subtype = event_data.get("subtype", "")
        logger.debug(f"System event: {subtype}")

    async def _handle_result_event(self, event_data: Dict[str, Any]):
        """Handle result event (end of response)"""
        # Finalize current message
        await self._finalize_current_message()

    async def _finalize_current_message(self):
        """Finalize the current message being streamed"""
        if not self._current_message_id:
            logger.debug(f"[Archiver] _finalize_current_message called but no current_message_id")
            return
        
        try:
            # Get final content
            content = self._current_message_content
            logger.info(f"[Archiver] Finalizing message: id={self._current_message_id}, content_len={len(content)}, session={self.session_id}")
            if not content:
                # Try to recover from streaming content
                content = self._storage.get_streaming_content(
                    self.session_id, self._current_message_id
                ) or ""
                logger.info(f"[Archiver] Recovered streaming content: len={len(content)}")
            
            # Add remaining text content as final segment if any
            if content and content != self._last_text_content:
                remaining_text = content[len(self._last_text_content):]
                if remaining_text.strip():
                    self._content_segments.append(ContentSegment(
                        type="text",
                        content=remaining_text,
                        sequence=self._segment_sequence
                    ))
                    self._segment_sequence += 1
            
            # If no segments but have content, create a single text segment
            if not self._content_segments and content:
                self._content_segments.append(ContentSegment(
                    type="text",
                    content=content,
                    sequence=0
                ))
            
            # Update message
            msg = StoredMessage(
                id=self._current_message_id,
                role="assistant",
                content=content,
                status=MessageStatus.COMPLETE,
                tool_call_ids=self._pending_tool_calls if self._pending_tool_calls else None,
                content_segments=self._content_segments if self._content_segments else None,
            )
            self._storage.update_message(self.session_id, msg)
            
            # Clean up streaming content
            self._storage.delete_streaming_content(self.session_id, self._current_message_id)
            
        except Exception as e:
            logger.error(f"Failed to finalize message: {e}")
        finally:
            # Reset state
            self._current_message_id = None
            self._current_message_content = ""
            self._pending_tool_calls = []
            self._content_segments = []
            self._segment_sequence = 0
            self._last_text_content = ""


def create_archiver(
    thread_id: str,
    run_id: Optional[str],
    username: str,
    agent_name: Optional[str] = None,
    provider: Optional[str] = None,
) -> StreamArchiver:
    """Factory function to create a StreamArchiver
    
    Args:
        thread_id: AG-UI thread ID (used as session ID)
        run_id: AG-UI run ID
        username: Username
        agent_name: Optional agent name
        
    Returns:
        StreamArchiver instance
    """
    return StreamArchiver(
        session_id=thread_id,  # Use thread_id as session_id
        thread_id=thread_id,
        run_id=run_id,
        username=username,
        agent_name=agent_name,
        provider=provider,
    )

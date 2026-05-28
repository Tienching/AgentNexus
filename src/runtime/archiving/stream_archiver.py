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
        exec_user: Optional[str] = None,
        provider: Optional[str] = None,
        alias: Optional[str] = None,
        storage: Optional[SessionStorage] = None,
    ):
        """Initialize stream archiver
        
        Args:
            session_id: Session ID (typically same as thread_id)
            thread_id: AG-UI thread ID
            run_id: AG-UI run ID
            username: Username
            exec_user: Optional exec_user name
            provider: Optional provider (e.g., claude, gemini)
            storage: Optional SessionStorage instance
        """
        self.session_id = session_id
        self.thread_id = thread_id
        self.run_id = run_id
        self.username = username
        self.exec_user = exec_user
        self.provider = provider
        self.alias = alias
        self._storage = storage or get_session_storage()
        
        # State tracking
        self._current_message_id: Optional[str] = None
        self._current_message_content: str = ""
        self._current_tool_call_id: Optional[str] = None
        self._current_tool_args: str = ""
        self._pending_tool_calls: List[str] = []
        self._first_user_message: Optional[str] = None
        self._initialized = False
        self._last_assistant_message_id: Optional[str] = None
        self._saw_run_error = False
        
        # Content segments tracking for ordering text and tool calls
        self._content_segments: List[ContentSegment] = []
        self._segment_sequence: int = 0
        self._last_text_content: str = ""  # Track text content before tool call

    def _format_initial_message_content(self, content: Any) -> str:
        """Render AG-UI text/multimodal message content into storable text."""
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return "" if content is None else str(content)

        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                if item:
                    parts.append(item)
                continue
            if not isinstance(item, dict):
                continue

            item_type = str(item.get("type") or "").strip().lower()
            if item_type in ("text", "input_text"):
                text = item.get("text", item.get("content", ""))
                if text:
                    parts.append(str(text))
                continue

            url = item.get("url")
            if not url and isinstance(item.get("image_url"), dict):
                url = item["image_url"].get("url")
            if not url:
                url = item.get("path")

            mime_type = str(item.get("mimeType") or item.get("mime_type") or "").lower()
            if item_type in ("binary", "image", "image_url", "input_image") and url:
                label = "image" if item_type != "binary" or mime_type.startswith("image/") else "file"
                parts.append(f"{{{label}: {url}}}")
                continue

            if item_type == "file" and url:
                parts.append(f"{{file: {url}}}")

        return "\n".join(parts)

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
                meta_changed = False
                if self.username and existing.username != self.username:
                    existing.username = self.username
                    meta_changed = True
                if self.exec_user and existing.exec_user != self.exec_user:
                    existing.exec_user = self.exec_user
                    meta_changed = True
                if self.provider and existing.provider != self.provider:
                    existing.provider = self.provider
                    meta_changed = True
                if self.alias and getattr(existing, "alias", None) != self.alias:
                    existing.alias = self.alias
                    meta_changed = True
                if meta_changed:
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
                            content = self._format_initial_message_content(msg.get("content", ""))
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
                    exec_user=self.exec_user,
                    provider=self.provider,
                    alias=self.alias,
                    status=SessionStatus.RUNNING,
                )
                self._storage.save_session_meta(meta)
                self._initialized = True

            # IMPORTANT: Write RUN_STARTED event IMMEDIATELY after setting
            # status to RUNNING, BEFORE storing initial messages. This prevents
            # the self-heal logic from seeing a stale RUN_FINISHED (from the
            # previous run) without a corresponding RUN_STARTED and incorrectly
            # resetting the status back to completed.
            try:
                self._storage.append_agui_event(self.session_id, {
                    "type": "RUN_STARTED",
                    "threadId": self.thread_id,
                    "runId": self.run_id,
                })
            except Exception:
                pass

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
                        content=self._format_initial_message_content(msg.get("content", "")),
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

            # If a RUN_ERROR was already observed in this run, do not overwrite
            # the terminal state with completed. The CodeBuddy CLI executor emits
            # timeout/model errors as stream events and then the outer stream still
            # reaches its normal finally path; without this guard the UI sees
            # RUN_ERROR immediately followed by RUN_FINISHED and reloads a
            # misleading "completed" snapshot.
            if self._saw_run_error:
                self._storage.update_session_status(self.session_id, SessionStatus.ERROR)
                logger.debug(f"Run finished skipped after prior error for session: {self.session_id}")
                return
            
            # Update session status
            self._storage.update_session_status(self.session_id, SessionStatus.COMPLETED)
            
            # Write terminal event to event log so SSE stream knows to close
            try:
                self._storage.append_agui_event(self.session_id, {"type": "RUN_FINISHED"})
            except Exception:
                pass
            
            logger.debug(f"Run finished for session: {self.session_id}")
            
        except Exception as e:
            logger.error(f"Failed to handle run finished: {e}")

    async def on_run_error(self, error: str):
        """Called when a run encounters an error
        
        Args:
            error: Error message
        """
        try:
            self._saw_run_error = True

            # Finalize any pending message with error status
            if self._current_message_id:
                msg = StoredMessage(
                    id=self._current_message_id,
                    role="assistant",
                    content=self._current_message_content,
                    status=MessageStatus.ERROR,
                    tool_call_ids=self._pending_tool_calls if self._pending_tool_calls else None,
                    content_segments=self._content_segments if self._content_segments else None,
                )
                self._storage.update_message(self.session_id, msg)
                self._last_assistant_message_id = self._current_message_id
            
            # Update session status
            self._storage.update_session_status(self.session_id, SessionStatus.ERROR)
            
            # Write terminal event to event log so SSE stream knows to close
            try:
                self._storage.append_agui_event(self.session_id, {"type": "RUN_ERROR", "message": error})
            except Exception:
                pass
            
            logger.debug(f"Run error for session: {self.session_id}: {error}")
            
        except Exception as e:
            logger.error(f"Failed to handle run error: {e}")

    async def archive_event(self, event_data: Dict[str, Any]):
        """Archive a single event (non-blocking)
        
        This method dispatches to specific handlers based on event type.
        Also appends the event to the session event log for live streaming.
        
        Args:
            event_data: Raw event data from CLI
        """
        try:
            event_type = event_data.get("type", "")
            
            # Append to event log for live streaming (channel sessions, etc.)
            if event_type in (
                "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
                "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT",
                "RUN_STARTED", "RUN_FINISHED", "RUN_ERROR", "STATE_SNAPSHOT",
            ):
                try:
                    self._storage.append_agui_event(self.session_id, event_data)
                except Exception:
                    pass
            
            # Log all events for debugging
            if event_type in ("TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"):
                logger.info(f"[Archiver] archive_event: type={event_type}, messageId={event_data.get('messageId')}, session={self.session_id}")

            # ================= AG-UI events =================
            # We archive based on the already-converted AG-UI event stream to ensure
            # what the client sees is what we persist.
            if event_type == "RUN_ERROR":
                self._saw_run_error = True

            if event_type == "TEXT_MESSAGE_START":
                message_id = event_data.get("messageId") or f"msg-{int(time.time() * 1000)}"
                self._current_message_id = message_id
                self._current_message_content = ""
                self._current_tool_call_id = None
                self._pending_tool_calls = []
                self._content_segments = []
                self._segment_sequence = 0
                self._last_text_content = ""

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
                    self._current_tool_call_id = None
                    self._pending_tool_calls = []
                    self._content_segments = []
                    self._segment_sequence = 0
                    self._last_text_content = ""
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
                    self._append_text_segment(delta)
                    self._update_current_message()
                return

            if event_type == "TEXT_MESSAGE_END":
                await self._finalize_current_message()
                return

            if event_type == "TOOL_CALL_START":
                tool_id = event_data.get("toolCallId") or f"tool-{int(time.time() * 1000)}"
                tool_name = event_data.get("toolCallName", "unknown")
                parent_id = event_data.get("parentMessageId") or self._current_message_id or self._last_assistant_message_id

                if self._current_message_id:
                    # Add tool call segment to the active message.
                    self._content_segments.append(ContentSegment(
                        type="tool_call",
                        tool_call_id=tool_id,
                        sequence=self._segment_sequence
                    ))
                    self._segment_sequence += 1
                else:
                    # The assistant text segment may already have ended. Link
                    # this late tool call to the last finalized assistant
                    # message so a later snapshot preserves what the live UI
                    # showed instead of falling back to only the first text.
                    self._append_tool_segment_to_message(parent_id, tool_id)

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
                if self._current_message_id:
                    self._update_current_message()
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
                        # Only update result if provided in END event
                        # This prevents overwriting the result from a preceding TOOL_CALL_RESULT event
                        res = event_data.get("result")
                        if res is not None:
                            tool_call.result = res
                    else:
                        # TOOL_CALL_RESULT always provides content
                        tool_call.result = event_data.get("content")

                    # Try to parse args_string to args if args is empty
                    if not tool_call.args and tool_call.args_string:
                        try:
                            tool_call.args = json.loads(tool_call.args_string)
                        except Exception:
                            pass

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

    def _append_text_segment(self, content: str) -> None:
        if not content:
            return

        if self._content_segments and self._content_segments[-1].type == "text":
            previous = self._content_segments[-1].content or ""
            self._content_segments[-1].content = f"{previous}{content}"
        else:
            self._content_segments.append(ContentSegment(
                type="text",
                content=content,
                sequence=self._segment_sequence,
            ))
            self._segment_sequence += 1

        self._last_text_content = self._current_message_content

    def _update_current_message(self) -> None:
        if not self._current_message_id:
            return
        msg = StoredMessage(
            id=self._current_message_id,
            role="assistant",
            content=self._current_message_content,
            status=MessageStatus.STREAMING,
            tool_call_ids=self._pending_tool_calls if self._pending_tool_calls else None,
            content_segments=self._content_segments if self._content_segments else None,
        )
        updated = self._storage.update_message(self.session_id, msg)
        if not updated:
            self._storage.add_session_message(self.session_id, msg)

    def _append_tool_segment_to_message(self, message_id: Optional[str], tool_id: str) -> None:
        """Attach a tool call to an already-finalized assistant message.

        Some AG-UI streams close the assistant text message before subsequent
        tool calls arrive. The live UI still shows those tools in the same
        streaming bubble, but the persisted snapshot used after reload only
        knows about StoredMessage.content/tool_call_ids. Link late tool calls
        back to the most recent assistant message so refresh/timeout snapshots
        don't appear to roll back to the first visible text chunk.
        """
        if not message_id or not tool_id:
            return
        msg = self._storage.get_message_by_id(self.session_id, message_id)
        if not msg or msg.role != "assistant":
            return

        tool_call_ids = list(msg.tool_call_ids or [])
        if tool_id not in tool_call_ids:
            tool_call_ids.append(tool_id)

        segments = list(msg.content_segments or [])
        if not any(seg.type == "tool_call" and seg.tool_call_id == tool_id for seg in segments):
            next_sequence = (max((seg.sequence for seg in segments), default=-1) + 1)
            segments.append(ContentSegment(
                type="tool_call",
                tool_call_id=tool_id,
                sequence=next_sequence,
            ))

        updated = msg.model_copy(update={
            "tool_call_ids": tool_call_ids,
            "content_segments": segments,
        })
        self._storage.update_message(self.session_id, updated)

    async def _handle_tool_use_event(self, event_data: Dict[str, Any]):
        """Handle tool use start event"""
        tool_id = event_data.get("id", f"tool-{int(time.time() * 1000)}")
        tool_name = event_data.get("name", "unknown")
        args = event_data.get("input", {})
        
        # Save current text content as a segment before tool call
        if self._current_message_content and self._current_message_content != self._last_text_content:
            new_text = self._current_message_content[len(self._last_text_content):]
            if new_text.strip():
                self._append_text_segment(new_text)
            self._last_text_content = self._current_message_content
        
        parent_id = self._current_message_id or self._last_assistant_message_id
        if self._current_message_id:
            # Add tool call segment to the active message.
            self._content_segments.append(ContentSegment(
                type="tool_call",
                tool_call_id=tool_id,
                sequence=self._segment_sequence
            ))
            self._segment_sequence += 1
        else:
            self._append_tool_segment_to_message(parent_id, tool_id)
        
        # Create tool call record
        tool_call = StoredToolCall(
            id=tool_id,
            tool_name=tool_name,
            args=args if isinstance(args, dict) else {},
            args_string=json.dumps(args, ensure_ascii=False) if args else "",
            status=ToolCallStatus.EXECUTING,
            parent_message_id=parent_id,
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
                    self._append_text_segment(remaining_text)
            
            # If no segments but have content, create a single text segment
            if not self._content_segments and content:
                self._append_text_segment(content)
            
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
            self._last_assistant_message_id = self._current_message_id
            
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
    exec_user: Optional[str] = None,
    provider: Optional[str] = None,
    alias: Optional[str] = None,
) -> StreamArchiver:
    """Factory function to create a StreamArchiver

    Args:
        thread_id: AG-UI thread ID (used as session ID)
        run_id: AG-UI run ID
        username: Username
        exec_user: Optional exec_user name

    Returns:
        StreamArchiver instance
    """
    # Check if there's a target_session_id override (for /workspace -t mode)
    # If set, archive messages to the target session instead of the current session
    archive_session_id = thread_id
    try:
        from ..stores.session_storage import get_session_storage
        storage = get_session_storage()
        target_session_id = storage.get_target_session_id(thread_id)
        if target_session_id:
            archive_session_id = target_session_id
            logger.info(f"Using target_session_id for archiving: {thread_id} -> {target_session_id}")
    except Exception as e:
        logger.warning(f"Failed to check target_session_id: {e}")

    return StreamArchiver(
        session_id=archive_session_id,  # Use target_session_id if set, otherwise thread_id
        thread_id=thread_id,
        run_id=run_id,
        username=username,
        exec_user=exec_user,
        provider=provider,
        alias=alias,
    )

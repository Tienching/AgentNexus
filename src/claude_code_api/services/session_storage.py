# -*- coding: utf-8 -*-
"""Session Storage Service

Provides CRUD operations for AGUI session data in Redis.
"""

import json
import logging
import time
from typing import List, Optional, Tuple

from ..models.session import (
    SessionMeta,
    SessionStatus,
    StoredMessage,
    StoredToolCall,
)
from .redis_client import get_redis_client, RedisClient

logger = logging.getLogger(__name__)

# TTL constants (in seconds)
SESSION_TTL = 7 * 24 * 60 * 60  # 7 days
STREAMING_CONTENT_TTL = 60 * 60  # 1 hour for temporary streaming content


class SessionStorage:
    """Session storage service using Redis"""

    def __init__(self, redis_client: Optional[RedisClient] = None):
        """Initialize session storage
        
        Args:
            redis_client: Optional Redis client instance. If not provided, uses global instance.
        """
        self._redis = redis_client or get_redis_client()

    # ============ Session Metadata Operations ============

    def save_session_meta(self, meta: SessionMeta) -> bool:
        """Save session metadata to Redis
        
        Args:
            meta: Session metadata to save
            
        Returns:
            True if successful
        """
        try:
            key = f"session:{meta.id}:meta"
            self._redis.hset(key, meta.to_redis_hash())
            
            # Set TTL
            self._redis.client.expire(self._redis._key(key), SESSION_TTL)
            
            # Add to global session index (sorted set with updated_at as score)
            global_key = "sessions:all"
            self._redis.zadd(global_key, {meta.id: meta.updated_at})
            
            # Also add to user's session index if username provided
            if meta.username:
                user_key = f"user:{meta.username}:sessions"
                self._redis.zadd(user_key, {meta.id: meta.updated_at})
            
            logger.debug(f"Saved session meta: {meta.id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save session meta: {e}")
            return False

    def get_session_meta(self, session_id: str) -> Optional[SessionMeta]:
        """Get session metadata from Redis
        
        Args:
            session_id: Session ID
            
        Returns:
            SessionMeta if found, None otherwise
        """
        try:
            key = f"session:{session_id}:meta"
            data = self._redis.hgetall(key)
            if not data:
                return None
            return SessionMeta.from_redis_hash(data)
        except Exception as e:
            logger.error(f"Failed to get session meta: {e}")
            return None

    def get_user_sessions(
        self,
        username: str,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        status_filter: Optional[SessionStatus] = None,
    ) -> Tuple[List[SessionMeta], int]:
        """Get user's sessions with pagination and filtering
        
        Args:
            username: Username
            page: Page number (1-indexed)
            page_size: Number of sessions per page
            search: Optional search term for title
            status_filter: Optional status filter
            
        Returns:
            Tuple of (session list, total count)
        """
        try:
            user_key = f"user:{username}:sessions"
            
            # Get all session IDs sorted by updated_at (descending)
            # Use zrevrange for descending order
            all_session_ids = self._redis.client.zrevrange(
                self._redis._key(user_key), 0, -1
            )
            
            if not all_session_ids:
                return [], 0
            
            # Fetch all session metadata for filtering
            sessions = []
            for session_id in all_session_ids:
                meta = self.get_session_meta(session_id)
                if meta:
                    # Apply filters
                    if search and search.lower() not in meta.title.lower():
                        continue
                    if status_filter and meta.status != status_filter:
                        continue
                    sessions.append(meta)
            
            total = len(sessions)
            
            # Apply pagination
            start = (page - 1) * page_size
            end = start + page_size
            paginated = sessions[start:end]
            
            return paginated, total
            
        except Exception as e:
            logger.error(f"Failed to get user sessions: {e}")
            return [], 0

    def get_all_sessions(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        status_filter: Optional[SessionStatus] = None,
    ) -> Tuple[List[SessionMeta], int]:
        """Get all sessions with pagination and filtering
        
        Args:
            page: Page number (1-indexed)
            page_size: Number of sessions per page
            search: Optional search term for title
            status_filter: Optional status filter
            
        Returns:
            Tuple of (session list, total count)
        """
        try:
            global_key = "sessions:all"
            
            # Get all session IDs sorted by updated_at (descending)
            all_session_ids = self._redis.client.zrevrange(
                self._redis._key(global_key), 0, -1
            )
            
            if not all_session_ids:
                return [], 0
            
            # Fetch all session metadata for filtering
            sessions = []
            for session_id in all_session_ids:
                meta = self.get_session_meta(session_id)
                if meta:
                    # Apply filters
                    if search and search.lower() not in meta.title.lower():
                        continue
                    if status_filter and meta.status != status_filter:
                        continue
                    sessions.append(meta)
            
            total = len(sessions)
            
            # Apply pagination
            start = (page - 1) * page_size
            end = start + page_size
            paginated = sessions[start:end]
            
            return paginated, total
            
        except Exception as e:
            logger.error(f"Failed to get all sessions: {e}")
            return [], 0

    def get_all_usernames(self) -> List[str]:
        """Get all unique usernames from sessions
        
        Returns:
            List of usernames sorted alphabetically
        """
        try:
            global_key = "sessions:all"
            
            # Get all session IDs
            all_session_ids = self._redis.client.zrevrange(
                self._redis._key(global_key), 0, -1
            )
            
            if not all_session_ids:
                return []
            
            # Collect unique usernames
            usernames = set()
            for session_id in all_session_ids:
                if isinstance(session_id, bytes):
                    session_id = session_id.decode('utf-8')
                meta = self.get_session_meta(session_id)
                if meta and meta.username:
                    usernames.add(meta.username)
            
            return sorted(list(usernames))
            
        except Exception as e:
            logger.error(f"Failed to get usernames: {e}")
            return []

    def update_session_status(
        self,
        session_id: str,
        status: SessionStatus,
        update_timestamp: bool = True,
    ) -> bool:
        """Update session status
        
        Args:
            session_id: Session ID
            status: New status
            update_timestamp: Whether to update updated_at timestamp
            
        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            
            mapping = {"status": status.value}
            updated_at: Optional[int] = None
            if update_timestamp:
                updated_at = int(time.time() * 1000)
                mapping["updated_at"] = str(updated_at)
            
            self._redis.hset(key, mapping)
            
            # Refresh indexes if timestamp changed
            if update_timestamp and updated_at is not None:
                self._redis.zadd("sessions:all", {session_id: updated_at})
                meta = self.get_session_meta(session_id)
                if meta and meta.username:
                    user_key = f"user:{meta.username}:sessions"
                    self._redis.zadd(user_key, {session_id: updated_at})
            
            return True
        except Exception as e:
            logger.error(f"Failed to update session status: {e}")
            return False

    def delete_session(self, session_id: str, username: Optional[str] = None) -> bool:
        """Delete session and all associated data
        
        Args:
            session_id: Session ID
            username: Optional username (for removing from user index)
            
        Returns:
            True if successful
        """
        try:
            # Delete all session keys
            keys_to_delete = [
                f"session:{session_id}:meta",
                f"session:{session_id}:messages",
                f"session:{session_id}:toolcalls",
            ]
            
            for key in keys_to_delete:
                self._redis.delete(key)
            
            # Remove from global index
            global_key = "sessions:all"
            self._redis.zrem(global_key, session_id)
            
            # Remove from user index if username provided
            if username:
                user_key = f"user:{username}:sessions"
                self._redis.zrem(user_key, session_id)
            
            logger.info(f"Deleted session: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            return False

    # ============ Message Operations ============

    def add_session_message(self, session_id: str, message: StoredMessage) -> bool:
        """Add a message to session
        
        Args:
            session_id: Session ID
            message: Message to add
            
        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:messages"
            self._redis.rpush(key, message.to_json())
            
            # Set TTL
            self._redis.client.expire(self._redis._key(key), SESSION_TTL)
            
            # Update session meta
            meta_key = f"session:{session_id}:meta"
            updated_at = int(time.time() * 1000)
            self._redis.hset(meta_key, {
                "message_count": str(self._redis.llen(key)),
                "updated_at": str(updated_at),
            })

            # Refresh indexes
            self._redis.zadd("sessions:all", {session_id: updated_at})
            meta = self.get_session_meta(session_id)
            if meta and meta.username:
                self._redis.zadd(f"user:{meta.username}:sessions", {session_id: updated_at})
            
            return True
        except Exception as e:
            logger.error(f"Failed to add session message: {e}")
            return False

    def update_message(self, session_id: str, message: StoredMessage) -> bool:
        """Update an existing message in session
        
        This replaces the message with matching ID in the list.
        
        Args:
            session_id: Session ID
            message: Updated message
            
        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:messages"
            messages = self._redis.lrange(key, 0, -1)
            
            for i, msg_json in enumerate(messages):
                try:
                    msg_data = json.loads(msg_json)
                    if msg_data.get("id") == message.id:
                        # Found the message, update it
                        self._redis.client.lset(
                            self._redis._key(key), i, message.to_json()
                        )
                        return True
                except json.JSONDecodeError:
                    continue
            
            return False
        except Exception as e:
            logger.error(f"Failed to update message: {e}")
            return False

    def get_session_messages(self, session_id: str) -> List[StoredMessage]:
        """Get all messages for a session
        
        Args:
            session_id: Session ID
            
        Returns:
            List of messages
        """
        try:
            key = f"session:{session_id}:messages"
            messages_json = self._redis.lrange(key, 0, -1)
            
            messages = []
            for msg_json in messages_json:
                try:
                    messages.append(StoredMessage.from_json(msg_json))
                except Exception as e:
                    logger.warning(f"Failed to parse message: {e}")
                    continue
            
            return messages
        except Exception as e:
            logger.error(f"Failed to get session messages: {e}")
            return []

    def get_message_by_id(self, session_id: str, message_id: str) -> Optional[StoredMessage]:
        """Get a specific message by ID
        
        Args:
            session_id: Session ID
            message_id: Message ID
            
        Returns:
            StoredMessage if found, None otherwise
        """
        messages = self.get_session_messages(session_id)
        for msg in messages:
            if msg.id == message_id:
                return msg
        return None

    # ============ Tool Call Operations ============

    def save_tool_call(self, session_id: str, tool_call: StoredToolCall) -> bool:
        """Save a tool call to session
        
        Args:
            session_id: Session ID
            tool_call: Tool call to save
            
        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:toolcalls"
            self._redis.hset(key, {tool_call.id: tool_call.to_json()})
            
            # Set TTL
            self._redis.client.expire(self._redis._key(key), SESSION_TTL)
            
            return True
        except Exception as e:
            logger.error(f"Failed to save tool call: {e}")
            return False

    def get_tool_call(self, session_id: str, tool_call_id: str) -> Optional[StoredToolCall]:
        """Get a specific tool call by ID
        
        Args:
            session_id: Session ID
            tool_call_id: Tool call ID
            
        Returns:
            StoredToolCall if found, None otherwise
        """
        try:
            key = f"session:{session_id}:toolcalls"
            tool_json = self._redis.hget(key, tool_call_id)
            if not tool_json:
                return None
            return StoredToolCall.from_json(tool_json)
        except Exception as e:
            logger.error(f"Failed to get tool call: {e}")
            return None

    def get_session_tool_calls(self, session_id: str) -> List[StoredToolCall]:
        """Get all tool calls for a session
        
        Args:
            session_id: Session ID
            
        Returns:
            List of tool calls
        """
        try:
            key = f"session:{session_id}:toolcalls"
            tool_calls_map = self._redis.hgetall(key)
            
            tool_calls = []
            for tool_json in tool_calls_map.values():
                try:
                    tool_calls.append(StoredToolCall.from_json(tool_json))
                except Exception as e:
                    logger.warning(f"Failed to parse tool call: {e}")
                    continue
            
            # Sort by start_time
            tool_calls.sort(key=lambda x: x.start_time)
            return tool_calls
        except Exception as e:
            logger.error(f"Failed to get session tool calls: {e}")
            return []

    def update_tool_call(self, session_id: str, tool_call: StoredToolCall) -> bool:
        """Update a tool call
        
        Args:
            session_id: Session ID
            tool_call: Updated tool call
            
        Returns:
            True if successful
        """
        return self.save_tool_call(session_id, tool_call)

    # ============ Streaming Content Operations ============

    def save_streaming_content(self, session_id: str, message_id: str, content: str) -> bool:
        """Save temporary streaming content
        
        Args:
            session_id: Session ID
            message_id: Message ID
            content: Current accumulated content
            
        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:msg:{message_id}:content"
            self._redis.set(key, content, ex=STREAMING_CONTENT_TTL)
            return True
        except Exception as e:
            logger.error(f"Failed to save streaming content: {e}")
            return False

    def get_streaming_content(self, session_id: str, message_id: str) -> Optional[str]:
        """Get temporary streaming content
        
        Args:
            session_id: Session ID
            message_id: Message ID
            
        Returns:
            Content string if found, None otherwise
        """
        try:
            key = f"session:{session_id}:msg:{message_id}:content"
            return self._redis.get(key)
        except Exception as e:
            logger.error(f"Failed to get streaming content: {e}")
            return None

    def delete_streaming_content(self, session_id: str, message_id: str) -> bool:
        """Delete temporary streaming content
        
        Args:
            session_id: Session ID
            message_id: Message ID
            
        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:msg:{message_id}:content"
            self._redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Failed to delete streaming content: {e}")
            return False


# Global instance getter
_session_storage: Optional[SessionStorage] = None


def get_session_storage() -> SessionStorage:
    """Get global SessionStorage instance"""
    global _session_storage
    if _session_storage is None:
        _session_storage = SessionStorage()
    return _session_storage

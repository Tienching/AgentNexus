# -*- coding: utf-8 -*-
"""Session Storage Service

Provides CRUD operations for AGUI session data in Redis.
"""

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

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

    def _history_mapping_key(self, provider: str, history_session_id: str, project_path: str) -> str:
        """Build Redis key for history->runtime mapping."""
        project_hash = hashlib.sha1((project_path or "").encode("utf-8")).hexdigest()
        return f"historymap:{provider}:{history_session_id}:{project_hash}"

    def set_history_runtime_mapping(
        self,
        provider: str,
        history_session_id: str,
        project_path: str,
        runtime_session_id: str,
    ) -> bool:
        """Persist mapping from history session to runtime session."""
        try:
            key = self._history_mapping_key(provider, history_session_id, project_path)
            self._redis.set(key, runtime_session_id, ex=SESSION_TTL)
            return True
        except Exception as e:
            logger.error(f"Failed to set history runtime mapping: {e}")
            return False

    def get_history_runtime_mapping(
        self,
        provider: str,
        history_session_id: str,
        project_path: str,
    ) -> Optional[str]:
        """Get mapped runtime session for a history session if exists."""
        try:
            key = self._history_mapping_key(provider, history_session_id, project_path)
            return self._redis.get(key)
        except Exception as e:
            logger.error(f"Failed to get history runtime mapping: {e}")
            return None

    # ============ History Session Hidden (lazy registration) ============

    def hide_history_session(self, session_id: str) -> bool:
        """Mark a history session as hidden (user deleted the promoted runtime session).

        Uses a Redis SET `history:hidden` to track hidden history session IDs.
        """
        try:
            self._redis.sadd("history:hidden", session_id)
            logger.debug(f"Marked history session as hidden: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to hide history session: {e}")
            return False

    def unhide_history_session(self, session_id: str) -> bool:
        """Remove hidden mark from a history session."""
        try:
            self._redis.srem("history:hidden", session_id)
            return True
        except Exception as e:
            logger.error(f"Failed to unhide history session: {e}")
            return False

    def is_history_session_hidden(self, session_id: str) -> bool:
        """Check if a history session is hidden."""
        try:
            return bool(self._redis.sismember("history:hidden", session_id))
        except Exception:
            return False

    def get_hidden_history_sessions(self) -> set:
        """Get all hidden history session IDs."""
        try:
            return self._redis.smembers("history:hidden") or set()
        except Exception:
            return set()

    def set_history_bootstrap_context(self, session_id: str, context: str) -> bool:
        """Set one-time bootstrap context used on next message only."""
        try:
            key = f"session:{session_id}:meta"
            self._redis.hset(key, {"history_bootstrap_context": context})
            return True
        except Exception as e:
            logger.error(f"Failed to set history bootstrap context: {e}")
            return False

    def consume_history_bootstrap_context(self, session_id: str) -> Optional[str]:
        """Consume and clear one-time history bootstrap context."""
        try:
            key = f"session:{session_id}:meta"
            context = self._redis.hget(key, "history_bootstrap_context")
            if context:
                self._redis.hdel(key, "history_bootstrap_context")
            return context or None
        except Exception as e:
            logger.error(f"Failed to consume history bootstrap context: {e}")
            return None

    def set_inherited_session(self, session_id: str, inherited_from: str) -> bool:
        """Mark session as inheriting context from another session.

        Args:
            session_id: Current session ID
            inherited_from: Session ID to inherit context from

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hset(key, {"inherited_from": inherited_from})
            logger.info(f"Set inherited session: {session_id} <- {inherited_from}")
            return True
        except Exception as e:
            logger.error(f"Failed to set inherited session: {e}")
            return False

    def get_inherited_session(self, session_id: str) -> Optional[str]:
        """Get the session ID this session inherited context from.

        Args:
            session_id: Session ID to check

        Returns:
            Inherited session ID if set, None otherwise
        """
        try:
            key = f"session:{session_id}:meta"
            result = self._redis.hget(key, "inherited_from")
            return result
        except Exception as e:
            logger.error(f"Failed to get inherited session: {e}")
            return None

    def clear_inherited_session(self, session_id: str) -> bool:
        """Clear the inherited session flag.

        Args:
            session_id: Session ID to clear

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hdel(key, "inherited_from")
            return True
        except Exception as e:
            logger.error(f"Failed to clear inherited session: {e}")
            return False

    def set_exec_dir_override(self, session_id: str, exec_dir: str) -> bool:
        """Set execution directory override for a session.

        When set, CLIExecutor will use this directory instead of auto-determining one.

        Args:
            session_id: Session ID
            exec_dir: Directory path to use for execution

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hset(key, {"exec_dir_override": exec_dir, "exec_dir": exec_dir})
            logger.info(f"Set exec_dir override: {session_id} -> {exec_dir}")
            return True
        except Exception as e:
            logger.error(f"Failed to set exec_dir override: {e}")
            return False

    def get_exec_dir_override(self, session_id: str) -> Optional[str]:
        """Get execution directory override if set.

        Args:
            session_id: Session ID to check

        Returns:
            Override directory path if set, None otherwise
        """
        try:
            key = f"session:{session_id}:meta"
            result = self._redis.hget(key, "exec_dir_override")
            return result
        except Exception as e:
            logger.error(f"Failed to get exec_dir override: {e}")
            return None

    def clear_exec_dir_override(self, session_id: str) -> bool:
        """Clear the execution directory override.

        Args:
            session_id: Session ID to clear

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hdel(key, "exec_dir_override")
            logger.info(f"Cleared exec_dir override: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear exec_dir override: {e}")
            return False

    def set_target_session_id(self, session_id: str, target_session_id: str) -> bool:
        """Set target session ID for message archiving when in /workspace -t mode.

        When set, messages from this session should be archived to the target session.

        Args:
            session_id: Current user's session ID
            target_session_id: Task's session ID to archive messages to

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hset(key, {"target_session_id": target_session_id})
            logger.info(f"Set target session ID: {session_id} -> {target_session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to set target session ID: {e}")
            return False

    def get_target_session_id(self, session_id: str) -> Optional[str]:
        """Get target session ID if set (for /workspace -t mode).

        Args:
            session_id: Session ID to check

        Returns:
            Target session ID if set, None otherwise
        """
        try:
            key = f"session:{session_id}:meta"
            result = self._redis.hget(key, "target_session_id")
            return result
        except Exception as e:
            logger.error(f"Failed to get target session ID: {e}")
            return None

    def clear_target_session_id(self, session_id: str) -> bool:
        """Clear the target session ID.

        Args:
            session_id: Session ID to clear

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hdel(key, "target_session_id")
            logger.info(f"Cleared target session ID: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear target session ID: {e}")
            return False

    def set_workspace_provider(self, session_id: str, provider: str) -> bool:
        """Store the task's provider when switching workspace via /workspace -t.

        This allows the CLI executor to use the correct resume mechanism
        (e.g., -c for claude, --resume latest for gemini, resume --last for codex).

        Args:
            session_id: Current user's session ID
            provider: The task's provider (e.g., 'claude', 'gemini', 'codex')

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hset(key, {"workspace_provider": provider})
            logger.info(f"Set workspace provider: {session_id} -> {provider}")
            return True
        except Exception as e:
            logger.error(f"Failed to set workspace provider: {e}")
            return False

    def get_workspace_provider(self, session_id: str) -> Optional[str]:
        """Get the workspace task's provider if set (for /workspace -t mode).

        Args:
            session_id: Session ID to check

        Returns:
            Provider string if set, None otherwise
        """
        try:
            key = f"session:{session_id}:meta"
            result = self._redis.hget(key, "workspace_provider")
            return result
        except Exception as e:
            logger.error(f"Failed to get workspace provider: {e}")
            return None

    def clear_workspace_provider(self, session_id: str) -> bool:
        """Clear the workspace provider override.

        Args:
            session_id: Session ID to clear

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hdel(key, "workspace_provider")
            return True
        except Exception as e:
            logger.error(f"Failed to clear workspace provider: {e}")
            return False

    def set_workspace_alias(self, session_id: str, alias: str) -> bool:
        """Store the task's original alias when switching workspace via /workspace -t.

        This preserves the original CLI command name (e.g., 'gemini-internal')
        while using the provider (e.g., 'gemini') for parameter parsing logic.

        Args:
            session_id: Current user's session ID
            alias: The task's original alias (e.g., 'gemini-internal', 'codex-internal')

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hset(key, {"workspace_alias": alias})
            logger.info(f"Set workspace alias: {session_id} -> {alias}")
            return True
        except Exception as e:
            logger.error(f"Failed to set workspace alias: {e}")
            return False

    def get_workspace_alias(self, session_id: str) -> Optional[str]:
        """Get the workspace task's original alias if set (for /workspace -t mode).

        Args:
            session_id: Session ID to check

        Returns:
            Alias string if set, None otherwise
        """
        try:
            key = f"session:{session_id}:meta"
            result = self._redis.hget(key, "workspace_alias")
            return result
        except Exception as e:
            logger.error(f"Failed to get workspace alias: {e}")
            return None

    def clear_workspace_alias(self, session_id: str) -> bool:
        """Clear the workspace alias override.

        Args:
            session_id: Session ID to clear

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hdel(key, "workspace_alias")
            logger.info(f"Cleared workspace alias: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear workspace alias: {e}")
            return False

    # ============ Switch Context (Agent/Model Switching) ============

    def set_handoff_context(self, session_id: str, context: str, target_provider_or_alias: str, model: Optional[str] = None) -> bool:
        """Store switch context for agent/model switching.

        When switching agents, the current agent generates a summary which is
        stored here. The new agent will receive this as initial context.

        Args:
            session_id: Current session ID
            context: Summary/context text from previous agent
            target_provider_or_alias: The provider or alias to switch to
                                     (used as CLI command name, e.g., 'codex' or 'gemini-internal')
            model: Optional LLM model name to use after switching

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            fields = {
                "handoff_context": context,
                "handoff_target_provider": target_provider_or_alias,
            }
            if model:
                fields["handoff_model"] = model
            self._redis.hset(key, fields)
            if not model:
                self._redis.hdel(key, "handoff_model")
            logger.info(f"Set switch context: {session_id} -> {target_provider_or_alias} (model={model})")
            return True
        except Exception as e:
            logger.error(f"Failed to set switch context: {e}")
            return False

    def get_handoff_context(self, session_id: str) -> Optional[Tuple[str, str]]:
        """Get switch context if set.

        Args:
            session_id: Session ID to check

        Returns:
            Tuple of (context, target_provider) if set, None otherwise.
            Context may be empty string if summary is pending.
        """
        try:
            key = f"session:{session_id}:meta"
            context = self._redis.hget(key, "handoff_context")
            target_provider = self._redis.hget(key, "handoff_target_provider")
            # Return if target_provider is set (context can be empty string)
            if target_provider:
                return (context or "", target_provider)
            return None
        except Exception as e:
            logger.error(f"Failed to get switch context: {e}")
            return None

    def get_handoff_model(self, session_id: str) -> Optional[str]:
        """Get switch model if set."""
        try:
            key = f"session:{session_id}:meta"
            return self._redis.hget(key, "handoff_model") or None
        except Exception:
            return None

    def clear_handoff_context(self, session_id: str) -> bool:
        """Clear handoff context after it has been consumed.

        Args:
            session_id: Session ID to clear

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hdel(key, "handoff_context", "handoff_target_provider", "handoff_model")
            logger.info(f"Cleared switch context: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear switch context: {e}")
            return False

    def set_handoff_pending_summary(
        self,
        session_id: str,
        target_provider_or_alias: str,
        model: Optional[str] = None,
        context_mode: str = "full",
    ) -> bool:
        """Store pending switch summary request.

        When user requests /switch -a, we set this flag. The next message
        will trigger the current agent to generate summary/full context first.

        Args:
            session_id: Current session ID
            target_provider_or_alias: The provider or alias to switch to after summary
            model: Optional LLM model name to use after switching
            context_mode: Context injection mode, one of: full | windowed

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            normalized_mode = (context_mode or "full").strip().lower()
            # Backward compat: treat legacy "summary" as "windowed"
            if normalized_mode == "summary":
                normalized_mode = "windowed"
            if normalized_mode not in ("full", "windowed"):
                normalized_mode = "full"
            fields = {
                "handoff_pending_summary": target_provider_or_alias,
                "handoff_pending_context_mode": normalized_mode,
            }
            if model:
                fields["handoff_model"] = model
            self._redis.hset(key, fields)
            if not model:
                self._redis.hdel(key, "handoff_model")
            logger.info(
                f"Set switch pending summary: {session_id} -> {target_provider_or_alias} "
                f"(model={model}, context_mode={normalized_mode})"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set switch pending summary: {e}")
            return False

    def get_handoff_pending_summary(self, session_id: str) -> Optional[str]:
        """Get pending switch summary target provider.

        Args:
            session_id: Session ID to check

        Returns:
            Target provider/alias if pending, None otherwise
        """
        try:
            key = f"session:{session_id}:meta"
            target = self._redis.hget(key, "handoff_pending_summary")
            return target
        except Exception as e:
            logger.error(f"Failed to get handoff pending summary: {e}")
            return None

    def get_handoff_pending_context_mode(self, session_id: str) -> str:
        """Get pending switch context mode.

        Returns:
            "full" or "windowed". Defaults to "full" when unset/invalid.
        """
        try:
            key = f"session:{session_id}:meta"
            mode = (self._redis.hget(key, "handoff_pending_context_mode") or "full").strip().lower()
            # Backward compat: treat legacy "summary" as "windowed"
            if mode == "summary":
                mode = "windowed"
            return mode if mode in ("full", "windowed") else "full"
        except Exception as e:
            logger.error(f"Failed to get handoff pending context mode: {e}")
            return "full"

    def clear_handoff_pending_summary(self, session_id: str) -> bool:
        """Clear pending switch summary request.

        Args:
            session_id: Session ID to clear

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hdel(key, "handoff_pending_summary", "handoff_model", "handoff_pending_context_mode")
            logger.info(f"Cleared switch pending summary: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear switch pending summary: {e}")
            return False

    # ============ Model Override Persistence ============

    def set_model_override(self, session_id: str, model: str) -> bool:
        """Persist a model override for the session.

        Set by ``/switch -m <model>`` (model-only switch).  Unlike
        ``handoff_model`` which is consumed once, this field persists across
        requests until explicitly cleared.

        Args:
            session_id: Session ID
            model: LLM model name (e.g. ``"claude-opus-4.6"``)
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hset(key, {"model_override": model})
            logger.info(f"Set model override: {session_id} -> {model}")
            return True
        except Exception as e:
            logger.error(f"Failed to set model override: {e}")
            return False

    def get_model_override(self, session_id: str) -> Optional[str]:
        """Get the persisted model override if set."""
        try:
            key = f"session:{session_id}:meta"
            return self._redis.hget(key, "model_override") or None
        except Exception:
            return None

    def clear_model_override(self, session_id: str) -> bool:
        """Clear the persisted model override."""
        try:
            key = f"session:{session_id}:meta"
            self._redis.hdel(key, "model_override")
            logger.info(f"Cleared model override: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear model override: {e}")
            return False

    def set_active_model(self, session_id: str, model: str) -> bool:
        """Record the model actually used in the last CLI invocation.

        Used to detect model changes between requests — when the model
        changes, the CLI must start a new session instead of continuing
        the old one (``-c``), because CLI tools like codebuddy lock the
        model for the lifetime of a continued session.
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hset(key, {"active_model": model})
            return True
        except Exception:
            return False

    def get_active_model(self, session_id: str) -> Optional[str]:
        """Get the model used in the last CLI invocation."""
        try:
            key = f"session:{session_id}:meta"
            return self._redis.hget(key, "active_model") or None
        except Exception:
            return None

    # ============ Switch Provider Persistence ============

    def set_handoff_provider(self, session_id: str, provider: str, alias: str) -> bool:
        """Persist the provider/alias chosen by a switch command.

        Unlike ``workspace_provider`` (set by ``/workspace -t``), this field is
        set exclusively when a switch context is consumed.  It ensures that
        *subsequent* requests in the same session keep using the new provider
        without overwriting any workspace-level setting.

        Args:
            session_id: Current session ID
            provider: Resolved provider name (e.g. ``"codex"``)
            alias: Original alias (e.g. ``"codex-internal"``)
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hset(key, {
                "handoff_provider": provider,
                "handoff_alias": alias,
            })
            logger.info(f"Set switch provider: {session_id} -> {provider} (alias={alias})")
            return True
        except Exception as e:
            logger.error(f"Failed to set switch provider: {e}")
            return False

    def get_handoff_provider(self, session_id: str) -> Optional[Tuple[str, str]]:
        """Get the persisted handoff provider/alias.

        Returns:
            ``(provider, alias)`` if set, ``None`` otherwise.
        """
        try:
            key = f"session:{session_id}:meta"
            provider = self._redis.hget(key, "handoff_provider")
            alias = self._redis.hget(key, "handoff_alias")
            if provider:
                return (provider, alias or provider)
            return None
        except Exception as e:
            logger.error(f"Failed to get switch provider: {e}")
            return None

    def clear_handoff_provider(self, session_id: str) -> bool:
        """Clear the persisted handoff provider."""
        try:
            key = f"session:{session_id}:meta"
            self._redis.hdel(key, "handoff_provider", "handoff_alias")
            logger.info(f"Cleared switch provider: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear switch provider: {e}")
            return False

    def set_claude_session_id(self, session_id: str, claude_session_id: str) -> bool:
        """Store Claude CLI session UUID for resumption.

        Args:
            session_id: Our session ID
            claude_session_id: Claude CLI internal session UUID

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hset(key, {"claude_session_id": claude_session_id})
            logger.info(f"Set Claude session ID: {session_id} -> {claude_session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to set Claude session ID: {e}")
            return False

    def get_claude_session_id(self, session_id: str) -> Optional[str]:
        """Get stored Claude CLI session UUID.

        Args:
            session_id: Session ID to check

        Returns:
            Claude CLI session UUID if set, None otherwise
        """
        try:
            key = f"session:{session_id}:meta"
            result = self._redis.hget(key, "claude_session_id")
            return result
        except Exception as e:
            logger.error(f"Failed to get Claude session ID: {e}")
            return None

    def clear_claude_session_id(self, session_id: str) -> bool:
        """Clear the Claude session ID.

        Args:
            session_id: Session ID to clear

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hdel(key, "claude_session_id")
            logger.info(f"Cleared Claude session ID: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear Claude session ID: {e}")
            return False

    # ── Provider-agnostic CLI session ID (generalized from claude_session_id) ──

    def set_cli_session_id(self, session_id: str, cli_session_id: str) -> bool:
        """Store CLI session UUID for resumption (provider-agnostic).

        Also sets the legacy claude_session_id field for backward compatibility.

        Args:
            session_id: Our session ID
            cli_session_id: CLI-internal session UUID (works for any provider)
        """
        try:
            key = f"session:{session_id}:meta"
            self._redis.hset(key, {
                "cli_session_id": cli_session_id,
                "claude_session_id": cli_session_id,  # backward compat
            })
            logger.info(f"Set CLI session ID: {session_id} -> {cli_session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to set CLI session ID: {e}")
            return False

    def get_cli_session_id(self, session_id: str) -> Optional[str]:
        """Get stored CLI session UUID (provider-agnostic).

        Falls back to claude_session_id for backward compatibility.
        """
        try:
            key = f"session:{session_id}:meta"
            result = self._redis.hget(key, "cli_session_id")
            if not result:
                # Fallback to legacy field
                result = self._redis.hget(key, "claude_session_id")
            return result
        except Exception as e:
            logger.error(f"Failed to get CLI session ID: {e}")
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
        """Delete session and all associated data.

        Notes:
            - Idempotent: deleting a non-existent session returns True.
            - If username is not provided, we will best-effort resolve it from session meta
              so user index doesn't accumulate stale ids.
            - Also clears AGUI event log and temporary streaming content keys.
            - If the session was promoted from CLI history (has cli_session_id),
              the history session will be marked as hidden so it doesn't reappear
              in the history list.
        """
        try:
            # Resolve username and cli_session_id from meta before deletion
            meta = None
            if not username:
                try:
                    meta = self.get_session_meta(session_id)
                    if meta and meta.username:
                        username = meta.username
                except Exception:
                    pass

            # Mark associated history session as hidden (best-effort)
            try:
                cli_sid = self.get_cli_session_id(session_id)
                if cli_sid:
                    self.hide_history_session(cli_sid)
                    logger.info(f"Marked history session {cli_sid} as hidden (runtime session {session_id} deleted)")
            except Exception:
                pass

            # Delete all fixed session keys
            keys_to_delete = [
                f"session:{session_id}:meta",
                f"session:{session_id}:messages",
                f"session:{session_id}:toolcalls",
                f"session:{session_id}:events",  # task SSE playback log
            ]
            self._redis.delete(*keys_to_delete)

            # Delete temporary streaming content keys: session:{id}:msg:*:content
            try:
                for key in self._redis.scan_iter(f"session:{session_id}:msg:*:content"):
                    self._redis.delete(key)
            except Exception:
                pass

            # Remove from global index
            self._redis.zrem("sessions:all", session_id)

            # Remove from user index if username known
            if username:
                self._redis.zrem(f"user:{username}:sessions", session_id)

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

    def clear_session_messages(self, session_id: str) -> bool:
        """Clear all messages for a session.

        Args:
            session_id: Session ID

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:messages"
            self._redis.delete(key)
            # Reset message_count in meta
            meta_key = f"session:{session_id}:meta"
            self._redis.hset(meta_key, {"message_count": "0"})
            logger.debug(f"Cleared messages for session: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear session messages: {e}")
            return False

    def clear_session_tool_calls(self, session_id: str) -> bool:
        """Clear all tool calls for a session.

        Args:
            session_id: Session ID

        Returns:
            True if successful
        """
        try:
            key = f"session:{session_id}:toolcalls"
            self._redis.delete(key)
            logger.debug(f"Cleared tool calls for session: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear session tool calls: {e}")
            return False

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

    # ============ AGUI Event Log Operations ============

    def append_agui_event(self, session_id: str, event: Dict[str, Any], max_len: int = 5000) -> bool:
        """Append a raw AG-UI event JSON into an ordered event log.

        用途：Task 在后台执行时，前端无法直连 CLI 的 SSE；我们把转换后的 AG-UI 事件写入 Redis，
        然后由 `/api/nexus/tasks/{id}/agui/stream` 以 SSE 方式增量推送。
        """
        try:
            key = f"session:{session_id}:events"
            self._redis.rpush(key, json.dumps(event, ensure_ascii=False))

            # TTL aligned with session lifetime
            self._redis.client.expire(self._redis._key(key), SESSION_TTL)

            # Best-effort cap
            if max_len and max_len > 0:
                try:
                    # Keep last N items
                    self._redis.client.ltrim(self._redis._key(key), -max_len, -1)
                except Exception:
                    pass

            return True
        except Exception as e:
            logger.error(f"Failed to append AGUI event: {e}")
            return False

    def get_agui_event_count(self, session_id: str) -> int:
        """Get event count for session event log."""
        try:
            key = f"session:{session_id}:events"
            return int(self._redis.llen(key) or 0)
        except Exception:
            return 0

    def get_agui_events(self, session_id: str, start: int = 0, end: int = -1) -> List[Dict[str, Any]]:
        """Get a slice of AG-UI events."""
        try:
            key = f"session:{session_id}:events"
            raw = self._redis.lrange(key, start, end)
            out: List[Dict[str, Any]] = []
            for item in raw or []:
                try:
                    evt = json.loads(item)
                    if isinstance(evt, dict):
                        out.append(evt)
                except Exception:
                    continue
            return out
        except Exception:
            return []


# Global instance getter
_session_storage: Optional[SessionStorage] = None


def get_session_storage() -> SessionStorage:
    """Get global SessionStorage instance"""
    global _session_storage
    if _session_storage is None:
        _session_storage = SessionStorage()
    return _session_storage

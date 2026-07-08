"""Runtime permission mode framework for tool call approval.

Implements four permission modes:
  - auto:   All tools auto-approved (default, preserves current behavior)
  - ask:    Destructive/sensitive tools require explicit approval via callback
  - plan:   Read-only tools auto-approved; write/exec/network tools denied
  - bypass: Everything auto-approved without logging (trusted automation)

The permission gate intercepts tool calls before execution in the agent loop.
Approved calls are cached per-session to avoid re-prompting for identical
operations within the same conversation turn.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Permission mode enum
# ---------------------------------------------------------------------------

class PermissionMode(str, Enum):
    """Runtime permission mode for tool execution."""
    AUTO = "auto"       # All tools auto-approved (default behavior)
    ASK = "ask"         # Sensitive tools require approval callback
    PLAN = "plan"       # Read-only only; write/exec/network denied
    BYPASS = "bypass"   # Everything approved without logging


# ---------------------------------------------------------------------------
# Tool risk classification
# ---------------------------------------------------------------------------

class ToolRisk(str, Enum):
    """Risk level classification for tools."""
    READ = "read"           # Read-only: safe in all modes
    WRITE = "write"         # Modifies files: restricted in plan mode
    EXEC = "exec"           # Executes commands: restricted in plan/ask modes
    NETWORK = "network"     # Network access: restricted in plan mode
    ADMIN = "admin"         # System-level operations: always restricted
    MESSAGE = "message"     # Sends messages: restricted in plan mode


# Default risk classification for known tools.
# Tools not listed here default to ToolRisk.WRITE (conservative).
DEFAULT_TOOL_RISKS: dict[str, ToolRisk] = {
    # Read-only tools
    "read_file": ToolRisk.READ,
    "list_dir": ToolRisk.READ,
    "web_search": ToolRisk.READ,
    "web_fetch": ToolRisk.NETWORK,
    # Write tools
    "write_file": ToolRisk.WRITE,
    "edit_file": ToolRisk.WRITE,
    # Execution tools
    "exec": ToolRisk.EXEC,
    # Communication tools
    "message": ToolRisk.MESSAGE,
    # Orchestration tools
    "spawn": ToolRisk.ADMIN,
    "mission": ToolRisk.ADMIN,
    "cron": ToolRisk.ADMIN,
}


def classify_tool(tool_name: str, custom_risks: dict[str, ToolRisk] | None = None) -> ToolRisk:
    """Classify a tool's risk level.

    Args:
        tool_name: The name of the tool to classify.
        custom_risks: Optional custom risk overrides (merged over defaults).

    Returns:
        The risk classification for the tool.
    """
    risks = {**DEFAULT_TOOL_RISKS, **(custom_risks or {})}
    return risks.get(tool_name, ToolRisk.WRITE)  # Conservative default


# ---------------------------------------------------------------------------
# Approval callback types
# ---------------------------------------------------------------------------

ApprovalCallback = Callable[
    [str, str, dict[str, Any]],  # tool_name, tool_call_id, arguments
    Awaitable[bool],             # True = approved, False = denied
]


@dataclass
class ApprovalRequest:
    """A pending approval request for a tool call."""
    tool_name: str
    tool_call_id: str
    arguments: dict[str, Any]
    risk: ToolRisk
    mode: PermissionMode
    created_at: float = field(default_factory=time.time)


@dataclass
class ApprovalResult:
    """Result of an approval decision."""
    approved: bool
    reason: str = ""
    cached: bool = False


# ---------------------------------------------------------------------------
# Permission cache
# ---------------------------------------------------------------------------

@dataclass
class CacheEntry:
    """A cached approval entry."""
    approved: bool
    created_at: float
    expires_at: float
    args_hash: str


class PermissionCache:
    """Session-scoped cache for tool call approvals.

    Avoids re-prompting for identical operations within a session.
    Cache entries expire after a configurable TTL.
    """

    def __init__(self, ttl_seconds: float = 300.0):
        """Initialize the permission cache.

        Args:
            ttl_seconds: Time-to-live for cache entries in seconds (default 5 min).
        """
        self._ttl = ttl_seconds
        self._entries: dict[str, CacheEntry] = {}

    @staticmethod
    def _make_key(tool_name: str, args_hash: str) -> str:
        """Create a cache key from tool name and args hash."""
        return f"{tool_name}:{args_hash}"

    @staticmethod
    def hash_args(arguments: dict[str, Any]) -> str:
        """Create a deterministic hash of tool call arguments.

        Uses JSON serialization with sorted keys for determinism.
        """
        payload = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def get(self, tool_name: str, arguments: dict[str, Any]) -> CacheEntry | None:
        """Look up a cached approval for the given tool call.

        Returns None if not cached or expired.
        """
        args_hash = self.hash_args(arguments)
        key = self._make_key(tool_name, args_hash)
        entry = self._entries.get(key)

        if entry is None:
            return None

        if time.time() > entry.expires_at:
            del self._entries[key]
            return None

        return entry

    def put(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        approved: bool,
    ) -> None:
        """Cache an approval decision for the given tool call."""
        args_hash = self.hash_args(arguments)
        key = self._make_key(tool_name, args_hash)
        now = time.time()
        self._entries[key] = CacheEntry(
            approved=approved,
            created_at=now,
            expires_at=now + self._ttl,
            args_hash=args_hash,
        )

    def invalidate(self, tool_name: str, arguments: dict[str, Any]) -> None:
        """Remove a cached approval."""
        args_hash = self.hash_args(arguments)
        key = self._make_key(tool_name, args_hash)
        self._entries.pop(key, None)

    def clear(self) -> None:
        """Clear all cached approvals."""
        self._entries.clear()

    @property
    def size(self) -> int:
        """Number of cached entries (including potentially expired)."""
        return len(self._entries)

    def prune_expired(self) -> int:
        """Remove all expired entries. Returns count of pruned entries."""
        now = time.time()
        expired_keys = [
            k for k, v in self._entries.items()
            if now > v.expires_at
        ]
        for k in expired_keys:
            del self._entries[k]
        return len(expired_keys)


# ---------------------------------------------------------------------------
# Permission gate — the core authorization check
# ---------------------------------------------------------------------------

class PermissionGate:
    """Gates tool execution based on the active permission mode.

    Usage in the agent loop::

        gate = PermissionGate(mode=PermissionMode.ASK, approval_callback=my_callback)
        for tc in response.tool_calls:
            result = await gate.check(tc.name, tc.id, tc.arguments)
            if result.approved:
                output = await self.tools.execute(tc.name, tc.arguments)
            else:
                output = f"Permission denied: {result.reason}"
    """

    def __init__(
        self,
        mode: PermissionMode = PermissionMode.AUTO,
        approval_callback: ApprovalCallback | None = None,
        cache_ttl_seconds: float = 300.0,
        custom_risks: dict[str, ToolRisk] | None = None,
    ):
        self._mode = mode
        self._approval_callback = approval_callback
        self._cache = PermissionCache(ttl_seconds=cache_ttl_seconds)
        self._custom_risks = custom_risks or {}
        self._denied_count: int = 0
        self._approved_count: int = 0

    @property
    def mode(self) -> PermissionMode:
        """Current permission mode."""
        return self._mode

    @mode.setter
    def mode(self, value: PermissionMode) -> None:
        """Change the permission mode. Clears the cache on mode change."""
        if value != self._mode:
            logger.info("Permission mode changed: {} → {}", self._mode.value, value.value)
            self._mode = value
            self._cache.clear()

    @property
    def cache(self) -> PermissionCache:
        """Access the permission cache (for inspection or manual invalidation)."""
        return self._cache

    @property
    def stats(self) -> dict[str, int]:
        """Approval/denial statistics."""
        return {
            "approved": self._approved_count,
            "denied": self._denied_count,
            "cache_size": self._cache.size,
        }

    async def check(
        self,
        tool_name: str,
        tool_call_id: str,
        arguments: dict[str, Any] | list | str,
    ) -> ApprovalResult:
        """Check whether a tool call is permitted under the current mode.

        This is the main entry point called by the agent loop before
        each tool execution.

        Args:
            tool_name: Name of the tool being called.
            tool_call_id: Unique ID of the tool call (from the LLM response).
            arguments: Tool call arguments (may be dict, list, or string).

        Returns:
            ApprovalResult indicating whether the call is allowed.
        """
        # Normalize arguments to dict for consistent hashing
        args = self._normalize_args(arguments)
        risk = classify_tool(tool_name, self._custom_risks)

        # --- Mode-specific logic ---

        if self._mode == PermissionMode.BYPASS:
            # Everything allowed, no logging
            self._approved_count += 1
            return ApprovalResult(approved=True, reason="bypass_mode")

        if self._mode == PermissionMode.AUTO:
            # Everything allowed with logging for sensitive tools
            if risk in (ToolRisk.EXEC, ToolRisk.ADMIN):
                logger.info("Auto-approved sensitive tool: {} (risk={})", tool_name, risk.value)
            self._approved_count += 1
            return ApprovalResult(approved=True, reason="auto_mode")

        if self._mode == PermissionMode.PLAN:
            return self._check_plan_mode(tool_name, tool_call_id, args, risk)

        if self._mode == PermissionMode.ASK:
            return await self._check_ask_mode(tool_name, tool_call_id, args, risk)

        # Unknown mode — deny by default
        self._denied_count += 1
        return ApprovalResult(approved=False, reason=f"unknown_mode:{self._mode}")

    def _check_plan_mode(
        self,
        tool_name: str,
        tool_call_id: str,
        args: dict[str, Any],
        risk: ToolRisk,
    ) -> ApprovalResult:
        """Plan mode: only read-only tools are allowed."""
        if risk == ToolRisk.READ:
            self._approved_count += 1
            return ApprovalResult(
                approved=True,
                reason=f"plan_mode:read_tool:{tool_name}",
            )

        self._denied_count += 1
        return ApprovalResult(
            approved=False,
            reason=f"plan_mode:tool_{risk.value}_not_allowed:{tool_name}",
        )

    async def _check_ask_mode(
        self,
        tool_name: str,
        tool_call_id: str,
        args: dict[str, Any],
        risk: ToolRisk,
    ) -> ApprovalResult:
        """Ask mode: auto-approve reads, ask for everything else via callback."""
        # Auto-approve read-only tools
        if risk == ToolRisk.READ:
            self._approved_count += 1
            return ApprovalResult(
                approved=True,
                reason=f"ask_mode:read_tool:{tool_name}",
            )

        # Check cache first
        cached = self._cache.get(tool_name, args)
        if cached is not None:
            if cached.approved:
                self._approved_count += 1
                return ApprovalResult(approved=True, reason="cached_approval", cached=True)
            else:
                self._denied_count += 1
                return ApprovalResult(approved=False, reason="cached_denial", cached=True)

        # Need to ask via callback
        if self._approval_callback is None:
            # No callback configured — deny by default in ask mode
            self._denied_count += 1
            return ApprovalResult(
                approved=False,
                reason=f"ask_mode:no_callback:tool_{risk.value}:{tool_name}",
            )

        try:
            approved = await self._approval_callback(tool_name, tool_call_id, args)
        except Exception as e:
            logger.warning("Approval callback failed for {}: {}", tool_name, e)
            self._denied_count += 1
            return ApprovalResult(
                approved=False,
                reason=f"ask_mode:callback_error:{e}",
            )

        # Cache the decision
        self._cache.put(tool_name, args, approved)

        if approved:
            self._approved_count += 1
            return ApprovalResult(
                approved=True,
                reason=f"ask_mode:approved:{tool_name}",
            )
        else:
            self._denied_count += 1
            return ApprovalResult(
                approved=False,
                reason=f"ask_mode:denied:{tool_name}",
            )

    @staticmethod
    def _normalize_args(arguments: dict[str, Any] | list | str) -> dict[str, Any]:
        """Normalize tool call arguments to a dict for hashing."""
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, list):
            return {"_args_list": arguments}
        if isinstance(arguments, str):
            return {"_args_str": arguments}
        return {"_args_raw": str(arguments)}

    def reset_stats(self) -> None:
        """Reset approval/denial counters."""
        self._approved_count = 0
        self._denied_count = 0

    def set_approval_callback(self, callback: ApprovalCallback) -> None:
        """Set or replace the approval callback (for ask mode)."""
        self._approval_callback = callback


# ---------------------------------------------------------------------------
# Helper: create a permission gate from a mode string
# ---------------------------------------------------------------------------

def create_permission_gate(
    mode: str = "auto",
    approval_callback: ApprovalCallback | None = None,
    cache_ttl_seconds: float = 300.0,
    custom_risks: dict[str, ToolRisk] | None = None,
) -> PermissionGate:
    """Create a PermissionGate from a mode string.

    Args:
        mode: Permission mode string ("auto", "ask", "plan", "bypass").
        approval_callback: Optional async callback for ask mode.
        cache_ttl_seconds: Cache TTL in seconds.
        custom_risks: Custom tool risk overrides.

    Returns:
        Configured PermissionGate instance.

    Raises:
        ValueError: If the mode string is not recognized.
    """
    try:
        perm_mode = PermissionMode(mode.lower())
    except ValueError:
        valid = ", ".join(m.value for m in PermissionMode)
        raise ValueError(f"Unknown permission mode '{mode}'. Valid modes: {valid}") from None

    return PermissionGate(
        mode=perm_mode,
        approval_callback=approval_callback,
        cache_ttl_seconds=cache_ttl_seconds,
        custom_risks=custom_risks,
    )

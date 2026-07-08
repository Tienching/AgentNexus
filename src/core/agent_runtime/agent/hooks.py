# -*- coding: utf-8 -*-
"""Pre/Post tool hooks and trust-boundary checks.

MC-053: Policy checks before/after tool execution:
- environment variable injection patterns
- sensitive tool boundary checks
- security event auditing
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.core.security import (
    SecuritySeverity,
    get_active_profile,
    log_security_event,
    should_audit_mcp_calls,
    should_block_on_secret_detection,
)


def _safe_log_security_event(**kwargs) -> None:
    try:
        log_security_event(**kwargs)
    except Exception:
        # Never fail tool execution due to audit logging issues.
        return


SENSITIVE_TOOLS = {
    "exec",
    "write_file",
    "edit_file",
    "spawn",
    "mission",
    "cron",
}

ENV_INJECTION_PATTERNS = [
    re.compile(r"\b(export|set)\s+[A-Z_][A-Z0-9_]*\s*=", re.IGNORECASE),
    re.compile(r"\$(\{|\()?[A-Z_][A-Z0-9_]*", re.IGNORECASE),
    re.compile(r"`env`|printenv|/proc/self/environ", re.IGNORECASE),
]

SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
    re.compile(r"-----BEGIN\s+(RSA|EC|OPENSSH)\s+PRIVATE\s+KEY-----", re.IGNORECASE),
]


@dataclass
class HookDecision:
    allowed: bool
    reason: str = ""


class ToolHooks:
    """Tool call hooks for policy enforcement."""

    def before_tool(self, tool_name: str, args: Dict[str, Any]) -> HookDecision:
        profile = get_active_profile()
        payload = json.dumps(args or {}, ensure_ascii=False, default=str)

        # MCP audit hook (by tool naming convention)
        if tool_name.startswith("mcp_") and should_audit_mcp_calls():
            _safe_log_security_event(
                event_type="mcp.call",
                severity=SecuritySeverity.INFO,
                source="tool-hook",
                detail=f"MCP tool call: {tool_name}",
            )

        # Sensitive tool boundary hardening in strict mode
        if profile.level == "strict" and tool_name in SENSITIVE_TOOLS:
            if any(p.search(payload) for p in ENV_INJECTION_PATTERNS):
                _safe_log_security_event(
                    event_type="injection.attempt",
                    severity=SecuritySeverity.WARNING,
                    source="tool-hook",
                    detail=f"Env injection-like payload blocked on {tool_name}",
                )
                return HookDecision(
                    allowed=False,
                    reason="blocked_by_hook:env_injection_pattern",
                )

        # Secret detection
        if any(p.search(payload) for p in SECRET_PATTERNS):
            _safe_log_security_event(
                event_type="secret.exposure",
                severity=SecuritySeverity.CRITICAL,
                source="tool-hook",
                detail=f"Secret-like pattern detected for {tool_name}",
            )
            if should_block_on_secret_detection():
                return HookDecision(
                    allowed=False,
                    reason="blocked_by_hook:secret_detection",
                )

        return HookDecision(allowed=True)

    def after_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Any,
        error: Optional[BaseException] = None,
    ) -> None:
        if error is not None:
            _safe_log_security_event(
                event_type="tool.failure",
                severity=SecuritySeverity.WARNING,
                source="tool-hook",
                detail=f"Tool {tool_name} failed: {type(error).__name__}",
            )
            return

        # Post-exec audit for sensitive tools
        if tool_name in SENSITIVE_TOOLS:
            detail = f"Tool {tool_name} executed"
            _safe_log_security_event(
                event_type="tool.executed",
                severity=SecuritySeverity.INFO,
                source="tool-hook",
                detail=detail,
            )

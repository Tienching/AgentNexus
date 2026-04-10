# -*- coding: utf-8 -*-
"""Security audit system package.

Exports:
- SecurityAuditor: Main security audit class
- SecurityEvent, SecurityPosture, SecurityCheck, SecurityCategory, SecurityScanResult: Types
- SecuritySeverity, CheckStatus, CheckSeverity, FixSafety: Enums
- get_auditor(), log_security_event(), get_security_posture(), run_security_scan(): Convenience functions
"""

from __future__ import annotations

from src.core.security.auditor import (
    CheckSeverity,
    CheckStatus,
    FixSafety,
    SecurityAuditor,
    SecurityCategory,
    SecurityCheck,
    SecurityEvent,
    SecurityPosture,
    SecurityScanResult,
    SecuritySeverity,
    get_auditor,
    get_security_posture,
    log_security_event,
    run_security_scan,
)
from src.core.security.hook_profiles import (
    HookProfile,
    HookProfileLevel,
    get_active_profile,
    get_rate_limit_multiplier,
    set_active_profile,
    should_audit_mcp_calls,
    should_block_on_secret_detection,
    should_scan_secrets,
)
from src.core.security.trust_scoring import (
    AgentTrustScoringService,
    TrustScoreBreakdown,
    get_trust_scoring_service,
)

__all__ = [
    "SecurityAuditor",
    "SecurityEvent",
    "SecurityPosture",
    "SecurityCheck",
    "SecurityCategory",
    "SecurityScanResult",
    "SecuritySeverity",
    "CheckStatus",
    "CheckSeverity",
    "FixSafety",
    "get_auditor",
    "log_security_event",
    "get_security_posture",
    "run_security_scan",
    "HookProfile",
    "HookProfileLevel",
    "get_active_profile",
    "set_active_profile",
    "should_scan_secrets",
    "should_audit_mcp_calls",
    "should_block_on_secret_detection",
    "get_rate_limit_multiplier",
    "AgentTrustScoringService",
    "TrustScoreBreakdown",
    "get_trust_scoring_service",
]
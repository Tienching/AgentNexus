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
]
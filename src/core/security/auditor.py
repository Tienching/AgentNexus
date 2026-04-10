# -*- coding: utf-8 -*-
"""Security audit system - real-time security scoring, key detection, MCP call auditing.

Provides:
- Security event logging and agent trust scoring
- Comprehensive security posture scanning
- Credential exposure detection
- Network and runtime security checks

Inspired by Mission Control's security-events.ts and security-scan.ts.
"""

from __future__ import annotations

import importlib
import logging
import os
import platform
import re
import stat
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class SecuritySeverity(str, Enum):
    """Security event severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class CheckStatus(str, Enum):
    """Security check status."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class CheckSeverity(str, Enum):
    """Security check severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FixSafety(str, Enum):
    """Fix safety levels."""

    SAFE = "safe"
    REQUIRES_RESTART = "requires-restart"
    REQUIRES_REVIEW = "requires-review"
    MANUAL_ONLY = "manual-only"


# ---------------------------------------------------------------------------
# Trust weight map — mirrors Mission Control's TRUST_WEIGHTS
# ---------------------------------------------------------------------------

TRUST_WEIGHTS: Dict[str, Dict[str, Any]] = {
    "auth.failure": {"field": "auth_failures", "delta": -0.05},
    "injection.attempt": {"field": "injection_attempts", "delta": -0.15},
    "rate_limit.hit": {"field": "rate_limit_hits", "delta": -0.03},
    "secret.exposure": {"field": "secret_exposures", "delta": -0.20},
    "task.success": {"field": "successful_tasks", "delta": 0.02},
    "task.failure": {"field": "failed_tasks", "delta": -0.01},
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SecurityEvent:
    """A structured security event."""

    event_type: str
    severity: SecuritySeverity = SecuritySeverity.INFO
    source: Optional[str] = None
    agent_name: Optional[str] = None
    detail: Optional[str] = None
    ip_address: Optional[str] = None
    workspace_id: int = 1
    tenant_id: int = 1


@dataclass
class SecurityPosture:
    """Overall security posture score and statistics."""

    score: int
    total_events: int
    critical_events: int
    warning_events: int
    avg_trust_score: float
    recent_incidents: int


@dataclass
class SecurityCheck:
    """A single security check result."""

    id: str
    name: str
    status: CheckStatus
    detail: str
    fix: str
    severity: CheckSeverity = CheckSeverity.MEDIUM
    fix_safety: FixSafety = FixSafety.REQUIRES_REVIEW
    platform: str = "all"


@dataclass
class SecurityCategory:
    """A category of security checks with an aggregate score."""

    score: int
    checks: List[SecurityCheck] = field(default_factory=list)


@dataclass
class SecurityScanResult:
    """Result of a full security scan."""

    overall: str  # 'secure' | 'hardened' | 'needs-attention' | 'at-risk'
    score: int
    timestamp: int
    categories: Dict[str, SecurityCategory] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Security Auditor
# ---------------------------------------------------------------------------


class SecurityAuditor:
    """Security audit system for real-time security scoring and scanning.

    Provides:
    - log_security_event(): Record security events to the database
    - update_agent_trust_score(): Update trust scores based on events
    - get_security_posture(): Get overall security posture
    - run_security_scan(): Run a comprehensive security scan
    """

    _instance: Optional["SecurityAuditor"] = None

    def __new__(cls) -> "SecurityAuditor":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._db = None

    @property
    def db(self):
        """Lazy-load database to avoid circular imports."""
        if self._db is None:
            from src.runtime.stores.db import get_db

            self._db = get_db()
        return self._db

    def log_security_event(self, event: SecurityEvent) -> int:
        """Log a security event to the database.

        Returns the rowid of the inserted event.
        """
        import time

        now = time.time()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO security_events
                (event_type, severity, source, agent_name, detail, ip_address, workspace_id, tenant_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_type,
                    event.severity.value,
                    event.source,
                    event.agent_name,
                    event.detail,
                    event.ip_address,
                    event.workspace_id,
                    event.tenant_id,
                    now,
                ),
            )
            event_id = cursor.lastrowid

        # Update agent trust score
        if event.agent_name:
            self.update_agent_trust_score(event.agent_name, event.event_type, event.workspace_id)

        logger.info(
            "Security event logged: type=%s severity=%s agent=%s",
            event.event_type,
            event.severity.value,
            event.agent_name,
        )

        return event_id

    def update_agent_trust_score(
        self,
        agent_name: str,
        event_type: str,
        workspace_id: int = 1,
    ) -> None:
        """Update an agent's trust score based on a security event.

        Trust scores are calculated using weighted factors and clamped to [0, 1].
        """
        weight = TRUST_WEIGHTS.get(event_type)
        if not weight:
            return

        with self.db.transaction() as conn:
            # Ensure row exists
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_trust_scores (agent_name, workspace_id, trust_score, updated_at)
                VALUES (?, ?, 1.0, ?)
                """,
                (agent_name, workspace_id, time.time()),
            )

            # Increment the counter field
            conn.execute(
                f"""
                UPDATE agent_trust_scores
                SET {weight['field']} = {weight['field']} + 1,
                    updated_at = ?
                WHERE agent_name = ? AND workspace_id = ?
                """,
                (time.time(), agent_name, workspace_id),
            )

            # Recalculate trust score (clamped 0..1)
            row = conn.execute(
                """
                SELECT * FROM agent_trust_scores WHERE agent_name = ? AND workspace_id = ?
                """,
                (agent_name, workspace_id),
            ).fetchone()

            if row:
                score = 1.0
                score += (row["auth_failures"] or 0) * -0.05
                score += (row["injection_attempts"] or 0) * -0.15
                score += (row["rate_limit_hits"] or 0) * -0.03
                score += (row["secret_exposures"] or 0) * -0.20
                score += (row["successful_tasks"] or 0) * 0.02
                score += (row["failed_tasks"] or 0) * -0.01
                score = max(0.0, min(1.0, score))

                is_anomaly = weight["delta"] < 0
                conn.execute(
                    """
                    UPDATE agent_trust_scores
                    SET trust_score = ?,
                        last_anomaly_at = CASE WHEN ? THEN ? ELSE last_anomaly_at END,
                        updated_at = ?
                    WHERE agent_name = ? AND workspace_id = ?
                    """,
                    (score, is_anomaly, time.time(), time.time(), agent_name, workspace_id),
                )

    def get_security_posture(self, workspace_id: int = 1) -> SecurityPosture:
        """Get the overall security posture for a workspace.

        Returns a SecurityPosture with score (0-100), event counts, and trust stats.
        """
        import time

        one_day_ago = time.time() - 86400

        # Get event totals
        totals = self.db.execute_fetchone(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) as critical,
                SUM(CASE WHEN severity = 'warning' THEN 1 ELSE 0 END) as warning
            FROM security_events
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        )

        # Get recent incidents (warning + critical in last 24h)
        recent = self.db.execute_fetchone(
            """
            SELECT COUNT(*) as count
            FROM security_events
            WHERE workspace_id = ? AND severity IN ('warning', 'critical') AND created_at > ?
            """,
            (workspace_id, one_day_ago),
        )

        # Get average trust score
        trust_avg = self.db.execute_fetchone(
            """
            SELECT AVG(trust_score) as avg_trust
            FROM agent_trust_scores
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        )

        avg_trust = trust_avg["avg_trust"] if trust_avg and trust_avg["avg_trust"] is not None else 1.0
        critical_count = totals["critical"] if totals and totals["critical"] else 0
        warning_count = totals["warning"] if totals and totals["warning"] else 0
        recent_count = recent["count"] if recent and recent["count"] else 0

        # Score: start at 100, deduct for incidents
        score = 100
        score -= critical_count * 10
        score -= warning_count * 3
        score -= recent_count * 2
        score = int(max(0, min(100, score * avg_trust)))

        return SecurityPosture(
            score=score,
            total_events=totals["total"] if totals else 0,
            critical_events=critical_count,
            warning_events=warning_count,
            avg_trust_score=round(avg_trust, 2),
            recent_incidents=recent_count,
        )

    def run_security_scan(self) -> SecurityScanResult:
        """Run a comprehensive security scan across all categories.

        Returns a SecurityScanResult with overall score and per-category results.
        """
        credentials = self._scan_credentials()
        network = self._scan_network()
        runtime = self._scan_runtime()
        os_level = self._scan_os()

        categories = {
            "credentials": credentials,
            "network": network,
            "runtime": runtime,
            "os": os_level,
        }

        all_checks = []
        for cat in categories.values():
            all_checks.extend(cat.checks)

        weighted_max = sum(_severity_weight(c.severity) for c in all_checks)
        weighted_score = sum(
            _severity_weight(c.severity) for c in all_checks if c.status == CheckStatus.PASS
        )
        score = int((weighted_score / weighted_max) * 100) if weighted_max > 0 else 0

        if score >= 90:
            overall = "hardened"
        elif score >= 70:
            overall = "secure"
        elif score >= 40:
            overall = "needs-attention"
        else:
            overall = "at-risk"

        return SecurityScanResult(
            overall=overall,
            score=score,
            timestamp=int(time.time() * 1000),
            categories=categories,
        )

    def _scan_credentials(self) -> SecurityCategory:
        """Scan credentials category."""
        checks: List[SecurityCheck] = []

        # AUTH_PASS check
        auth_pass = os.environ.get("AUTH_PASS", "")
        if not auth_pass:
            checks.append(
                SecurityCheck(
                    id="auth_pass",
                    name="Admin password configured",
                    status=CheckStatus.FAIL,
                    detail="AUTH_PASS is not configured",
                    fix="Set AUTH_PASS in .env to a strong password (12+ characters)",
                    severity=CheckSeverity.CRITICAL,
                    fix_safety=FixSafety.SAFE,
                )
            )
        elif auth_pass.lower() in {"admin", "password", "change-me-on-first-login", "changeme", "testpass123"}:
            checks.append(
                SecurityCheck(
                    id="auth_pass",
                    name="Admin password strength",
                    status=CheckStatus.FAIL,
                    detail="AUTH_PASS is set to a known insecure default",
                    fix="Change AUTH_PASS to a unique password with 12+ characters",
                    severity=CheckSeverity.CRITICAL,
                    fix_safety=FixSafety.SAFE,
                )
            )
        elif len(auth_pass) < 12:
            checks.append(
                SecurityCheck(
                    id="auth_pass",
                    name="Admin password strength",
                    status=CheckStatus.WARN,
                    detail=f"AUTH_PASS is only {len(auth_pass)} characters",
                    fix="Use a password with at least 12 characters",
                    severity=CheckSeverity.CRITICAL,
                    fix_safety=FixSafety.SAFE,
                )
            )
        else:
            checks.append(
                SecurityCheck(
                    id="auth_pass",
                    name="Admin password configured",
                    status=CheckStatus.PASS,
                    detail="AUTH_PASS is a strong, non-default password",
                    fix="",
                    severity=CheckSeverity.CRITICAL,
                )
            )

        # API_KEY check
        api_key = os.environ.get("API_KEY", "")
        if not api_key or api_key == "generate-a-random-key":
            checks.append(
                SecurityCheck(
                    id="api_key_set",
                    name="API key configured",
                    status=CheckStatus.FAIL,
                    detail="API_KEY is not set or uses the default placeholder",
                    fix="Run: bash scripts/generate-env.sh --force",
                    severity=CheckSeverity.CRITICAL,
                    fix_safety=FixSafety.REQUIRES_RESTART,
                )
            )
        else:
            checks.append(
                SecurityCheck(
                    id="api_key_set",
                    name="API key configured",
                    status=CheckStatus.PASS,
                    detail="API_KEY is configured",
                    fix="",
                    severity=CheckSeverity.CRITICAL,
                )
            )

        # .env file permissions
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            try:
                mode = stat.S_IMODE(os.stat(env_path).st_mode)
                mode_str = oct(mode)[-3:]
                if mode_str == "600":
                    checks.append(
                        SecurityCheck(
                            id="env_permissions",
                            name=".env file permissions",
                            status=CheckStatus.PASS,
                            detail=f".env permissions are {mode_str}",
                            fix="",
                            severity=CheckSeverity.MEDIUM,
                            fix_safety=FixSafety.SAFE,
                        )
                    )
                else:
                    checks.append(
                        SecurityCheck(
                            id="env_permissions",
                            name=".env file permissions",
                            status=CheckStatus.WARN,
                            detail=f".env permissions are {mode_str}",
                            fix="Run: chmod 600 .env",
                            severity=CheckSeverity.MEDIUM,
                            fix_safety=FixSafety.SAFE,
                        )
                    )
            except OSError:
                checks.append(
                    SecurityCheck(
                        id="env_permissions",
                        name=".env file permissions",
                        status=CheckStatus.WARN,
                        detail="Could not check .env permissions",
                        fix="Run: chmod 600 .env",
                        severity=CheckSeverity.MEDIUM,
                        fix_safety=FixSafety.SAFE,
                    )
                )

        return _score_category(checks)

    def _scan_network(self) -> SecurityCategory:
        """Scan network security category."""
        checks: List[SecurityCheck] = []

        # Allowed hosts check
        allowed_hosts = os.environ.get("MC_ALLOWED_HOSTS", "").strip()
        allow_any = os.environ.get("MC_ALLOW_ANY_HOST")
        if allow_any in ("1", "true"):
            checks.append(
                SecurityCheck(
                    id="allowed_hosts",
                    name="Host allowlist configured",
                    status=CheckStatus.FAIL,
                    detail="MC_ALLOW_ANY_HOST is enabled — any host can connect",
                    fix="Remove MC_ALLOW_ANY_HOST and set MC_ALLOWED_HOSTS instead",
                    severity=CheckSeverity.HIGH,
                    fix_safety=FixSafety.REQUIRES_RESTART,
                )
            )
        elif not allowed_hosts:
            checks.append(
                SecurityCheck(
                    id="allowed_hosts",
                    name="Host allowlist configured",
                    status=CheckStatus.WARN,
                    detail="MC_ALLOWED_HOSTS is not set",
                    fix="Set MC_ALLOWED_HOSTS=localhost,127.0.0.1 in .env",
                    severity=CheckSeverity.HIGH,
                    fix_safety=FixSafety.REQUIRES_RESTART,
                )
            )
        else:
            checks.append(
                SecurityCheck(
                    id="allowed_hosts",
                    name="Host allowlist configured",
                    status=CheckStatus.PASS,
                    detail=f"MC_ALLOWED_HOSTS: {allowed_hosts}",
                    fix="",
                    severity=CheckSeverity.HIGH,
                )
            )

        # HSTS check
        hsts = os.environ.get("MC_ENABLE_HSTS")
        if hsts == "1":
            checks.append(
                SecurityCheck(
                    id="hsts_enabled",
                    name="HSTS enabled",
                    status=CheckStatus.PASS,
                    detail="Strict-Transport-Security header enabled",
                    fix="",
                    severity=CheckSeverity.MEDIUM,
                )
            )
        else:
            checks.append(
                SecurityCheck(
                    id="hsts_enabled",
                    name="HSTS enabled",
                    status=CheckStatus.WARN,
                    detail="HSTS is not enabled",
                    fix="Set MC_ENABLE_HSTS=1 in .env (requires HTTPS)",
                    severity=CheckSeverity.MEDIUM,
                    fix_safety=FixSafety.REQUIRES_RESTART,
                )
            )

        # Cookie secure check
        cookie_secure = os.environ.get("MC_COOKIE_SECURE")
        if cookie_secure in ("1", "true"):
            checks.append(
                SecurityCheck(
                    id="cookie_secure",
                    name="Secure cookies",
                    status=CheckStatus.PASS,
                    detail="Cookies marked secure",
                    fix="",
                    severity=CheckSeverity.MEDIUM,
                )
            )
        else:
            checks.append(
                SecurityCheck(
                    id="cookie_secure",
                    name="Secure cookies",
                    status=CheckStatus.WARN,
                    detail="Cookies not explicitly set to secure",
                    fix="Set MC_COOKIE_SECURE=1 in .env (requires HTTPS)",
                    severity=CheckSeverity.MEDIUM,
                    fix_safety=FixSafety.REQUIRES_RESTART,
                )
            )

        # Gateway bind check (check common config)
        gateway_host = os.environ.get("OPENCLAW_GATEWAY_HOST", os.environ.get("MC_GATEWAY_HOST", ""))
        if gateway_host in ("127.0.0.1", "localhost"):
            checks.append(
                SecurityCheck(
                    id="gateway_local",
                    name="Gateway bound to localhost",
                    status=CheckStatus.PASS,
                    detail=f"Gateway host is {gateway_host}",
                    fix="",
                    severity=CheckSeverity.CRITICAL,
                )
            )
        elif gateway_host:
            checks.append(
                SecurityCheck(
                    id="gateway_local",
                    name="Gateway bound to localhost",
                    status=CheckStatus.FAIL,
                    detail=f"Gateway host is {gateway_host}",
                    fix="Set OPENCLAW_GATEWAY_HOST=127.0.0.1 — never expose the gateway publicly",
                    severity=CheckSeverity.CRITICAL,
                    fix_safety=FixSafety.REQUIRES_RESTART,
                )
            )

        return _score_category(checks)

    def _scan_runtime(self) -> SecurityCategory:
        """Scan runtime security category."""
        checks: List[SecurityCheck] = []

        # Database integrity check
        try:
            result = self.db.execute_fetchone("PRAGMA integrity_check")
            if result and result.get("integrity_check") == "ok":
                checks.append(
                    SecurityCheck(
                        id="db_integrity",
                        name="Database integrity",
                        status=CheckStatus.PASS,
                        detail="Integrity check passed",
                        fix="",
                        severity=CheckSeverity.CRITICAL,
                    )
                )
            else:
                checks.append(
                    SecurityCheck(
                        id="db_integrity",
                        name="Database integrity",
                        status=CheckStatus.FAIL,
                        detail=f"Integrity: {result.get('integrity_check', 'unknown') if result else 'unknown'}",
                        fix="Database may be corrupted — restore from backup",
                        severity=CheckSeverity.CRITICAL,
                    )
                )
        except Exception as e:
            checks.append(
                SecurityCheck(
                    id="db_integrity",
                    name="Database integrity",
                    status=CheckStatus.WARN,
                    detail=f"Could not run integrity check: {e}",
                    fix="",
                    severity=CheckSeverity.CRITICAL,
                )
            )

        # Rate limiting check
        rl_disabled = os.environ.get("MC_DISABLE_RATE_LIMIT")
        if rl_disabled:
            checks.append(
                SecurityCheck(
                    id="rate_limiting",
                    name="Rate limiting active",
                    status=CheckStatus.FAIL,
                    detail="Rate limiting is disabled",
                    fix="Remove MC_DISABLE_RATE_LIMIT from .env",
                    severity=CheckSeverity.HIGH,
                    fix_safety=FixSafety.REQUIRES_RESTART,
                )
            )
        else:
            checks.append(
                SecurityCheck(
                    id="rate_limiting",
                    name="Rate limiting active",
                    status=CheckStatus.PASS,
                    detail="Rate limiting is active",
                    fix="",
                    severity=CheckSeverity.HIGH,
                )
            )

        # Docker detection
        if os.path.exists("/.dockerenv"):
            checks.append(
                SecurityCheck(
                    id="docker_detected",
                    name="Running in Docker",
                    status=CheckStatus.PASS,
                    detail="Container environment detected",
                    fix="",
                    severity=CheckSeverity.LOW,
                )
            )

        return _score_category(checks)

    def _scan_os(self) -> SecurityCategory:
        """Scan OS security category."""
        checks: List[SecurityCheck] = []
        sys_platform = platform.system().lower()
        is_linux = sys_platform == "linux"
        is_darwin = sys_platform == "darwin"
        is_windows = sys_platform == "win32"

        # Not running as root
        try:
            import stat

            uid = os.getuid()
            if uid == 0:
                checks.append(
                    SecurityCheck(
                        id="not_root",
                        name="Not running as root",
                        status=CheckStatus.FAIL,
                        detail="Process is running as root (UID 0)",
                        fix="Run as a non-root user",
                        severity=CheckSeverity.CRITICAL,
                        platform="all",
                    )
                )
            else:
                checks.append(
                    SecurityCheck(
                        id="not_root",
                        name="Not running as root",
                        status=CheckStatus.PASS,
                        detail=f"Running as UID {uid}",
                        fix="",
                        severity=CheckSeverity.CRITICAL,
                        platform="all",
                    )
                )
        except AttributeError:
            pass  # Windows doesn't have os.getuid

        # Node/Python version check (Python major version)
        py_version = platform.python_version()
        py_major = tuple(map(int, py_version.split(".")[:2]))
        if py_major >= (3, 10):
            checks.append(
                SecurityCheck(
                    id="python_supported",
                    name="Python version supported",
                    status=CheckStatus.PASS,
                    detail=f"Python v{py_version}",
                    fix="",
                    severity=CheckSeverity.MEDIUM,
                    platform="all",
                )
            )
        elif py_major >= (3, 8):
            checks.append(
                SecurityCheck(
                    id="python_supported",
                    name="Python version supported",
                    status=CheckStatus.WARN,
                    detail=f"Python v{py_version} (consider upgrading to 3.10+)",
                    fix="Upgrade to Python 3.10 LTS or later",
                    severity=CheckSeverity.MEDIUM,
                    platform="all",
                )
            )
        else:
            checks.append(
                SecurityCheck(
                    id="python_supported",
                    name="Python version supported",
                    status=CheckStatus.FAIL,
                    detail=f"Python v{py_version} is unsupported",
                    fix="Upgrade to Python 3.10 LTS or later",
                    severity=CheckSeverity.MEDIUM,
                    platform="all",
                )
            )

        # World-writable files check (Linux/Darwin)
        if is_linux or is_darwin:
            try:
                import subprocess

                cwd = os.getcwd()
                result = subprocess.run(
                    f"find {cwd!r} -maxdepth 2 -perm -o+w -not -type l 2>/dev/null | head -5",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                ww_files = result.stdout.strip().split("\n") if result.stdout else []
                ww_count = len([f for f in ww_files if f.strip()])
                if ww_count == 0:
                    checks.append(
                        SecurityCheck(
                            id="world_writable",
                            name="No world-writable app files",
                            status=CheckStatus.PASS,
                            detail="No world-writable files in app directory",
                            fix="",
                            severity=CheckSeverity.MEDIUM,
                            fix_safety=FixSafety.SAFE,
                            platform="linux" if is_linux else "darwin",
                        )
                    )
                else:
                    checks.append(
                        SecurityCheck(
                            id="world_writable",
                            name="No world-writable app files",
                            status=CheckStatus.WARN,
                            detail=f"{ww_count}+ world-writable file(s) found",
                            fix="Run: chmod o-w on affected files",
                            severity=CheckSeverity.MEDIUM,
                            fix_safety=FixSafety.SAFE,
                            platform="linux" if is_linux else "darwin",
                        )
                    )
            except Exception:
                checks.append(
                    SecurityCheck(
                        id="world_writable",
                        name="No world-writable app files",
                        status=CheckStatus.WARN,
                        detail="Could not check world-writable files",
                        fix="Run: chmod o-w on affected files",
                        severity=CheckSeverity.MEDIUM,
                        fix_safety=FixSafety.SAFE,
                        platform="linux" if is_linux else "darwin",
                    )
                )

        # Linux-specific checks
        if is_linux:
            # ASLR check
            try:
                with open("/proc/sys/kernel/randomize_va_space", "r") as f:
                    aslr = f.read().strip()
                if aslr == "2":
                    checks.append(
                        SecurityCheck(
                            id="linux_aslr",
                            name="Kernel ASLR enabled",
                            status=CheckStatus.PASS,
                            detail="Full ASLR randomization active",
                            fix="",
                            severity=CheckSeverity.CRITICAL,
                            platform="linux",
                        )
                    )
                elif aslr == "1":
                    checks.append(
                        SecurityCheck(
                            id="linux_aslr",
                            name="Kernel ASLR enabled",
                            status=CheckStatus.WARN,
                            detail="Partial ASLR — upgrade to full",
                            fix="Set: sysctl -w kernel.randomize_va_space=2",
                            severity=CheckSeverity.CRITICAL,
                            fix_safety=FixSafety.MANUAL_ONLY,
                            platform="linux",
                        )
                    )
                else:
                    checks.append(
                        SecurityCheck(
                            id="linux_aslr",
                            name="Kernel ASLR enabled",
                            status=CheckStatus.FAIL,
                            detail=f"ASLR value: {aslr}",
                            fix="Set: sysctl -w kernel.randomize_va_space=2",
                            severity=CheckSeverity.CRITICAL,
                            fix_safety=FixSafety.MANUAL_ONLY,
                            platform="linux",
                        )
                    )
            except (OSError, IOError):
                checks.append(
                    SecurityCheck(
                        id="linux_aslr",
                        name="Kernel ASLR enabled",
                        status=CheckStatus.WARN,
                        detail="Could not read ASLR status",
                        fix="Set: sysctl -w kernel.randomize_va_space=2",
                        severity=CheckSeverity.CRITICAL,
                        fix_safety=FixSafety.MANUAL_ONLY,
                        platform="linux",
                    )
                )

            # TCP SYN cookies check
            try:
                with open("/proc/sys/net/ipv4/tcp_syncookies", "r") as f:
                    syn_cookies = f.read().strip()
                if syn_cookies == "1":
                    checks.append(
                        SecurityCheck(
                            id="linux_syn_cookies",
                            name="TCP SYN cookies enabled",
                            status=CheckStatus.PASS,
                            detail="SYN cookie protection active",
                            fix="",
                            severity=CheckSeverity.MEDIUM,
                            fix_safety=FixSafety.MANUAL_ONLY,
                            platform="linux",
                        )
                    )
                else:
                    checks.append(
                        SecurityCheck(
                            id="linux_syn_cookies",
                            name="TCP SYN cookies enabled",
                            status=CheckStatus.WARN,
                            detail="SYN cookies are not enabled",
                            fix="Set: sysctl -w net.ipv4.tcp_syncookies=1",
                            severity=CheckSeverity.MEDIUM,
                            fix_safety=FixSafety.MANUAL_ONLY,
                            platform="linux",
                        )
                    )
            except (OSError, IOError):
                pass

            # Firewall check
            try:
                import subprocess

                ufw_result = subprocess.run(
                    "ufw status 2>/dev/null",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                has_ufw = "active" in ufw_result.stdout.lower()
                iptables_result = subprocess.run(
                    "iptables -L -n 2>/dev/null | wc -l",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                has_iptables = iptables_result.stdout.strip() and int(iptables_result.stdout.strip()) > 8
                if has_ufw or has_iptables:
                    checks.append(
                        SecurityCheck(
                            id="firewall",
                            name="Firewall active",
                            status=CheckStatus.PASS,
                            detail="UFW firewall is active" if has_ufw else "iptables rules present",
                            fix="",
                            severity=CheckSeverity.CRITICAL,
                            platform="linux",
                        )
                    )
                else:
                    checks.append(
                        SecurityCheck(
                            id="firewall",
                            name="Firewall active",
                            status=CheckStatus.WARN,
                            detail="No firewall detected",
                            fix="Enable a firewall: sudo ufw enable",
                            severity=CheckSeverity.CRITICAL,
                            fix_safety=FixSafety.MANUAL_ONLY,
                            platform="linux",
                        )
                    )
            except Exception:
                pass

        return _score_category(checks)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _severity_weight(severity: CheckSeverity) -> int:
    """Get the weight for a check severity."""
    weights = {
        CheckSeverity.CRITICAL: 4,
        CheckSeverity.HIGH: 3,
        CheckSeverity.MEDIUM: 2,
        CheckSeverity.LOW: 1,
    }
    return weights.get(severity, 2)


def _score_category(checks: List[SecurityCheck]) -> SecurityCategory:
    """Score a category based on its checks."""
    if not checks:
        return SecurityCategory(score=100, checks=checks)

    weighted_max = sum(_severity_weight(c.severity) for c in checks)
    weighted_score = sum(
        _severity_weight(c.severity) for c in checks if c.status == CheckStatus.PASS
    )
    score = int((weighted_score / weighted_max) * 100) if weighted_max > 0 else 100
    return SecurityCategory(score=score, checks=checks)


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def get_auditor() -> SecurityAuditor:
    """Get the global SecurityAuditor singleton."""
    return SecurityAuditor()


def log_security_event(
    event_type: str,
    severity: SecuritySeverity = SecuritySeverity.INFO,
    source: Optional[str] = None,
    agent_name: Optional[str] = None,
    detail: Optional[str] = None,
    ip_address: Optional[str] = None,
    workspace_id: int = 1,
    tenant_id: int = 1,
) -> int:
    """Log a security event (convenience function)."""
    event = SecurityEvent(
        event_type=event_type,
        severity=severity,
        source=source,
        agent_name=agent_name,
        detail=detail,
        ip_address=ip_address,
        workspace_id=workspace_id,
        tenant_id=tenant_id,
    )
    return get_auditor().log_security_event(event)


def get_security_posture(workspace_id: int = 1) -> SecurityPosture:
    """Get the security posture for a workspace (convenience function)."""
    return get_auditor().get_security_posture(workspace_id)


def run_security_scan() -> SecurityScanResult:
    """Run a full security scan (convenience function)."""
    return get_auditor().run_security_scan()
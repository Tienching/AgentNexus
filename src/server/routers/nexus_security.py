# -*- coding: utf-8 -*-
"""Security self-diagnostic endpoint.

Ported from mission-control:
  - GET /api/security-scan  (lib/security-scan.ts)

Adapted for agent-nexus: checks .env permissions, Redis security,
process environment, network exposure, and runtime config.
No SQLite or filesystem memory dependencies.
"""

from __future__ import annotations

import asyncio
import os
import platform
import stat
import subprocess
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from .nexus_auth import verify_nexus_auth

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-security"],
    dependencies=[Depends(verify_nexus_auth)],
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

CheckStatus = Literal["pass", "fail", "warn"]
Severity = Literal["critical", "high", "medium", "low"]
FixSafety = Literal["safe", "requires-restart", "requires-review", "manual-only"]


class SecurityCheck(BaseModel):
    id: str
    name: str
    status: CheckStatus
    detail: str
    fix: str = ""
    severity: Severity = "medium"
    fix_safety: Optional[FixSafety] = None


class SecurityCategory(BaseModel):
    score: int = Field(ge=0, le=100)
    checks: List[SecurityCheck] = Field(default_factory=list)


class SecurityScanResult(BaseModel):
    overall: Literal["hardened", "secure", "needs-attention", "at-risk"]
    score: int = Field(ge=0, le=100)
    timestamp: int
    categories: Dict[str, SecurityCategory]


# ---------------------------------------------------------------------------
# Severity-weighted scoring (ported from MC)
# ---------------------------------------------------------------------------

SEVERITY_WEIGHT: Dict[str, int] = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _score_category(checks: List[SecurityCheck]) -> SecurityCategory:
    weighted_max = sum(SEVERITY_WEIGHT.get(c.severity, 2) for c in checks)
    weighted_pass = sum(
        SEVERITY_WEIGHT.get(c.severity, 2) for c in checks if c.status == "pass"
    )
    score = round((weighted_pass / weighted_max) * 100) if weighted_max > 0 else 100
    return SecurityCategory(score=score, checks=checks)


# ---------------------------------------------------------------------------
# Exec helpers
# ---------------------------------------------------------------------------

def _try_exec(cmd: str, timeout: float = 5.0) -> Optional[str]:
    """Run a command and return stdout, None on error."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Category: Credentials
# ---------------------------------------------------------------------------

INSECURE_PASSWORDS = {
    "admin", "password", "change-me-on-first-login", "changeme",
    "testpass123", "nexus", "test", "1234", "12345678",
}


def _scan_credentials() -> SecurityCategory:
    checks: List[SecurityCheck] = []

    # 1. NEXUS_PASSWORD check
    nexus_pw = getattr(settings, "nexus_password", None) or ""
    if not nexus_pw:
        checks.append(SecurityCheck(
            id="nexus_password",
            name="Nexus password configured",
            status="warn",
            detail="NEXUS_PASSWORD is not set — UI is unprotected",
            fix="Set NEXUS_PASSWORD in .env to restrict access",
            severity="high",
        ))
    elif nexus_pw.lower() in INSECURE_PASSWORDS:
        checks.append(SecurityCheck(
            id="nexus_password",
            name="Nexus password strength",
            status="fail",
            detail="NEXUS_PASSWORD is set to a known insecure default",
            fix="Change NEXUS_PASSWORD to a unique password with 12+ characters",
            severity="critical",
        ))
    elif len(nexus_pw) < 8:
        checks.append(SecurityCheck(
            id="nexus_password",
            name="Nexus password strength",
            status="warn",
            detail=f"NEXUS_PASSWORD is only {len(nexus_pw)} characters",
            fix="Use a password with at least 12 characters",
            severity="high",
        ))
    else:
        checks.append(SecurityCheck(
            id="nexus_password",
            name="Nexus password strength",
            status="pass",
            detail="NEXUS_PASSWORD is configured with a reasonable length",
            fix="",
            severity="high",
        ))

    # 2. .env file permissions
    env_path = Path(os.getcwd()) / ".env"
    if env_path.exists():
        try:
            mode = oct(env_path.stat().st_mode & 0o777)
            checks.append(SecurityCheck(
                id="env_permissions",
                name=".env file permissions",
                status="pass" if mode == "0o600" else "warn",
                detail=f".env permissions are {mode}",
                fix="Run: chmod 600 .env" if mode != "0o600" else "",
                severity="medium",
                fix_safety="safe",
            ))
        except Exception:
            checks.append(SecurityCheck(
                id="env_permissions",
                name=".env file permissions",
                status="warn",
                detail="Could not check .env permissions",
                fix="Run: chmod 600 .env",
                severity="medium",
                fix_safety="safe",
            ))

    # 3. Redis password
    redis_pw = getattr(settings, "redis_password", None) or os.environ.get("REDIS_PASSWORD", "")
    checks.append(SecurityCheck(
        id="redis_password",
        name="Redis password configured",
        status="pass" if redis_pw else "warn",
        detail="REDIS_PASSWORD is set" if redis_pw else "Redis has no password — acceptable on localhost only",
        fix="" if redis_pw else "Set REDIS_PASSWORD if Redis is network-accessible",
        severity="medium",
    ))

    return _score_category(checks)


# ---------------------------------------------------------------------------
# Category: Network
# ---------------------------------------------------------------------------

def _scan_network() -> SecurityCategory:
    checks: List[SecurityCheck] = []

    # 1. Bind address
    host = getattr(settings, "api_host", "0.0.0.0")
    checks.append(SecurityCheck(
        id="bind_address",
        name="API bind address",
        status="warn" if host == "0.0.0.0" else "pass",
        detail=f"API bound to {host}" + (" (all interfaces)" if host == "0.0.0.0" else ""),
        fix="Set API_HOST=127.0.0.1 to restrict to localhost" if host == "0.0.0.0" else "",
        severity="medium",
    ))

    # 2. Redis bind
    redis_host = getattr(settings, "redis_host", "localhost")
    checks.append(SecurityCheck(
        id="redis_bind",
        name="Redis bound to localhost",
        status="pass" if redis_host in ("localhost", "127.0.0.1", "::1") else "warn",
        detail=f"Redis host: {redis_host}",
        fix="" if redis_host in ("localhost", "127.0.0.1", "::1") else "Ensure Redis is not exposed to the network without auth",
        severity="high" if redis_host not in ("localhost", "127.0.0.1", "::1") else "low",
    ))

    # 3. Debug mode
    debug = getattr(settings, "debug", False) or os.environ.get("DEBUG", "").lower() in ("1", "true")
    checks.append(SecurityCheck(
        id="debug_mode",
        name="Debug mode disabled",
        status="pass" if not debug else "warn",
        detail="Debug mode is OFF" if not debug else "Debug mode is ON — may expose sensitive data",
        fix="" if not debug else "Set DEBUG=false in .env for production",
        severity="medium",
    ))

    # 4. Environment setting
    env = getattr(settings, "environment", "development")
    checks.append(SecurityCheck(
        id="environment",
        name="Production environment",
        status="pass" if env == "production" else "warn",
        detail=f"Environment: {env}",
        fix="" if env == "production" else "Set ENVIRONMENT=production for production deployments",
        severity="low",
    ))

    return _score_category(checks)


# ---------------------------------------------------------------------------
# Category: Runtime
# ---------------------------------------------------------------------------

def _scan_runtime() -> SecurityCategory:
    checks: List[SecurityCheck] = []

    # 1. Running as root?
    is_root = os.geteuid() == 0 if hasattr(os, "geteuid") else False
    checks.append(SecurityCheck(
        id="not_root",
        name="Not running as root",
        status="pass" if not is_root else "fail",
        detail="Process runs as non-root user" if not is_root else "Process is running as root!",
        fix="" if not is_root else "Run the service as a non-root user",
        severity="critical",
    ))

    # 2. Python version (security patches)
    py_ver = platform.python_version()
    major, minor, patch = [int(x) for x in py_ver.split(".")[:3]]
    checks.append(SecurityCheck(
        id="python_version",
        name="Python version current",
        status="pass" if (major == 3 and minor >= 11) else "warn",
        detail=f"Python {py_ver}",
        fix="" if (major == 3 and minor >= 11) else "Upgrade to Python 3.11+ for security patches",
        severity="medium",
    ))

    # 3. Executor isolation
    executor_enabled = getattr(settings, "executor_enabled", True)
    if executor_enabled:
        checks.append(SecurityCheck(
            id="executor_enabled",
            name="Executor enabled",
            status="warn",
            detail="Task executor is enabled — ensure CLI commands are trusted",
            fix="Set EXECUTOR_ENABLED=false if not needed",
            severity="medium",
        ))
    else:
        checks.append(SecurityCheck(
            id="executor_enabled",
            name="Executor disabled",
            status="pass",
            detail="Task executor is disabled",
            fix="",
            severity="medium",
        ))

    # 4. Log level
    log_level = getattr(settings, "log_level", "INFO").upper()
    checks.append(SecurityCheck(
        id="log_level",
        name="Log level appropriate",
        status="pass" if log_level not in ("DEBUG", "TRACE") else "warn",
        detail=f"Log level: {log_level}",
        fix="" if log_level not in ("DEBUG", "TRACE") else "Set LOG_LEVEL=INFO in production to avoid leaking sensitive data",
        severity="low",
    ))

    return _score_category(checks)


# ---------------------------------------------------------------------------
# Category: OS
# ---------------------------------------------------------------------------

def _scan_os() -> SecurityCategory:
    checks: List[SecurityCheck] = []

    if platform.system() != "Linux":
        checks.append(SecurityCheck(
            id="os_linux",
            name="Linux host",
            status="warn",
            detail=f"Running on {platform.system()} — some checks skipped",
            fix="",
            severity="low",
        ))
        return _score_category(checks)

    # 1. Firewall active
    ufw = _try_exec("ufw status 2>/dev/null | head -1")
    iptables_count = _try_exec("iptables -L -n 2>/dev/null | wc -l")
    has_firewall = (ufw and "active" in ufw.lower()) or (
        iptables_count and int(iptables_count) > 10
    )
    checks.append(SecurityCheck(
        id="firewall",
        name="Firewall active",
        status="pass" if has_firewall else "warn",
        detail=ufw or "No UFW detected, checked iptables",
        fix="" if has_firewall else "Enable UFW: sudo ufw enable",
        severity="medium",
    ))

    # 2. System uptime (if very long, may miss security patches)
    uptime_s = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else None
    try:
        with open("/proc/uptime") as f:
            uptime = float(f.read().split()[0])
        days = int(uptime / 86400)
        checks.append(SecurityCheck(
            id="uptime",
            name="System recently rebooted",
            status="pass" if days < 90 else "warn",
            detail=f"Uptime: {days} days",
            fix="" if days < 90 else "Consider rebooting to apply kernel patches",
            severity="low",
        ))
    except Exception:
        pass

    # 3. Open ports (just count listening ports)
    ports_out = _try_exec("ss -tlnp 2>/dev/null | tail -n +2 | wc -l")
    if ports_out:
        n_ports = int(ports_out)
        checks.append(SecurityCheck(
            id="open_ports",
            name="Listening ports",
            status="pass" if n_ports < 20 else "warn",
            detail=f"{n_ports} ports listening",
            fix="" if n_ports < 20 else "Review: ss -tlnp — close unnecessary services",
            severity="low",
        ))

    return _score_category(checks)


# ---------------------------------------------------------------------------
# Category: Redis
# ---------------------------------------------------------------------------

def _scan_redis() -> SecurityCategory:
    checks: List[SecurityCheck] = []

    try:
        from ..services.redis_client import get_redis_client
        r = get_redis_client()

        # 1. Redis reachable
        pong = r.ping()
        checks.append(SecurityCheck(
            id="redis_reachable",
            name="Redis reachable",
            status="pass" if pong else "fail",
            detail="Redis PING → PONG" if pong else "Redis not responding",
            fix="" if pong else "Check Redis service: redis-cli ping",
            severity="critical",
        ))

        # 2. Redis version
        info = r.info("server")
        version = info.get("redis_version", "unknown")
        major = int(version.split(".")[0]) if version != "unknown" else 0
        checks.append(SecurityCheck(
            id="redis_version",
            name="Redis version current",
            status="pass" if major >= 6 else "warn",
            detail=f"Redis {version}",
            fix="" if major >= 6 else "Upgrade to Redis 6+ for ACL support",
            severity="medium",
        ))

        # 3. Redis maxmemory
        mem_info = r.info("memory")
        maxmem = mem_info.get("maxmemory", 0)
        checks.append(SecurityCheck(
            id="redis_maxmemory",
            name="Redis maxmemory configured",
            status="pass" if maxmem > 0 else "warn",
            detail=f"maxmemory: {maxmem}" if maxmem > 0 else "maxmemory not set — unbounded memory usage",
            fix="" if maxmem > 0 else "Set maxmemory in redis.conf to prevent OOM",
            severity="medium",
        ))

        # 4. Redis protected-mode
        config_resp = r.config_get("protected-mode")
        protected = config_resp.get("protected-mode", "yes")
        checks.append(SecurityCheck(
            id="redis_protected_mode",
            name="Redis protected mode",
            status="pass" if protected == "yes" else "warn",
            detail=f"protected-mode: {protected}",
            fix="" if protected == "yes" else "Enable protected-mode in redis.conf",
            severity="high",
        ))

    except Exception as e:
        checks.append(SecurityCheck(
            id="redis_reachable",
            name="Redis reachable",
            status="fail",
            detail=f"Redis connection failed: {str(e)[:80]}",
            fix="Ensure Redis is running and REDIS_HOST/REDIS_PORT are correct",
            severity="critical",
        ))

    return _score_category(checks)


# ---------------------------------------------------------------------------
# Main scan function
# ---------------------------------------------------------------------------

def run_security_scan() -> SecurityScanResult:
    """Run all security checks and return a scored result."""
    categories = {
        "credentials": _scan_credentials(),
        "network": _scan_network(),
        "runtime": _scan_runtime(),
        "os": _scan_os(),
        "redis": _scan_redis(),
    }

    all_checks = [c for cat in categories.values() for c in cat.checks]
    weighted_max = sum(SEVERITY_WEIGHT.get(c.severity, 2) for c in all_checks)
    weighted_pass = sum(
        SEVERITY_WEIGHT.get(c.severity, 2) for c in all_checks if c.status == "pass"
    )
    score = round((weighted_pass / weighted_max) * 100) if weighted_max > 0 else 0

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


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/security-scan", response_model=SecurityScanResult)
async def security_scan():
    """Self-diagnostic security scan of the agent-nexus deployment.

    Ported from mission-control GET /api/security-scan (lib/security-scan.ts).
    Checks credentials, network exposure, runtime config, OS hardening,
    and Redis security. Returns a severity-weighted score (0–100) with
    actionable fix suggestions.
    """
    return await asyncio.get_event_loop().run_in_executor(
        None, run_security_scan
    )

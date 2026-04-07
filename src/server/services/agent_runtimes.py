# -*- coding: utf-8 -*-
"""Agent runtime detection and management service.

Ported from mission-control:
  - src/lib/agent-runtimes.ts  (commit 14f34d1)

Detects installed CLI agent runtimes (claude, codex, gemini, codebuddy, nanobot),
their versions, and authentication status. Adapted for Python/FastAPI — no
Node.js, no SQLite, no install jobs (agent-nexus runs CLI tools, not gateways).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

from ..logger import get_logger

logger = get_logger(__name__)

RuntimeId = Literal["claude", "codex", "gemini", "codebuddy", "nanobot"]


@dataclass
class RuntimeMeta:
    name: str
    description: str
    auth_required: bool
    auth_hint: str
    binaries: List[str]  # candidate binary names to search for
    version_flag: str = "--version"


@dataclass
class RuntimeStatus:
    id: str
    name: str
    description: str
    installed: bool
    version: Optional[str]
    binary_path: Optional[str]
    auth_required: bool
    auth_hint: str
    authenticated: bool


RUNTIME_META: Dict[str, RuntimeMeta] = {
    "claude": RuntimeMeta(
        name="Claude Code",
        description="Anthropic CLI agent for software engineering tasks.",
        auth_required=True,
        auth_hint='Run "claude login" after install to authenticate.',
        binaries=["claude"],
    ),
    "codex": RuntimeMeta(
        name="Codex CLI",
        description="OpenAI CLI agent for code generation and editing.",
        auth_required=True,
        auth_hint='Run "codex auth" after install to authenticate.',
        binaries=["codex"],
    ),
    "gemini": RuntimeMeta(
        name="Gemini CLI",
        description="Google CLI agent for code tasks.",
        auth_required=True,
        auth_hint='Set GEMINI_API_KEY in environment to authenticate.',
        binaries=["gemini"],
    ),
    "codebuddy": RuntimeMeta(
        name="CodeBuddy",
        description="Multi-model CLI agent with tool use.",
        auth_required=True,
        auth_hint='Configure API keys in CodeBuddy settings.',
        binaries=["codebuddy"],
    ),
    "nanobot": RuntimeMeta(
        name="Nanobot",
        description="In-process lightweight chat provider.",
        auth_required=False,
        auth_hint="",
        binaries=["nanobot"],
    ),
}


def _detect_binary(
    candidates: List[str], version_flag: str = "--version", timeout: float = 5.0
) -> tuple[bool, Optional[str], Optional[str]]:
    """Try to find a binary and get its version.

    Returns (installed, version_string, binary_path).
    """
    for name in candidates:
        bin_path = shutil.which(name)
        if not bin_path:
            continue
        try:
            result = subprocess.run(
                [bin_path, version_flag],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                version = result.stdout.strip() or result.stderr.strip() or None
                # Clean up multiline version strings
                if version:
                    version = version.split("\n")[0].strip()
                return True, version, bin_path
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            # Binary exists but version check failed — still count as installed
            return True, None, bin_path
    return False, None, None


def _check_claude_auth() -> bool:
    """Check if Claude Code has valid credentials."""
    home = Path.home()
    claude_dir = home / ".claude"
    return any(
        (claude_dir / f).exists()
        for f in ("credentials.json", ".credentials", "settings.json")
    )


def _check_codex_auth() -> bool:
    """Check if Codex CLI has valid credentials."""
    home = Path.home()
    codex_dir = home / ".codex"
    return any(
        (codex_dir / f).exists()
        for f in ("auth.json", "config.json")
    )


def _check_gemini_auth() -> bool:
    """Check if Gemini API key is available."""
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def _check_codebuddy_auth() -> bool:
    """Check if CodeBuddy has configuration."""
    home = Path.home()
    return (home / ".codebuddy").exists() or (home / ".config" / "codebuddy").exists()


def _check_nanobot_auth() -> bool:
    """Nanobot is in-process, always authenticated if importable."""
    try:
        import importlib
        spec = importlib.util.find_spec("src.nanobot")
        return spec is not None
    except Exception:
        return False


AUTH_CHECKERS = {
    "claude": _check_claude_auth,
    "codex": _check_codex_auth,
    "gemini": _check_gemini_auth,
    "codebuddy": _check_codebuddy_auth,
    "nanobot": _check_nanobot_auth,
}


def detect_runtime(runtime_id: str) -> RuntimeStatus:
    """Detect a single runtime's installation and auth status."""
    meta = RUNTIME_META.get(runtime_id)
    if not meta:
        return RuntimeStatus(
            id=runtime_id,
            name=runtime_id,
            description="Unknown runtime",
            installed=False,
            version=None,
            binary_path=None,
            auth_required=False,
            auth_hint="",
            authenticated=False,
        )

    installed, version, bin_path = _detect_binary(meta.binaries, meta.version_flag)

    # Check authentication
    auth_checker = AUTH_CHECKERS.get(runtime_id)
    authenticated = auth_checker() if auth_checker else False

    # Special case: nanobot is always "installed" if the module exists
    if runtime_id == "nanobot" and not installed:
        try:
            import importlib
            spec = importlib.util.find_spec("src.nanobot")
            if spec is not None:
                installed = True
                version = "in-process"
                bin_path = None
                authenticated = True
        except Exception:
            pass

    return RuntimeStatus(
        id=runtime_id,
        name=meta.name,
        description=meta.description,
        installed=installed,
        version=version,
        binary_path=bin_path,
        auth_required=meta.auth_required,
        auth_hint=meta.auth_hint,
        authenticated=authenticated,
    )


def detect_all_runtimes() -> List[RuntimeStatus]:
    """Detect all known runtimes."""
    return [detect_runtime(rid) for rid in RUNTIME_META]

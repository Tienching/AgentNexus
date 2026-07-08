# -*- coding: utf-8 -*-
"""Agent runtime detection and management service.

Ported from mission-control:
  - src/lib/agent-runtimes.ts  (commit 14f34d1)

Detects installed CLI agent runtimes (claude, codex, codebuddy, hermes),
their versions, and authentication status. Adapted for Python/FastAPI — no
Node.js, no SQLite, no install jobs (agent-nexus runs CLI tools, not gateways).
"""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from ..logger import get_logger
from src.runtime.stores.db import Database, get_db

logger = get_logger(__name__)

RuntimeId = Literal["claude", "codex", "codebuddy", "hermes"]


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


@dataclass
class RuntimeDaemon:
    daemon_id: str
    runtime_id: str
    device_name: str = ""
    cli_version: Optional[str] = None
    provider_version: Optional[str] = None
    status: str = "idle"
    health_endpoint: Optional[str] = None
    pending_operations: int = 0
    last_heartbeat: float = field(default_factory=time.time)
    last_health_check: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "daemon_id": self.daemon_id,
            "runtime_id": self.runtime_id,
            "device_name": self.device_name,
            "cli_version": self.cli_version,
            "provider_version": self.provider_version,
            "status": self.status,
            "health_endpoint": self.health_endpoint,
            "pending_operations": self.pending_operations,
            "last_heartbeat": self.last_heartbeat,
            "last_health_check": self.last_health_check,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


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
    "codebuddy": RuntimeMeta(
        name="CodeBuddy",
        description="Multi-model CLI agent with tool use.",
        auth_required=True,
        auth_hint='Configure API keys in CodeBuddy settings.',
        binaries=["codebuddy"],
    ),
    "hermes": RuntimeMeta(
        name="Hermes",
        description="Hermes ACP/CLI agent runtime.",
        auth_required=True,
        auth_hint='Configure Hermes credentials before use.',
        binaries=["hermes"],
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



def _check_codebuddy_auth() -> bool:
    """Check if CodeBuddy has configuration."""
    home = Path.home()
    return (home / ".codebuddy").exists() or (home / ".config" / "codebuddy").exists()


def _check_hermes_auth() -> bool:
    """Check if Hermes has configuration."""
    home = Path.home()
    return (home / ".hermes").exists() or (home / ".config" / "hermes").exists()


AUTH_CHECKERS = {
    "claude": _check_claude_auth,
    "codex": _check_codex_auth,
    "codebuddy": _check_codebuddy_auth,
    "hermes": _check_hermes_auth,
}


class RuntimeDaemonRegistry:
    """SQLite-backed runtime daemon registry and heartbeat log."""

    def __init__(self, db: Optional[Database] = None):
        self._db = db or get_db()
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_daemons (
                    daemon_id TEXT PRIMARY KEY,
                    runtime_id TEXT NOT NULL,
                    device_name TEXT NOT NULL DEFAULT '',
                    cli_version TEXT,
                    provider_version TEXT,
                    status TEXT NOT NULL DEFAULT 'idle',
                    health_endpoint TEXT,
                    pending_operations INTEGER NOT NULL DEFAULT 0,
                    last_heartbeat REAL NOT NULL,
                    last_health_check REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_runtime_daemons_runtime ON runtime_daemons(runtime_id, updated_at DESC)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_runtime_daemons_status ON runtime_daemons(status, updated_at DESC)"
            )
        except Exception:
            pass

    def _row_to_daemon(self, row: Dict[str, Any]) -> RuntimeDaemon:
        metadata: Dict[str, Any] = {}
        raw = row.get("metadata_json")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    metadata = parsed
            except Exception:
                metadata = {}
        return RuntimeDaemon(
            daemon_id=row.get("daemon_id", ""),
            runtime_id=row.get("runtime_id", ""),
            device_name=row.get("device_name") or "",
            cli_version=row.get("cli_version") or None,
            provider_version=row.get("provider_version") or None,
            status=row.get("status") or "idle",
            health_endpoint=row.get("health_endpoint") or None,
            pending_operations=int(row.get("pending_operations") or 0),
            last_heartbeat=float(row.get("last_heartbeat") or time.time()),
            last_health_check=float(row.get("last_health_check") or time.time()),
            metadata=metadata,
            created_at=float(row.get("created_at") or time.time()),
            updated_at=float(row.get("updated_at") or time.time()),
        )

    def register_daemon(
        self,
        daemon_id: str,
        runtime_id: str,
        *,
        device_name: str = "",
        cli_version: Optional[str] = None,
        provider_version: Optional[str] = None,
        status: str = "idle",
        health_endpoint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RuntimeDaemon:
        now = time.time()
        daemon = RuntimeDaemon(
            daemon_id=daemon_id,
            runtime_id=runtime_id,
            device_name=device_name or "",
            cli_version=cli_version,
            provider_version=provider_version,
            status=status or "idle",
            health_endpoint=health_endpoint,
            pending_operations=int((metadata or {}).get("pending_operations") or 0),
            last_heartbeat=now,
            last_health_check=now,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO runtime_daemons (
                    daemon_id, runtime_id, device_name, cli_version, provider_version,
                    status, health_endpoint, pending_operations,
                    last_heartbeat, last_health_check, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(daemon_id) DO UPDATE SET
                    runtime_id=excluded.runtime_id,
                    device_name=excluded.device_name,
                    cli_version=excluded.cli_version,
                    provider_version=excluded.provider_version,
                    status=excluded.status,
                    health_endpoint=excluded.health_endpoint,
                    pending_operations=excluded.pending_operations,
                    last_heartbeat=excluded.last_heartbeat,
                    last_health_check=excluded.last_health_check,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    daemon.daemon_id,
                    daemon.runtime_id,
                    daemon.device_name,
                    daemon.cli_version,
                    daemon.provider_version,
                    daemon.status,
                    daemon.health_endpoint,
                    daemon.pending_operations,
                    daemon.last_heartbeat,
                    daemon.last_health_check,
                    json.dumps(daemon.metadata, ensure_ascii=False),
                    daemon.created_at,
                    daemon.updated_at,
                ),
            )
        return daemon

    def record_daemon_heartbeat(
        self,
        daemon_id: str,
        *,
        status: Optional[str] = None,
        pending_operations: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[RuntimeDaemon]:
        daemon = self.get_daemon(daemon_id)
        if not daemon:
            return None
        now = time.time()
        daemon.last_heartbeat = now
        daemon.updated_at = now
        daemon.last_health_check = daemon.last_health_check or now
        if status:
            daemon.status = status
        if pending_operations is not None:
            daemon.pending_operations = int(pending_operations)
        if metadata:
            daemon.metadata = {**(daemon.metadata or {}), **metadata}
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE runtime_daemons
                SET status = ?, pending_operations = ?, last_heartbeat = ?, last_health_check = ?,
                    metadata_json = ?, updated_at = ?
                WHERE daemon_id = ?
                """,
                (
                    daemon.status,
                    daemon.pending_operations,
                    daemon.last_heartbeat,
                    daemon.last_health_check,
                    json.dumps(daemon.metadata, ensure_ascii=False),
                    daemon.updated_at,
                    daemon_id,
                ),
            )
        return daemon

    def update_daemon_health(
        self,
        daemon_id: str,
        *,
        status: Optional[str] = None,
        health_endpoint: Optional[str] = None,
        pending_operations: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[RuntimeDaemon]:
        daemon = self.get_daemon(daemon_id)
        if not daemon:
            return None
        now = time.time()
        daemon.last_health_check = now
        daemon.updated_at = now
        if status:
            daemon.status = status
        if health_endpoint is not None:
            daemon.health_endpoint = health_endpoint
        if pending_operations is not None:
            daemon.pending_operations = int(pending_operations)
        if metadata:
            daemon.metadata = {**(daemon.metadata or {}), **metadata}
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE runtime_daemons
                SET status = ?, health_endpoint = ?, pending_operations = ?,
                    last_health_check = ?, metadata_json = ?, updated_at = ?
                WHERE daemon_id = ?
                """,
                (
                    daemon.status,
                    daemon.health_endpoint,
                    daemon.pending_operations,
                    daemon.last_health_check,
                    json.dumps(daemon.metadata, ensure_ascii=False),
                    daemon.updated_at,
                    daemon_id,
                ),
            )
        return daemon

    def get_daemon(self, daemon_id: str) -> Optional[RuntimeDaemon]:
        row = self._db.execute_fetchone(
            "SELECT * FROM runtime_daemons WHERE daemon_id = ?",
            (daemon_id,),
        )
        if not row:
            return None
        return self._row_to_daemon(row)

    def list_daemons(self, runtime_id: Optional[str] = None, status: Optional[str] = None) -> List[RuntimeDaemon]:
        conditions: List[str] = []
        params: List[Any] = []
        if runtime_id:
            conditions.append("runtime_id = ?")
            params.append(runtime_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = " AND ".join(conditions) if conditions else "1=1"
        rows = self._db.execute_fetchall(
            f"SELECT * FROM runtime_daemons WHERE {where} ORDER BY updated_at DESC",
            tuple(params),
        )
        return [self._row_to_daemon(row) for row in rows]

    def reap_stale_daemons(self, stale_after_seconds: float = 120.0) -> List[RuntimeDaemon]:
        cutoff = time.time() - stale_after_seconds
        rows = self._db.execute_fetchall(
            "SELECT * FROM runtime_daemons WHERE last_heartbeat < ? AND status != 'offline'",
            (cutoff,),
        )
        out: List[RuntimeDaemon] = []
        for row in rows:
            daemon = self._row_to_daemon(row)
            daemon.status = "offline"
            daemon.updated_at = time.time()
            with self._db.transaction() as conn:
                conn.execute(
                    "UPDATE runtime_daemons SET status = ?, updated_at = ? WHERE daemon_id = ?",
                    (daemon.status, daemon.updated_at, daemon.daemon_id),
                )
            out.append(daemon)
        return out


_runtime_daemon_registry: Optional[RuntimeDaemonRegistry] = None


def get_runtime_daemon_registry() -> RuntimeDaemonRegistry:
    global _runtime_daemon_registry
    if _runtime_daemon_registry is None:
        _runtime_daemon_registry = RuntimeDaemonRegistry()
    return _runtime_daemon_registry


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

# -*- coding: utf-8 -*-
"""Agent runtime detection and management service.

Ported from mission-control:
  - src/lib/agent-runtimes.ts  (commit 14f34d1)

Detects installed CLI agent runtimes (claude, codex, gemini, codebuddy, hermes, openclaw),
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

# Canonical provider set lives in providers.registry.KNOWN_PROVIDERS.
RuntimeId = Literal["claude", "codex", "gemini", "codebuddy", "hermes", "openclaw"]


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
    workspace: str = "default"
    provider: str = "unknown"
    runtime_mode: str = "local"  # "local" (CLI on this host) or "relay" (forwarded)
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
            "workspace": self.workspace,
            "provider": self.provider,
            "runtime_mode": self.runtime_mode,
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


# Provider detection metadata. Sourced from providers.registry.PROVIDER_META
# so there is a single source of truth for name/binaries/auth hints.
def _meta_from_registry() -> Dict[str, RuntimeMeta]:
    from src.providers.registry import PROVIDER_META
    return {
        str(m["id"]): RuntimeMeta(
            name=str(m["name"]),
            description=str(m["description"]),
            auth_required=bool(m["auth_required"]),
            auth_hint=str(m["auth_hint"]),
            binaries=list(m["binaries"]),  # type: ignore[arg-type]
            version_flag=str(m.get("version_flag", "--version")),
        )
        for m in PROVIDER_META
    }


RUNTIME_META: Dict[str, RuntimeMeta] = _meta_from_registry()


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



AUTH_CHECKERS = {
    "claude": _check_claude_auth,
    "codex": _check_codex_auth,
    "gemini": _check_gemini_auth,
    "codebuddy": _check_codebuddy_auth,
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
                    workspace TEXT NOT NULL DEFAULT 'default',
                    daemon_id TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'unknown',
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
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (workspace, daemon_id, provider)
                )
                """
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_runtime_daemons_triple ON runtime_daemons(workspace, daemon_id, provider)"
            )
            # runtime_mode column (Phase 5: local vs relay). Added via migration v022
            # for existing DBs; the ALTER here is a belt-and-suspenders for DBs
            # created by _ensure_table before migrations run.
            cols = {row[1] for row in self._db.execute("PRAGMA table_info(runtime_daemons)").fetchall()}
            if "runtime_mode" not in cols:
                self._db.execute("ALTER TABLE runtime_daemons ADD COLUMN runtime_mode TEXT NOT NULL DEFAULT 'local'")
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_runtime_daemons_mode ON runtime_daemons(runtime_mode, updated_at DESC)"
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
            workspace=row.get("workspace") or "default",
            provider=row.get("provider") or "unknown",
            runtime_mode=row.get("runtime_mode") or "local",
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
        workspace: str = "default",
        provider: str = "unknown",
        runtime_mode: str = "local",
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
            workspace=workspace or "default",
            provider=provider or (metadata or {}).get("provider") or "unknown",
            runtime_mode=runtime_mode or "local",
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
                    workspace, daemon_id, provider, runtime_id, device_name, cli_version, provider_version,
                    status, health_endpoint, pending_operations,
                    last_heartbeat, last_health_check, metadata_json, created_at, updated_at, runtime_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace, daemon_id, provider) DO UPDATE SET
                    runtime_id=excluded.runtime_id,
                    runtime_mode=excluded.runtime_mode,
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
                    daemon.workspace,
                    daemon.daemon_id,
                    daemon.provider,
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
                    daemon.runtime_mode,
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
        workspace: str = "default",
        provider: Optional[str] = None,
    ) -> Optional[RuntimeDaemon]:
        daemon = self.get_daemon(daemon_id, workspace=workspace, provider=provider)
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
                WHERE daemon_id = ? AND workspace = ? AND provider = ?
                """,
                (
                    daemon.status,
                    daemon.pending_operations,
                    daemon.last_heartbeat,
                    daemon.last_health_check,
                    json.dumps(daemon.metadata, ensure_ascii=False),
                    daemon.updated_at,
                    daemon_id,
                    daemon.workspace,
                    daemon.provider,
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
        workspace: str = "default",
        provider: Optional[str] = None,
    ) -> Optional[RuntimeDaemon]:
        daemon = self.get_daemon(daemon_id, workspace=workspace, provider=provider)
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
                WHERE daemon_id = ? AND workspace = ? AND provider = ?
                """,
                (
                    daemon.status,
                    daemon.health_endpoint,
                    daemon.pending_operations,
                    daemon.last_health_check,
                    json.dumps(daemon.metadata, ensure_ascii=False),
                    daemon.updated_at,
                    daemon_id,
                    daemon.workspace,
                    daemon.provider,
                ),
            )
        return daemon

    def get_daemon(
        self,
        daemon_id: str,
        *,
        workspace: str = "default",
        provider: Optional[str] = None,
    ) -> Optional[RuntimeDaemon]:
        """Look up a daemon runtime row.

        With the triple-key schema (workspace, daemon_id, provider) a host may
        have multiple rows. When ``provider`` is given the exact row is returned;
        otherwise the most recently updated row for that daemon.
        """
        if provider:
            row = self._db.execute_fetchone(
                "SELECT * FROM runtime_daemons "
                "WHERE daemon_id = ? AND workspace = ? AND provider = ?",
                (daemon_id, workspace, provider),
            )
        else:
            row = self._db.execute_fetchone(
                "SELECT * FROM runtime_daemons WHERE daemon_id = ? "
                "ORDER BY updated_at DESC LIMIT 1",
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

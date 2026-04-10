# -*- coding: utf-8 -*-
"""Multi-tenant workspace isolation manager.

MC-026: Provides tenant-level isolation for environment, gateway and state dirs.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.stores.sqlite_backend import get_backend


@dataclass
class TenantInfo:
    tenant_id: str
    name: str
    status: str = "active"  # active | suspended | archived
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    workspace_dir: str = ""
    state_dir: str = ""
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class TenantManager:
    """Manage tenant lifecycle and isolated filesystem layout."""

    def __init__(self, root_dir: Optional[str] = None):
        self._store = get_backend()
        self._root = Path(root_dir or (Path.home() / ".nexus" / "tenants"))
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _tenant_key(tenant_id: str) -> str:
        return f"tenant:{tenant_id}"

    @staticmethod
    def _tenant_index_key() -> str:
        return "tenant:index"

    def create_tenant(
        self,
        tenant_id: str,
        name: str,
        gateway_host: str = "127.0.0.1",
        gateway_port: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TenantInfo:
        existing = self.get_tenant(tenant_id)
        if existing:
            raise ValueError(f"tenant already exists: {tenant_id}")

        tenant_root = self._root / tenant_id
        workspace_dir = tenant_root / "workspace"
        state_dir = tenant_root / "state"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)

        assigned_port = gateway_port or self._allocate_gateway_port()
        now = time.time()

        info = TenantInfo(
            tenant_id=tenant_id,
            name=name,
            status="active",
            created_at=now,
            updated_at=now,
            workspace_dir=str(workspace_dir),
            state_dir=str(state_dir),
            gateway_host=gateway_host,
            gateway_port=assigned_port,
            metadata=metadata or {},
        )

        self._store.set(self._tenant_key(tenant_id), asdict(info))
        self._store.hset(self._tenant_index_key(), tenant_id, {"name": name, "status": info.status})
        return info

    def get_tenant(self, tenant_id: str) -> Optional[TenantInfo]:
        data = self._store.get(self._tenant_key(tenant_id))
        if not isinstance(data, dict):
            return None
        try:
            return TenantInfo(**data)
        except Exception:
            return None

    def list_tenants(self) -> List[TenantInfo]:
        ids = sorted(self._store.hkeys(self._tenant_index_key()))
        out: List[TenantInfo] = []
        for tid in ids:
            info = self.get_tenant(str(tid))
            if info:
                out.append(info)
        return out

    def update_status(self, tenant_id: str, status: str) -> Optional[TenantInfo]:
        info = self.get_tenant(tenant_id)
        if not info:
            return None
        if status not in {"active", "suspended", "archived"}:
            raise ValueError(f"invalid tenant status: {status}")
        info.status = status
        info.updated_at = time.time()
        self._store.set(self._tenant_key(tenant_id), asdict(info))
        self._store.hset(self._tenant_index_key(), tenant_id, {"name": info.name, "status": status})
        return info

    def delete_tenant(self, tenant_id: str, remove_dirs: bool = False) -> bool:
        info = self.get_tenant(tenant_id)
        if not info:
            return False

        self._store.delete(self._tenant_key(tenant_id))
        self._store.hdel(self._tenant_index_key(), tenant_id)

        if remove_dirs:
            # Best-effort recursive cleanup
            root = Path(info.workspace_dir).parent
            if root.exists() and root.is_dir():
                for p in sorted(root.rglob("*"), reverse=True):
                    if p.is_file() or p.is_symlink():
                        p.unlink(missing_ok=True)
                    elif p.is_dir():
                        try:
                            p.rmdir()
                        except OSError:
                            pass
                try:
                    root.rmdir()
                except OSError:
                    pass

        return True

    def _allocate_gateway_port(self) -> int:
        """Allocate deterministic per-tenant port from existing tenant count."""
        base = int(os.getenv("NEXUS_TENANT_GATEWAY_BASE_PORT", "34000"))
        return base + len(self.list_tenants()) + 1


_manager: Optional[TenantManager] = None


def get_tenant_manager() -> TenantManager:
    global _manager
    if _manager is None:
        _manager = TenantManager()
    return _manager

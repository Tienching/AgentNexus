# -*- coding: utf-8 -*-
"""Persistent machine identity for a daemon.

A daemon's identity is a UUID decoupled from hostname so it survives renames /
profile changes (mirrors multica's ``identity.go``). The UUID is minted once
and stored at ``~/.agent-nexus/daemon.id`` (overridable via AGENT_NEXUS_DAEMON_ID
or AGENT_NEXUS_IDENTITY_PATH).
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_IDENTITY_PATH = Path.home() / ".agent-nexus" / "daemon.id"


@dataclass(frozen=True)
class DaemonIdentity:
    """The stable identity of a daemon host."""

    daemon_id: str  # persistent UUID, hostname-independent
    device_name: str  # current hostname (informational, may drift)

    def to_dict(self) -> dict:
        return {"daemon_id": self.daemon_id, "device_name": self.device_name}


def _resolve_identity_path() -> Path:
    override = os.environ.get("AGENT_NEXUS_IDENTITY_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_IDENTITY_PATH


def get_or_create_identity(path: Optional[Path] = None) -> DaemonIdentity:
    """Return the persistent identity, minting it on first call.

    Honors ``AGENT_NEXUS_DAEMON_ID`` (forces a specific id without touching disk)
    and ``AGENT_NEXUS_IDENTITY_PATH`` (relocates the id file).
    """
    forced = os.environ.get("AGENT_NEXUS_DAEMON_ID", "").strip()
    if forced:
        return DaemonIdentity(daemon_id=forced, device_name=socket.gethostname())

    id_path = path or _resolve_identity_path()
    try:
        if id_path.exists():
            data = json.loads(id_path.read_text(encoding="utf-8"))
            daemon_id = str(data.get("daemon_id") or "").strip()
            if daemon_id:
                return DaemonIdentity(
                    daemon_id=daemon_id,
                    device_name=socket.gethostname(),
                )
    except Exception:
        pass  # corrupt or unreadable — fall through to mint

    daemon_id = f"daemon-{uuid.uuid4().hex[:16]}"
    identity = DaemonIdentity(daemon_id=daemon_id, device_name=socket.gethostname())
    try:
        id_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file + os.replace (POSIX rename is atomic). Avoids
        # the TOCTOU race where two processes mint distinct UUIDs and clobber
        # each other on concurrent first-run.
        import tempfile as _tmpmod
        fd, tmp_name = _tmpmod.mkstemp(dir=str(id_path.parent), prefix=".daemon.id.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(identity.to_dict(), indent=2))
            os.replace(tmp_name, id_path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except Exception:
        # Identity is held in memory even if persistence fails; next run mints again.
        pass
    return identity

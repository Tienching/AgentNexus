# -*- coding: utf-8 -*-
"""Provider auto-discovery for the daemon.

Probes each provider in ``providers.registry.PROVIDER_META`` via ``shutil.which``
to find which CLI agents are installed on this host. Mirrors multica's
``execenv`` probe pattern (fail-closed: returns an empty set if nothing found,
the caller decides whether that's fatal).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.providers.registry import PROVIDER_META


@dataclass(frozen=True)
class DiscoveredProvider:
    """A provider CLI found on this host."""

    provider: str
    binary: str  # resolved path
    name: str
    version_flag: str = "--version"

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "binary": self.binary,
            "name": self.name,
            "version_flag": self.version_flag,
        }


def _which(binary: str) -> Optional[str]:
    """``shutil.which`` with a login-shell PATH fallback.

    Some CLIs are installed under a shell-init PATH that isn't visible to the
    daemon process. We honor an explicit ``<PROVIDER>_PATH`` override first,
    then try the process PATH, then a small set of common install locations.
    """
    override = os.environ.get(f"AGENT_NEXUS_{binary.upper()}_PATH", "").strip()
    if override and os.path.exists(override):
        return override

    found = shutil.which(binary)
    if found:
        return found

    # Common install locations for user-installed CLIs.
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".local", "bin", binary),
        os.path.join(home, ".bun", "bin", binary),
        os.path.join(home, ".cargo", "bin", binary),
        os.path.join(home, ".npm-global", "bin", binary),
        f"/usr/local/bin/{binary}",
        f"/opt/homebrew/bin/{binary}",
    ]
    for cand in candidates:
        if os.path.exists(cand):
            return cand
    return None


def discover_providers() -> List[DiscoveredProvider]:
    """Discover all installed CLI providers on this host.

    Iterates ``PROVIDER_META`` and probes each provider's candidate binaries.
    A provider is "installed" if at least one of its binaries is found.
    """
    found: List[DiscoveredProvider] = []
    for meta in PROVIDER_META:
        provider_id = str(meta["id"])
        binaries = list(meta.get("binaries") or [])
        for binary in binaries:
            resolved = _which(str(binary))
            if resolved:
                found.append(
                    DiscoveredProvider(
                        provider=provider_id,
                        binary=resolved,
                        name=str(meta["name"]),
                        version_flag=str(meta.get("version_flag", "--version")),
                    )
                )
                break  # first matching binary wins for this provider
    return found


def discovered_provider_map() -> Dict[str, DiscoveredProvider]:
    """Convenience: provider id -> DiscoveredProvider."""
    return {p.provider: p for p in discover_providers()}

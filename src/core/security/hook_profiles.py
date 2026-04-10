# -*- coding: utf-8 -*-
"""Hook profile configuration with minimal/standard/strict security policies.

MC-017: Provides three security policy levels for pre/post tool hooks.
Profile resolution order:
1) Environment variable NEXUS_HOOK_PROFILE
2) Persisted setting in SQLite kv_store (key: settings:hook_profile)
3) Default profile: standard
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Literal

from src.core.stores.sqlite_backend import get_backend

HookProfileLevel = Literal["minimal", "standard", "strict"]


@dataclass(frozen=True)
class HookProfile:
    level: HookProfileLevel
    scan_secrets: bool
    audit_mcp_calls: bool
    block_on_secret_detection: bool
    rate_limit_multiplier: float


PROFILES: Dict[HookProfileLevel, HookProfile] = {
    "minimal": HookProfile(
        level="minimal",
        scan_secrets=False,
        audit_mcp_calls=False,
        block_on_secret_detection=False,
        rate_limit_multiplier=2.0,
    ),
    "standard": HookProfile(
        level="standard",
        scan_secrets=True,
        audit_mcp_calls=True,
        block_on_secret_detection=False,
        rate_limit_multiplier=1.0,
    ),
    "strict": HookProfile(
        level="strict",
        scan_secrets=True,
        audit_mcp_calls=True,
        block_on_secret_detection=True,
        rate_limit_multiplier=0.5,
    ),
}

_SETTINGS_KEY = "settings:hook_profile"
_DEFAULT_LEVEL: HookProfileLevel = "standard"


def _normalize_level(level: str | None) -> HookProfileLevel:
    value = (level or "").strip().lower()
    if value in PROFILES:
        return value  # type: ignore[return-value]
    return _DEFAULT_LEVEL


def get_active_profile() -> HookProfile:
    """Get current hook profile from env/db/defaults."""
    env_level = os.getenv("NEXUS_HOOK_PROFILE")
    if env_level:
        return PROFILES[_normalize_level(env_level)]

    backend = get_backend()
    stored = backend.get(_SETTINGS_KEY)
    if isinstance(stored, str):
        return PROFILES[_normalize_level(stored)]

    return PROFILES[_DEFAULT_LEVEL]


def set_active_profile(level: HookProfileLevel) -> HookProfile:
    """Persist active profile in SQLite kv_store and return resolved profile."""
    normalized = _normalize_level(level)
    backend = get_backend()
    backend.set(_SETTINGS_KEY, normalized)
    return PROFILES[normalized]


def should_scan_secrets() -> bool:
    return get_active_profile().scan_secrets


def should_audit_mcp_calls() -> bool:
    return get_active_profile().audit_mcp_calls


def should_block_on_secret_detection() -> bool:
    return get_active_profile().block_on_secret_detection


def get_rate_limit_multiplier() -> float:
    return get_active_profile().rate_limit_multiplier

# -*- coding: utf-8 -*-
"""Shared provider/alias history config resolution helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional


PROVIDER_CONFIG_DIRS: Dict[str, str] = {
    "claude": ".claude",
    "codebuddy": ".codebuddy",
    "codex": ".codex",
    "gemini": ".gemini",
}


def infer_base_provider(alias_name: str) -> Optional[str]:
    alias = (alias_name or "").strip().lower()
    if not alias:
        return None
    for provider in PROVIDER_CONFIG_DIRS:
        if alias == provider or alias.startswith(provider):
            return provider
    return None


def resolve_tilde(path_str: str, user_home: Path) -> Path:
    raw = (path_str or "").strip()
    if not raw:
        return user_home
    if raw == "~":
        return user_home
    if raw.startswith("~/"):
        return user_home / raw[2:]
    return Path(raw)


def custom_path_belongs_to_user_home(path_obj: Path, user_home: Path) -> bool:
    """Whether a custom absolute path is safe for the given user home."""
    try:
        resolved = path_obj.resolve()
    except Exception:
        resolved = path_obj

    parts = resolved.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "home":
        return parts[2] == user_home.name
    return True


def resolve_history_user_homes(
    *,
    exec_user: str = "",
    user_home_base: str = "/home",
    fallback_exec_user: str = "ubuntu",
    all_users_root: Optional[str] = None,
) -> List[Path]:
    """Resolve target user-home directories for history discovery."""
    base_home = Path(user_home_base or "/home")
    chosen_user = (exec_user or "").strip()
    if chosen_user:
        return [base_home / chosen_user]

    homes: List[Path] = []
    scan_root = Path(all_users_root or user_home_base or "/home")
    if scan_root.is_dir():
        try:
            for entry in sorted(scan_root.iterdir()):
                if entry.is_dir():
                    homes.append(entry)
        except Exception:
            pass

    fallback_user = (fallback_exec_user or "ubuntu").strip() or "ubuntu"
    fallback_home = base_home / fallback_user
    if fallback_home not in homes:
        homes.append(fallback_home)

    seen = set()
    ordered: List[Path] = []
    for home in homes:
        key = str(home)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(home)
    return ordered


def build_alias_config_map(
    *,
    user_home: Path,
    provider_filter: Optional[str] = None,
    alias_registry_map: Optional[Dict[str, str]] = None,
    custom_paths_str: str = "",
) -> Dict[str, Path]:
    """Build alias→config-path mapping from defaults, registry and custom paths."""
    normalized_filter = (provider_filter or "").strip().lower() or None
    alias_map: Dict[str, Path] = {}

    for provider, config_dir in PROVIDER_CONFIG_DIRS.items():
        if normalized_filter and provider != normalized_filter:
            continue
        alias_map[provider] = user_home / config_dir

    registry_map = alias_registry_map or {}
    for alias_name_raw, provider_raw in registry_map.items():
        alias_name = (alias_name_raw or "").strip().lower()
        provider_name = (provider_raw or "").strip().lower()
        if not alias_name:
            continue
        if normalized_filter and alias_name != normalized_filter and provider_name != normalized_filter:
            continue
        config_dir = user_home / f".{alias_name}"
        try:
            if config_dir.exists():
                alias_map[alias_name] = config_dir
        except OSError:
            continue

    if custom_paths_str:
        try:
            custom_paths: Dict[str, str] = json.loads(custom_paths_str)
        except (json.JSONDecodeError, TypeError):
            custom_paths = {}

        for alias_name_raw, path_str in custom_paths.items():
            alias_name = (alias_name_raw or "").strip().lower()
            if not alias_name:
                continue

            base_provider = infer_base_provider(alias_name)
            if normalized_filter and alias_name != normalized_filter and base_provider != normalized_filter:
                continue

            resolved = resolve_tilde(path_str, user_home)
            if resolved.is_absolute():
                if custom_path_belongs_to_user_home(resolved, user_home):
                    alias_map[alias_name] = resolved
            # Non-absolute paths are intentionally ignored here.

    # Auto-discover dotdirs on disk, but ONLY trust names that are either the
    # provider base directory itself or explicitly present in the alias registry.
    # When a provider family filter is active, we also allow clean aliases that
    # belong to that provider family (for example `.gemini-alt`) so filtered
    # history views still surface legitimate local provider variants.
    # Without these guards, backup directories like
    # `.codebuddy.backup.20260317_102924` or
    # `.claude-internal.backup.20251223_103236` would be surfaced as "aliases"
    # in the history UI, which confuses users who never configured them.
    registered_aliases = {
        (name or "").strip().lower()
        for name in (alias_registry_map or {}).keys()
        if (name or "").strip()
    }
    try:
        for entry in user_home.iterdir():
            if not entry.is_dir() or not entry.name.startswith("."):
                continue
            alias_name = entry.name[1:].strip().lower()
            if not alias_name or alias_name in alias_map:
                continue
            base_provider = infer_base_provider(alias_name)
            if not base_provider:
                continue
            # Skip backup / snapshot / tmp / disabled variants. Even if the prefix
            # matches a provider, these are not user-facing aliases.
            if _looks_like_non_alias_dir(alias_name):
                continue
            # Only accept dotdirs that are either the provider root (e.g. `.claude`)
            # or an explicitly registered alias. When the caller has already
            # narrowed the view to a specific provider family, also allow clean
            # provider-prefixed aliases that belong to that family.
            allow_filtered_family_alias = normalized_filter and base_provider == normalized_filter
            if alias_name != base_provider and alias_name not in registered_aliases and not allow_filtered_family_alias:
                continue
            if normalized_filter and alias_name != normalized_filter and base_provider != normalized_filter:
                continue
            alias_map[alias_name] = entry
    except Exception:
        pass

    return alias_map


# Substrings inside an alias name that mark the dotdir as "not a real alias".
# Kept deliberately narrow: these patterns are virtually always human / tool
# backups rather than active configs.
_NON_ALIAS_DIR_MARKERS = (
    ".backup",
    ".bak",
    ".old",
    ".orig",
    ".snapshot",
    ".disabled",
    ".tmp",
)


def _looks_like_non_alias_dir(alias_name: str) -> bool:
    name = (alias_name or "").lower()
    return any(marker in name for marker in _NON_ALIAS_DIR_MARKERS)

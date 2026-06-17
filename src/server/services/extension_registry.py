# -*- coding: utf-8 -*-
"""Unified extension registry for providers, skills, plugins, and UI panels."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.runtime.history.alias_resolution import PROVIDER_CONFIG_DIRS, build_alias_config_map
from src.runtime.plugins.installer import AVAILABLE_PROVIDERS, PluginInstaller
from src.server.config import settings


_SKILL_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


@dataclass
class ExtensionProvider:
    name: str
    display_name: str
    installed: bool
    enabled: bool
    config_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "installed": self.installed,
            "enabled": self.enabled,
            "config_path": self.config_path,
        }


@dataclass
class ExtensionSkill:
    name: str
    description: str = ""
    version: str = ""
    provider: str = ""
    source: str = "provider"
    path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "provider": self.provider,
            "source": self.source,
            "path": self.path,
        }


@dataclass
class ExtensionPlugin:
    plugin_id: str
    name: str
    source: str
    path: str
    capabilities: List[str] = field(default_factory=list)
    panels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "source": self.source,
            "path": self.path,
            "capabilities": list(self.capabilities),
            "panels": list(self.panels),
        }


@dataclass
class ExtensionPanel:
    panel_id: str
    title: str
    placement: str
    route: str
    capability: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "panel_id": self.panel_id,
            "title": self.title,
            "placement": self.placement,
            "route": self.route,
            "capability": self.capability,
        }


class ExtensionRegistryService:
    def __init__(self, *, exec_user: Optional[str] = None):
        self.exec_user = exec_user or settings.exec_user or "ubuntu"
        self.home_base = settings.user_home_base or "/home"
        self.user_home = Path(self.home_base) / self.exec_user
        self.installer = PluginInstaller()

    @staticmethod
    def _parse_skill_md(file_path: Path) -> Dict[str, str]:
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return {}
        match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        if not match:
            return {}
        data: Dict[str, str] = {}
        for line in match.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parsed = re.match(r"^(\w+)\s*:\s*\"?([^\"]*)\"?\s*$", line)
            if parsed:
                data[parsed.group(1)] = parsed.group(2).strip()
        return data

    def _scan_skills_dir(self, skills_dir: Path, provider: str, *, source: str) -> List[ExtensionSkill]:
        if not skills_dir.is_dir():
            return []
        skills: List[ExtensionSkill] = []
        for entry in sorted(skills_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue
            meta = self._parse_skill_md(skill_md)
            skills.append(
                ExtensionSkill(
                    name=meta.get("name", entry.name),
                    description=meta.get("description", ""),
                    version=meta.get("version", ""),
                    provider=provider,
                    source=source,
                    path=str(entry),
                )
            )
        return skills

    def list_providers(self) -> List[ExtensionProvider]:
        installed = set(self.installer.list_installed_providers())
        providers: List[ExtensionProvider] = []
        for name, meta in sorted(AVAILABLE_PROVIDERS.items()):
            config_path = None
            try:
                config_path = str(self.installer.get_config_path("provider", name))
            except Exception:
                config_path = None
            providers.append(
                ExtensionProvider(
                    name=name,
                    display_name=meta.get("name", name.title()),
                    installed=name in installed,
                    enabled=bool(self.installer.is_enabled("provider", name)),
                    config_path=config_path,
                )
            )
        return providers

    def list_bundled_skills(self) -> List[ExtensionSkill]:
        # Bundled skills lived in the retired nanobot engine; provider-discovered
        # skills (list_provider_skills) remain the supported path.
        return []

    def list_provider_skills(self, *, custom_paths: Optional[Dict[str, str]] = None) -> Dict[str, List[ExtensionSkill]]:
        config_map = build_alias_config_map(
            user_home=self.user_home,
            alias_registry_map={},
            custom_paths_str=json.dumps(custom_paths or {}),
        )
        payload: Dict[str, List[ExtensionSkill]] = {}
        for alias_name, config_path in config_map.items():
            payload[alias_name] = self._scan_skills_dir(config_path / "skills", alias_name, source="provider")
        for alias_name, raw_path in (custom_paths or {}).items():
            if alias_name in payload or alias_name in PROVIDER_CONFIG_DIRS:
                continue
            path = Path(raw_path)
            if raw_path.startswith("~/") or raw_path == "~":
                path = self.user_home / raw_path[2:] if len(raw_path) > 2 else self.user_home
            if path.is_absolute():
                payload[alias_name] = self._scan_skills_dir(path, alias_name, source="provider")
        return payload

    def list_plugins(self) -> List[ExtensionPlugin]:
        plugins: List[ExtensionPlugin] = []
        runtime_plugins_root = Path(__file__).resolve().parents[2] / "runtime" / "plugins"
        for entry in sorted(runtime_plugins_root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("__"):
                continue
            plugins.append(
                ExtensionPlugin(
                    plugin_id=entry.name,
                    name=entry.name.replace("-", " ").title(),
                    source="runtime",
                    path=str(entry),
                    capabilities=["provider-registry"] if entry.name == "cli" else ["extension"],
                    panels=["settings.skills", "admin.overview"] if entry.name == "cli" else [],
                )
            )
        return plugins

    def list_panels(self) -> List[ExtensionPanel]:
        return [
            ExtensionPanel("settings.skills", "Skills", "settings", "/api/nexus/skills", "skills.manage"),
            ExtensionPanel("settings.providers", "Providers", "settings", "/api/nexus/config/defaults", "providers.manage"),
            ExtensionPanel("admin.runtimes", "Runtimes", "admin", "/api/nexus/runtimes/daemons", "runtime.read"),
            ExtensionPanel("admin.events", "Events", "admin", "/api/nexus/events", "events.read"),
            ExtensionPanel("admin.control-plane", "Control Plane", "admin", "/api/nexus/control-plane/tenants", "control_plane.read"),
        ]

    def import_bundled_skill(
        self,
        *,
        skill_name: str,
        provider: str,
        skills_path: Optional[str] = None,
        overwrite: bool = False,
    ) -> ExtensionSkill:
        normalized_name = (skill_name or "").strip()
        normalized_provider = (provider or "").strip().lower()
        if not _SKILL_NAME_RE.match(normalized_name):
            raise ValueError("invalid skill_name")
        # Bundled skills were retired with the nanobot engine. Provider skills
        # are imported per-provider via the skills API instead.
        raise ValueError("bundled skills are no longer available; use provider skills")
        if False:  # pragma: no cover - dead branch, kept for minimal diff
            source_dir = None
        if not True:
            raise ValueError(f"bundled skill not found: {normalized_name}")
        allowed_root = None
        if normalized_provider in PROVIDER_CONFIG_DIRS:
            allowed_root = (self.user_home / PROVIDER_CONFIG_DIRS[normalized_provider] / "skills").resolve()
        if skills_path:
            target_root = Path(skills_path)
            if skills_path.startswith("~/") or skills_path == "~":
                target_root = self.user_home / skills_path[2:] if len(skills_path) > 2 else self.user_home
        elif normalized_provider in PROVIDER_CONFIG_DIRS:
            target_root = allowed_root
        else:
            raise ValueError(f"unknown provider: {normalized_provider}")
        target_root = target_root.resolve()
        if allowed_root is not None and target_root != allowed_root:
            raise ValueError("skills_path must match the provider skills directory")
        target_root.mkdir(parents=True, exist_ok=True)
        target_dir = (target_root / normalized_name).resolve()
        if not str(target_dir).startswith(str(target_root)):
            raise ValueError("invalid target path")
        if target_dir.exists():
            if not overwrite:
                raise FileExistsError(f"skill already exists: {normalized_name}")
            shutil.rmtree(target_dir)
        shutil.copytree(source_dir, target_dir)
        meta = self._parse_skill_md(target_dir / "SKILL.md")
        return ExtensionSkill(
            name=meta.get("name", normalized_name),
            description=meta.get("description", ""),
            version=meta.get("version", ""),
            provider=normalized_provider,
            source="imported",
            path=str(target_dir),
        )

    async def get_catalog(self, *, custom_paths: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        providers = await asyncio.to_thread(self.list_providers)
        plugins = await asyncio.to_thread(self.list_plugins)
        bundled_skills = await asyncio.to_thread(self.list_bundled_skills)
        provider_skills = await asyncio.to_thread(self.list_provider_skills, custom_paths=custom_paths or {})
        panels = await asyncio.to_thread(self.list_panels)
        return {
            "providers": [item.to_dict() for item in providers],
            "plugins": [item.to_dict() for item in plugins],
            "bundled_skills": [item.to_dict() for item in bundled_skills],
            "provider_skills": {key: [item.to_dict() for item in value] for key, value in provider_skills.items()},
            "panels": [item.to_dict() for item in panels],
        }


__all__ = [
    "ExtensionProvider",
    "ExtensionSkill",
    "ExtensionPlugin",
    "ExtensionPanel",
    "ExtensionRegistryService",
]

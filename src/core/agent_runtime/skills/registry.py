# -*- coding: utf-8 -*-
"""Skills Hub - Skill registry with security scanning and ClawdHub integration.

Provides a central registry for agent skills with:
- Skill registration and discovery
- Security scanning for prompt injection, credential leakage, etc.
- Skill metadata and version tracking
- ClawdHub integration for external skill packages

Usage:
    from src.core.agent_runtime.skills.registry import SkillRegistry, Skill

    registry = SkillRegistry()
    skill = registry.register(
        name="code-review",
        description="Reviews code for bugs",
        handler="src.skills.code_review",
    )
"""

from __future__ import annotations

import importlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.core.agent_runtime.skills.security_scanner import SkillSecurityScanner


class SkillStatus(str, Enum):
    """Skill status."""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class SecurityRisk(str, Enum):
    """Security risk levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Skill:
    """A registered skill."""
    name: str
    description: str
    handler: str  # Module/path to the skill handler
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    status: SkillStatus = SkillStatus.ACTIVE
    security_risk: SecurityRisk = SecurityRisk.LOW
    security_notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class SkillRegistry:
    """Central registry for agent skills."""

    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._security_scanner = SkillSecurityScanner()
        self._loaded_slash_extensions: set[str] = set()
        self._register_default_skills()

    def _register_default_skills(self) -> None:
        """Register default built-in skills."""
        # These are placeholder skills representing core capabilities
        default_skills = [
            Skill(
                name="task-management",
                description="Task creation, assignment, and tracking",
                handler="src.core.agent_runtime.skills.task_management",
                tags=["core", "tasks"],
            ),
            Skill(
                name="code-execution",
                description="Execute code in sandboxed environment",
                handler="src.core.agent_runtime.skills.code_execution",
                tags=["core", "execution"],
                security_risk=SecurityRisk.HIGH,
                security_notes="Requires sandboxing",
            ),
            Skill(
                name="web-search",
                description="Search the web for information",
                handler="src.core.agent_runtime.skills.web_search",
                tags=["core", "search"],
            ),
            Skill(
                name="file-operations",
                description="Read and write files",
                handler="src.core.agent_runtime.skills.file_operations",
                tags=["core", "files"],
                security_risk=SecurityRisk.MEDIUM,
                security_notes="Access control required",
            ),
        ]

        for skill in default_skills:
            self._skills[skill.name] = skill

    def register(
        self,
        name: str,
        description: str,
        handler: str,
        version: str = "1.0.0",
        author: str = "",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Skill:
        """Register a new skill.

        Args:
            name: Skill name (must be unique)
            description: Skill description
            handler: Module/path to skill handler
            version: Skill version
            author: Skill author
            tags: Optional tags
            metadata: Optional metadata

        Returns:
            The registered Skill
        """
        if name in self._skills:
            # Update existing
            skill = self._skills[name]
            skill.description = description
            skill.handler = handler
            skill.version = version
            skill.author = author
            skill.tags = tags or []
            skill.metadata = metadata or {}
            skill.updated_at = time.time()
        else:
            # Create new
            skill = Skill(
                name=name,
                description=description,
                handler=handler,
                version=version,
                author=author,
                tags=tags or [],
                metadata=metadata or {},
            )
            self._skills[name] = skill

        return skill

    def unregister(self, name: str) -> bool:
        """Unregister a skill.

        Args:
            name: Skill name

        Returns:
            True if unregistered, False if not found
        """
        if name in self._skills:
            del self._skills[name]
            return True
        return False

    def get(self, name: str) -> Optional[Skill]:
        """Get a skill by name.

        Args:
            name: Skill name

        Returns:
            The Skill if found, None otherwise
        """
        return self._skills.get(name)

    def list_skills(
        self,
        tags: Optional[List[str]] = None,
        status: Optional[SkillStatus] = None,
    ) -> List[Skill]:
        """List all skills, optionally filtered.

        Args:
            tags: Only return skills with these tags
            status: Only return skills with this status

        Returns:
            List of matching skills
        """
        result = list(self._skills.values())

        if status:
            result = [s for s in result if s.status == status]

        if tags:
            result = [
                s for s in result
                if any(t in s.tags for t in tags)
            ]

        return result

    def search(self, query: str) -> List[Skill]:
        """Search skills by name or description.

        Args:
            query: Search query

        Returns:
            Matching skills
        """
        query_lower = query.lower()
        result = []
        for skill in self._skills.values():
            if (
                query_lower in skill.name.lower()
                or query_lower in skill.description.lower()
                or any(query_lower in tag.lower() for tag in skill.tags)
            ):
                result.append(skill)
        return result

    @staticmethod
    def _resolve_dotted_callable(path: str):
        """Resolve dotted path (<module>:<callable>) to a Python callable."""
        if not path or ":" not in path:
            raise ValueError("Handler path must be '<module>:<callable>'")
        module_name, attr_name = path.split(":", 1)
        module = importlib.import_module(module_name)
        fn = getattr(module, attr_name, None)
        if not callable(fn):
            raise ValueError(f"Resolved object is not callable: {path}")
        return fn

    def register_slash_extension(
        self,
        *,
        name: str,
        description: str,
        handler: str,
        cmd: str,
        subcmd: str,
        options: Optional[List[Dict[str, Any]]] = None,
        allow_free_text: bool = False,
        free_text_required: bool = False,
        default_subcmd: Optional[str] = None,
        infer_subcmd_from_options: Optional[Dict[str, str]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Skill:
        """Register a skill that also contributes a slash command extension."""
        merged_metadata = dict(metadata or {})
        merged_metadata["slash_extension"] = {
            "cmd": (cmd or "").strip().lower(),
            "subcmd": (subcmd or "").strip().lower(),
            "handler": handler,
            "options": list(options or []),
            "allow_free_text": bool(allow_free_text),
            "free_text_required": bool(free_text_required),
            "default_subcmd": default_subcmd,
            "infer_subcmd_from_options": dict(infer_subcmd_from_options or {}),
        }
        return self.register(
            name=name,
            description=description,
            handler=handler,
            tags=tags or ["slash-extension"],
            metadata=merged_metadata,
        )

    def list_slash_extensions(self) -> List[Dict[str, Any]]:
        """List slash extensions declared in skill metadata."""
        out: List[Dict[str, Any]] = []
        for skill in self._skills.values():
            ext = (skill.metadata or {}).get("slash_extension") if skill.metadata else None
            if not isinstance(ext, dict):
                continue
            payload = dict(ext)
            payload["skill"] = skill.name
            out.append(payload)
        return out

    def load_slash_extensions(self) -> int:
        """Load slash extensions from registry into runtime parser/handler hooks."""
        extensions = self.list_slash_extensions()
        if not extensions:
            return 0

        try:
            from src.runtime.commands.slash import CommandSpec, OptionDef, register_slash_command_extension
        except Exception:
            return 0

        loaded = 0
        for ext in extensions:
            key = f"{ext.get('skill')}:{ext.get('cmd')}:{ext.get('subcmd')}"
            if key in self._loaded_slash_extensions:
                continue

            options = ext.get("options") or []
            option_defs = []
            for opt in options:
                if not isinstance(opt, dict):
                    continue
                short = (opt.get("short") or "").strip()
                long_name = (opt.get("long") or "").strip()
                if not short or not long_name:
                    continue
                option_defs.append(
                    OptionDef(
                        short=short,
                        long=long_name,
                        type=(opt.get("type") or "string").strip(),
                        required=bool(opt.get("required", False)),
                        default=opt.get("default"),
                    )
                )

            spec = CommandSpec(
                cmd=(ext.get("cmd") or "").strip().lower(),
                subcmd=(ext.get("subcmd") or "").strip().lower(),
                options=tuple(option_defs),
                allow_free_text=bool(ext.get("allow_free_text", False)),
                free_text_required=bool(ext.get("free_text_required", False)),
            )
            handler_fn = self._resolve_dotted_callable(ext.get("handler") or "")

            def _wrapped(runtime_handler, parsed, context, _fn=handler_fn):
                return _fn(runtime_handler, parsed, context)

            register_slash_command_extension(
                cmd=spec.cmd,
                subcmd=spec.subcmd,
                handler=_wrapped,
                spec=spec,
                default_subcmd=ext.get("default_subcmd"),
                infer_subcmd_from_options=ext.get("infer_subcmd_from_options") or None,
            )
            self._loaded_slash_extensions.add(key)
            loaded += 1

        return loaded

    def scan_skill(self, name: str, code: str) -> Dict[str, Any]:
        """Scan a skill for security issues.

        Args:
            name: Skill name
            code: Skill source code to scan

        Returns:
            Scan results with risk level
        """
        skill = self.get(name)
        if not skill:
            return {"error": "Skill not found"}

        results = self._security_scanner.scan(code)

        # Update skill security info
        raw_risk = str(results.get("risk", SecurityRisk.LOW.value)).lower()
        try:
            skill.security_risk = SecurityRisk(raw_risk)
        except ValueError:
            skill.security_risk = SecurityRisk.LOW
        skill.security_notes = json.dumps(results.get("findings", []))

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics.

        Returns:
            Dict with counts by status and risk level
        """
        total = len(self._skills)
        by_status: Dict[str, int] = {}
        by_risk: Dict[str, int] = {}

        for skill in self._skills.values():
            by_status[skill.status.value] = by_status.get(skill.status.value, 0) + 1
            by_risk[skill.security_risk.value] = by_risk.get(skill.security_risk.value, 0) + 1

        return {
            "total": total,
            "by_status": by_status,
            "by_risk": by_risk,
        }


# Global registry instance
_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """Get the global SkillRegistry instance."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry

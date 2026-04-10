# -*- coding: utf-8 -*-
"""Skills Hub - Skill registry with security scanning and ClawdHub integration.

Provides a central registry for agent skills with:
- Skill registration and discovery
- Security scanning for prompt injection, credential leakage, etc.
- Skill metadata and version tracking
- ClawdHub integration for external skill packages

Usage:
    from src.nanobot.skills.registry import SkillRegistry, Skill

    registry = SkillRegistry()
    skill = registry.register(
        name="code-review",
        description="Reviews code for bugs",
        handler="src.skills.code_review",
    )
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


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


class SkillSecurityScanner:
    """Scans skills for security issues."""

    # Patterns that indicate potential security issues
    DANGEROUS_PATTERNS = [
        (r"os\.system\s*\(", "Shell command execution via os.system"),
        (r"subprocess\.", "Subprocess execution"),
        (r"eval\s*\(", "Code evaluation via eval"),
        (r"exec\s*\(", "Code execution via exec"),
        (r"pickle\.loads?", "Pickle deserialization"),
        (r"__import__\s*\(", "Dynamic module import"),
        (r"open\s*\([^)]*['\"]w['\"].*\)", "File write operation"),
        (r"requests\.(post|put)\([^)]*auth[^)]*\)", "HTTP auth in requests"),
    ]

    CREDENTIAL_PATTERNS = [
        (r"api[_-]?key\s*=\s*['\"][a-zA-Z0-9]{20,}['\"]", "Hardcoded API key"),
        (r"password\s*=\s*['\"][^'\"]{8,}['\"]", "Hardcoded password"),
        (r"secret\s*=\s*['\"][^'\"]{16,}['\"]", "Hardcoded secret"),
        (r"token\s*=\s*['\"][a-zA-Z0-9_-]{20,}['\"]", "Hardcoded token"),
    ]

    def scan(self, skill_code: str) -> Dict[str, Any]:
        """Scan skill code for security issues.

        Args:
            skill_code: The skill's source code or config

        Returns:
            Dict with risk level and findings
        """
        findings = []
        max_risk = SecurityRisk.LOW

        import re

        # Check dangerous patterns
        for pattern, description in self.DANGEROUS_PATTERNS:
            if re.search(pattern, skill_code):
                findings.append({
                    "pattern": pattern,
                    "description": description,
                    "risk": SecurityRisk.HIGH,
                })
                if max_risk != SecurityRisk.CRITICAL:
                    max_risk = SecurityRisk.HIGH

        # Check credential patterns
        for pattern, description in self.CREDENTIAL_PATTERNS:
            if re.search(pattern, skill_code):
                findings.append({
                    "pattern": pattern,
                    "description": description,
                    "risk": SecurityRisk.CRITICAL,
                })
                max_risk = SecurityRisk.CRITICAL

        return {
            "risk": max_risk,
            "findings": findings,
            "scanned_at": time.time(),
        }


class SkillRegistry:
    """Central registry for agent skills."""

    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._security_scanner = SkillSecurityScanner()
        self._register_default_skills()

    def _register_default_skills(self) -> None:
        """Register default built-in skills."""
        # These are placeholder skills representing core capabilities
        default_skills = [
            Skill(
                name="task-management",
                description="Task creation, assignment, and tracking",
                handler="nanobot.skills.task_management",
                tags=["core", "tasks"],
            ),
            Skill(
                name="code-execution",
                description="Execute code in sandboxed environment",
                handler="nanobot.skills.code_execution",
                tags=["core", "execution"],
                security_risk=SecurityRisk.HIGH,
                security_notes="Requires sandboxing",
            ),
            Skill(
                name="web-search",
                description="Search the web for information",
                handler="nanobot.skills.web_search",
                tags=["core", "search"],
            ),
            Skill(
                name="file-operations",
                description="Read and write files",
                handler="nanobot.skills.file_operations",
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
        skill.security_risk = results["risk"]
        skill.security_notes = json.dumps(results["findings"])

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

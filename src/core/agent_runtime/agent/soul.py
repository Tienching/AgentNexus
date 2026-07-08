# -*- coding: utf-8 -*-
"""Agent SOUL system.

MC-003: Personalized agent identity/configuration with workspace sync.
Capabilities:
- Read SOUL from workspace `soul.md` (preferred) with DB fallback
- Update SOUL with dual-write to workspace + local DB store
- Apply templates with placeholder substitution
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from src.core.stores.sqlite_backend import get_backend


@dataclass
class AgentSoul:
    agent_name: str
    content: str
    source: str  # workspace | database | none
    updated_at: float
    template_name: Optional[str] = None


class AgentSoulStore:
    """SOUL storage and workspace synchronization."""

    def __init__(self, templates_dir: Optional[str] = None):
        self._store = get_backend()
        self._templates_dir = Path(
            templates_dir
            or Path.cwd() / "evolve" / "context" / "soul_templates"
        )

    @staticmethod
    def _workspace_soul_path(workspace: str) -> Path:
        return Path(workspace) / "soul.md"

    @staticmethod
    def _db_key(agent_name: str) -> str:
        return f"agent_soul:{agent_name}"

    def get(self, agent_name: str, workspace: Optional[str] = None) -> AgentSoul:
        """Get SOUL content; workspace file is preferred over DB."""
        if workspace:
            path = self._workspace_soul_path(workspace)
            if path.exists() and path.is_file():
                content = path.read_text(encoding="utf-8")
                return AgentSoul(
                    agent_name=agent_name,
                    content=content,
                    source="workspace",
                    updated_at=path.stat().st_mtime,
                )

        db_obj = self._store.get(self._db_key(agent_name))
        if isinstance(db_obj, dict) and db_obj.get("content"):
            return AgentSoul(
                agent_name=agent_name,
                content=str(db_obj.get("content", "")),
                source="database",
                updated_at=float(db_obj.get("updated_at") or time.time()),
                template_name=str(db_obj.get("template_name")) if db_obj.get("template_name") else None,
            )

        return AgentSoul(
            agent_name=agent_name,
            content="",
            source="none",
            updated_at=time.time(),
        )

    def set(
        self,
        agent_name: str,
        content: str,
        workspace: Optional[str] = None,
        template_name: Optional[str] = None,
    ) -> AgentSoul:
        """Persist SOUL to DB and best-effort write to workspace soul.md."""
        now = time.time()
        payload = {
            "agent_name": agent_name,
            "content": content,
            "template_name": template_name,
            "updated_at": now,
        }
        self._store.set(self._db_key(agent_name), payload)

        source = "database"
        if workspace:
            path = self._workspace_soul_path(workspace)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            source = "workspace"

        return AgentSoul(
            agent_name=agent_name,
            content=content,
            source=source,
            updated_at=now,
            template_name=template_name,
        )

    def list_templates(self) -> List[str]:
        """List available SOUL template names (without .md suffix)."""
        if not self._templates_dir.exists() or not self._templates_dir.is_dir():
            return []
        names: List[str] = []
        for f in self._templates_dir.glob("*.md"):
            names.append(f.stem)
        return sorted(names)

    def load_template(self, template_name: str) -> str:
        """Load template raw content by name."""
        path = self._templates_dir / f"{template_name}.md"
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"SOUL template not found: {template_name}")
        return path.read_text(encoding="utf-8")

    def apply_template(
        self,
        agent_name: str,
        template_name: str,
        role: str = "agent",
        workspace: Optional[str] = None,
    ) -> AgentSoul:
        """Apply template placeholders and persist resulting SOUL."""
        raw = self.load_template(template_name)
        rendered = (
            raw.replace("{{AGENT_NAME}}", agent_name)
            .replace("{{AGENT_ROLE}}", role)
            .replace("{{TIMESTAMP}}", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        )
        return self.set(
            agent_name=agent_name,
            content=rendered,
            workspace=workspace,
            template_name=template_name,
        )


_store: Optional[AgentSoulStore] = None


def get_soul_store() -> AgentSoulStore:
    global _store
    if _store is None:
        _store = AgentSoulStore()
    return _store

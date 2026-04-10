# -*- coding: utf-8 -*-
"""Feature Flag Service — runtime feature gating for Agent Nexus.

Inspired by Claude Code's two-layer Feature Flag system (ch38.md):
  - Compile-time flags → not applicable (Python is interpreted), but we
    approximate with module-level conditional imports where needed.
  - Runtime flags → this module implements a 4-layer resolution chain:

Resolution chain (highest priority first):
  1. Environment variable overrides  (NEXUS_FEATURE_OVERRIDES, JSON)
  2. Database overrides              (SQLite feature_flags table)
  3. Config-file defaults            (FeatureFlagSettings in ServerSettings)
  4. Code defaults                   (BUILTIN_FLAGS registry)

Usage:
    from src.server.services.feature_flags import is_feature_enabled, get_feature_value

    if is_feature_enabled("persistent_cli"):
        ...  # enable persistent CLI feature

    value = get_feature_value("max_parallel_tools", default=5)
"""

from __future__ import annotations

import json
import logging
import os
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Flag categories ──────────────────────────────────────────────────────────

class FlagCategory(str, Enum):
    """Feature flag categories for UI grouping."""
    CAPABILITY = "capability"   # Experimental capabilities
    TOOL = "tool"               # Tool-level gating
    UI = "ui"                   # UI panel / component gating
    INTEGRATION = "integration" # External integrations
    PERFORMANCE = "performance" # Performance-related toggles


class FlagType(str, Enum):
    """Feature flag value types."""
    BOOLEAN = "boolean"
    STRING = "string"
    NUMBER = "number"
    JSON = "json"


# ── Flag definition ──────────────────────────────────────────────────────────

class FlagDefinition(BaseModel):
    """Defines a feature flag and its default value."""
    name: str
    description: str
    category: FlagCategory = FlagCategory.CAPABILITY
    flag_type: FlagType = FlagType.BOOLEAN
    default_value: Any = True
    stable: bool = False  # If True, flag is considered production-stable


# ── Builtin flags registry ───────────────────────────────────────────────────

BUILTIN_FLAGS: Dict[str, FlagDefinition] = {
    "persistent_cli": FlagDefinition(
        name="persistent_cli",
        description="Persistent CLI process mode — keep CLI alive across messages via stdin streaming",
        category=FlagCategory.CAPABILITY,
        flag_type=FlagType.BOOLEAN,
        default_value=False,
    ),
    "evolution_mode": FlagDefinition(
        name="evolution_mode",
        description="Self-evolution system — enable scheduled autonomous improvement tasks",
        category=FlagCategory.CAPABILITY,
        flag_type=FlagType.BOOLEAN,
        default_value=False,
    ),
    "dag_message_chains": FlagDefinition(
        name="dag_message_chains",
        description="DAG-based message chains — store parentUuid links for conversation branching",
        category=FlagCategory.CAPABILITY,
        flag_type=FlagType.BOOLEAN,
        default_value=False,
    ),
    "interrupted_turn_recovery": FlagDefinition(
        name="interrupted_turn_recovery",
        description="Interrupted turn recovery — resume from interrupted_prompt/interrupted_turn markers",
        category=FlagCategory.CAPABILITY,
        flag_type=FlagType.BOOLEAN,
        default_value=False,
    ),
    "parallel_tool_completion": FlagDefinition(
        name="parallel_tool_completion",
        description="Parallel tool result completion — re-attach orphaned parallel tool results",
        category=FlagCategory.CAPABILITY,
        flag_type=FlagType.BOOLEAN,
        default_value=False,
    ),
    "observability_pipeline": FlagDefinition(
        name="observability_pipeline",
        description="Unified observability pipeline — structured telemetry, metrics, event sampling",
        category=FlagCategory.PERFORMANCE,
        flag_type=FlagType.BOOLEAN,
        default_value=False,
    ),
    "cost_metrics": FlagDefinition(
        name="cost_metrics",
        description="Cost tracking — per-session and per-provider token/cost metrics",
        category=FlagCategory.PERFORMANCE,
        flag_type=FlagType.BOOLEAN,
        default_value=False,
    ),
    "advanced_tool_search": FlagDefinition(
        name="advanced_tool_search",
        description="Advanced tool search — smarter tool discovery and selection for LLM",
        category=FlagCategory.TOOL,
        flag_type=FlagType.BOOLEAN,
        default_value=False,
    ),
    "mcp_dynamic_tools": FlagDefinition(
        name="mcp_dynamic_tools",
        description="MCP dynamic tool loading — runtime tool registration from MCP servers",
        category=FlagCategory.TOOL,
        flag_type=FlagType.BOOLEAN,
        default_value=True,
        stable=True,
    ),
    "kanban_ui": FlagDefinition(
        name="kanban_ui",
        description="Kanban board UI panel — visual task management interface",
        category=FlagCategory.UI,
        flag_type=FlagType.BOOLEAN,
        default_value=True,
        stable=True,
    ),
    "agent_lifecycle_panel": FlagDefinition(
        name="agent_lifecycle_panel",
        description="Agent lifecycle management panel — registration, heartbeat, status",
        category=FlagCategory.UI,
        flag_type=FlagType.BOOLEAN,
        default_value=False,
    ),
    "quality_gates": FlagDefinition(
        name="quality_gates",
        description="Aegis quality gate system — task completion quality review",
        category=FlagCategory.CAPABILITY,
        flag_type=FlagType.BOOLEAN,
        default_value=False,
    ),
    "skill_security_scanner": FlagDefinition(
        name="skill_security_scanner",
        description="Skill security scanner — detect prompt injection, credential leaks",
        category=FlagCategory.INTEGRATION,
        flag_type=FlagType.BOOLEAN,
        default_value=False,
    ),
    "nlp_cron_parser": FlagDefinition(
        name="nlp_cron_parser",
        description="Natural language cron parser — 'every day at 9am' → cron expression",
        category=FlagCategory.CAPABILITY,
        flag_type=FlagType.BOOLEAN,
        default_value=False,
    ),
    "max_parallel_tools": FlagDefinition(
        name="max_parallel_tools",
        description="Maximum number of parallel tool calls per turn (0=unlimited)",
        category=FlagCategory.TOOL,
        flag_type=FlagType.NUMBER,
        default_value=0,
    ),
}


# ── Feature Flag Service ─────────────────────────────────────────────────────

class FeatureFlagService:
    """Singleton service for runtime feature flag evaluation.

    Resolution chain (highest priority first):
      1. Environment variable overrides (NEXUS_FEATURE_OVERRIDES)
      2. Database overrides (SQLite feature_flags table)
      3. Config-file defaults (ServerSettings.feature_flags_*)
      4. Code defaults (BUILTIN_FLAGS registry)
    """

    _instance: Optional["FeatureFlagService"] = None

    def __new__(cls) -> "FeatureFlagService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._env_overrides: Dict[str, Any] = {}
        self._db_overrides: Dict[str, Any] = {}
        self._config_overrides: Dict[str, Any] = {}
        self._loaded_db = False
        self._initialized = True
        self._load_env_overrides()

    # ── Layer 1: Environment variable overrides ──────────────────────────

    def _load_env_overrides(self) -> None:
        """Load NEXUS_FEATURE_OVERRIDES from environment (JSON format)."""
        raw = os.environ.get("NEXUS_FEATURE_OVERRIDES", "").strip()
        if not raw:
            return
        try:
            overrides = json.loads(raw)
            if isinstance(overrides, dict):
                self._env_overrides = overrides
                logger.info(f"Loaded {len(overrides)} feature flag overrides from env")
            else:
                logger.warning("NEXUS_FEATURE_OVERRIDES must be a JSON object")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse NEXUS_FEATURE_OVERRIDES: {e}")

    # ── Layer 2: Database overrides ──────────────────────────────────────

    def _load_db_overrides(self) -> None:
        """Load feature flag overrides from SQLite."""
        if self._loaded_db:
            return
        try:
            from src.runtime.stores.db import get_db
            db = get_db()
            rows = db.execute_fetchall("SELECT name, value_json FROM feature_flags")
            for row in rows:
                try:
                    self._db_overrides[row["name"]] = json.loads(row["value_json"])
                except (json.JSONDecodeError, KeyError):
                    continue
            self._loaded_db = True
            logger.debug(f"Loaded {len(self._db_overrides)} feature flag overrides from DB")
        except Exception as e:
            logger.debug(f"Feature flag DB load skipped: {e}")
            self._loaded_db = True  # Don't keep retrying

    def _save_db_override(self, name: str, value: Any, updated_by: str = "") -> bool:
        """Persist a single flag override to SQLite."""
        try:
            from src.runtime.stores.db import get_db
            db = get_db()
            value_json = json.dumps(value, ensure_ascii=False)
            with db.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO feature_flags (name, value_json, updated_by, updated_at) VALUES (?, ?, ?, ?)",
                    (name, value_json, updated_by, time.time()),
                )
            self._db_overrides[name] = value
            return True
        except Exception as e:
            logger.error(f"Failed to save feature flag override: {e}")
            return False

    def _delete_db_override(self, name: str) -> bool:
        """Remove a single flag override from SQLite."""
        try:
            from src.runtime.stores.db import get_db
            db = get_db()
            with db.transaction() as conn:
                conn.execute("DELETE FROM feature_flags WHERE name = ?", (name,))
            self._db_overrides.pop(name, None)
            return True
        except Exception as e:
            logger.error(f"Failed to delete feature flag override: {e}")
            return False

    # ── Layer 3: Config-file defaults ────────────────────────────────────

    def set_config_overrides(self, overrides: Dict[str, Any]) -> None:
        """Set config-layer overrides from ServerSettings.

        Called once during app startup from the settings model.
        """
        self._config_overrides = {k: v for k, v in overrides.items() if v is not None}

    # ── Public API ───────────────────────────────────────────────────────

    def is_enabled(self, name: str, default: bool = False) -> bool:
        """Check if a boolean feature flag is enabled.

        Uses the full resolution chain:
          env > db > config > builtin default > default param
        """
        value = self.get_value(name, default=default)
        return bool(value)

    def get_value(self, name: str, default: Any = None) -> Any:
        """Get the resolved value of a feature flag.

        Resolution: env > db > config > builtin > default param
        """
        # Layer 1: Environment variable override
        if name in self._env_overrides:
            return self._env_overrides[name]

        # Layer 2: Database override
        self._load_db_overrides()
        if name in self._db_overrides:
            return self._db_overrides[name]

        # Layer 3: Config-file override
        if name in self._config_overrides:
            return self._config_overrides[name]

        # Layer 4: Builtin default
        if name in BUILTIN_FLAGS:
            return BUILTIN_FLAGS[name].default_value

        # Fallback
        return default

    def set_override(self, name: str, value: Any, updated_by: str = "api") -> bool:
        """Set a runtime override for a flag (persisted to DB).

        Returns True if saved successfully.
        """
        # Validate flag exists
        if name not in BUILTIN_FLAGS:
            logger.warning(f"Setting override for unknown flag: {name}")

        return self._save_db_override(name, value, updated_by=updated_by)

    def reset_override(self, name: str) -> bool:
        """Remove a DB override so the flag falls back to its default."""
        return self._delete_db_override(name)

    def list_flags(self) -> List[Dict[str, Any]]:
        """List all flags with their current resolved values and metadata."""
        self._load_db_overrides()
        result = []
        for name, flag_def in sorted(BUILTIN_FLAGS.items()):
            resolved = self.get_value(name)
            has_db_override = name in self._db_overrides
            has_env_override = name in self._env_overrides
            has_config_override = name in self._config_overrides
            result.append({
                "name": name,
                "description": flag_def.description,
                "category": flag_def.category.value,
                "flag_type": flag_def.flag_type.value,
                "default_value": flag_def.default_value,
                "value": resolved,
                "source": (
                    "env_override" if has_env_override else
                    "db_override" if has_db_override else
                    "config" if has_config_override else
                    "default"
                ),
                "stable": flag_def.stable,
                "overridden": has_db_override or has_env_override or has_config_override,
            })
        return result

    def get_flag(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a single flag's resolved info."""
        if name not in BUILTIN_FLAGS:
            return None
        flags = self.list_flags()
        for f in flags:
            if f["name"] == name:
                return f
        return None

    def reload(self) -> None:
        """Force reload DB overrides (useful after external changes)."""
        self._db_overrides.clear()
        self._loaded_db = False
        self._load_env_overrides()
        self._load_db_overrides()

    @classmethod
    def reset_singleton(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None


# ── Module-level convenience functions ────────────────────────────────────────

def is_feature_enabled(name: str, default: bool = False) -> bool:
    """Quick check if a boolean feature flag is enabled."""
    return FeatureFlagService().is_enabled(name, default=default)


def get_feature_value(name: str, default: Any = None) -> Any:
    """Get the resolved value of a feature flag."""
    return FeatureFlagService().get_value(name, default=default)


def get_feature_flag_service() -> FeatureFlagService:
    """Get the FeatureFlagService singleton."""
    return FeatureFlagService()

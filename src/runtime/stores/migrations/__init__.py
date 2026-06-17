# -*- coding: utf-8 -*-
"""SQLite schema migration package.

Each migration module in this package must define:
  - VERSION: int  (sequential, starting at 1)
  - NAME: str     (human-readable description)
  - up(conn): callable  (receives a sqlite3.Connection)

Migrations are applied in version order, tracked in ``_schema_version`` table.
Discovery is strict by default: missing or malformed modules raise immediately
so the application cannot continue with an incomplete migration registry.
"""

from __future__ import annotations

import importlib
import logging
from types import ModuleType
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Registry of migration modules (ordered by version)
_MIGRATION_MODULES = [
    "src.runtime.stores.migrations.v001_initial_kv_tables",
    "src.runtime.stores.migrations.v002_schedule_tables",
    "src.runtime.stores.migrations.v003_task_tables",
    "src.runtime.stores.migrations.v004_session_tables",
    "src.runtime.stores.migrations.v005_run_tables",
    "src.runtime.stores.migrations.v006_feature_flag_tables",
    "src.runtime.stores.migrations.v007_task_workflow_columns",
    "src.runtime.stores.migrations.v008_activities_table",
    "src.runtime.stores.migrations.v009_security_tables",
    "src.runtime.stores.migrations.v010_quality_reviews_table",
    "src.runtime.stores.migrations.v011_task_runtime_state_columns",
    "src.runtime.stores.migrations.v012_schedule_durability_and_lock",
    "src.runtime.stores.migrations.v013_migrate_task_statuses",
    "src.runtime.stores.migrations.v014_execution_bindings",
    "src.runtime.stores.migrations.v015_session_task_id_column",
    "src.runtime.stores.migrations.v016_task_lifecycle_guards",
    "src.runtime.stores.migrations.v017_netharness_statuses",
    "src.runtime.stores.migrations.v018_agent_templates",
    "src.runtime.stores.migrations.v019_control_plane_group_workspace",
    "src.runtime.stores.migrations.v020_control_plane_group_workspace_maintenance",
    "src.runtime.stores.migrations.v021_runtime_daemon_triple_key",
    "src.runtime.stores.migrations.v022_runtime_daemon_mode",
]


class MigrationDiscoveryError(RuntimeError):
    """Raised when the migration registry cannot be loaded safely."""


def _load_migration_module(module_path: str) -> ModuleType:
    """Import a migration module or raise a descriptive discovery error."""
    try:
        return importlib.import_module(module_path)
    except Exception as exc:  # pragma: no cover - exercised via tests/mocks
        raise MigrationDiscoveryError(
            f"Failed to import migration module {module_path}: {exc}"
        ) from exc


def _build_descriptor(module_path: str, mod: ModuleType) -> Dict[str, Any]:
    """Validate a migration module and convert it into a descriptor."""
    missing = [attr for attr in ("VERSION", "NAME", "up") if not hasattr(mod, attr)]
    if missing:
        raise MigrationDiscoveryError(
            f"Invalid migration module {module_path}: missing {', '.join(missing)}"
        )

    version = getattr(mod, "VERSION")
    name = getattr(mod, "NAME")
    up = getattr(mod, "up")

    if not isinstance(version, int) or version <= 0:
        raise MigrationDiscoveryError(
            f"Invalid migration module {module_path}: VERSION must be a positive integer"
        )
    if not isinstance(name, str) or not name.strip():
        raise MigrationDiscoveryError(
            f"Invalid migration module {module_path}: NAME must be a non-empty string"
        )
    if not callable(up):
        raise MigrationDiscoveryError(
            f"Invalid migration module {module_path}: up must be callable"
        )

    return {
        "version": version,
        "name": name,
        "up": up,
    }


def get_all_migrations(strict: bool = True) -> List[Dict[str, Any]]:
    """Load and return all migration descriptors sorted by version.

    When ``strict`` is true, any import/validation problem raises
    :class:`MigrationDiscoveryError`.
    """
    migrations = []
    for module_path in _MIGRATION_MODULES:
        try:
            migrations.append(_build_descriptor(module_path, _load_migration_module(module_path)))
        except MigrationDiscoveryError:
            if strict:
                raise
            logger.exception("Migration module could not be loaded: %s", module_path)

    ordered = sorted(migrations, key=lambda m: m["version"])
    versions = [int(m["version"]) for m in ordered]
    if len(set(versions)) != len(versions):
        raise MigrationDiscoveryError(f"Duplicate migration versions detected: {versions}")
    if versions and versions != list(range(1, len(versions) + 1)):
        raise MigrationDiscoveryError(
            f"Migration versions must be contiguous starting at 1; got {versions}"
        )
    return ordered

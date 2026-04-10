# -*- coding: utf-8 -*-
"""SQLite schema migration package.

Each migration module in this package must define:
  - VERSION: int  (sequential, starting at 1)
  - NAME: str     (human-readable description)
  - up(conn): callable  (receives a sqlite3.Connection)

Migrations are applied in version order, tracked in ``_schema_version`` table.
"""

from __future__ import annotations

import importlib
import logging
from typing import List, Dict, Any

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
]


def get_all_migrations() -> List[Dict[str, Any]]:
    """Load and return all migration descriptors sorted by version."""
    migrations = []
    for module_path in _MIGRATION_MODULES:
        try:
            mod = importlib.import_module(module_path)
            migrations.append({
                "version": mod.VERSION,
                "name": mod.NAME,
                "up": mod.up,
            })
        except ImportError as e:
            logger.debug(f"Migration module not loaded: {module_path} ({e})")
        except AttributeError as e:
            logger.warning(f"Invalid migration module {module_path}: {e}")
    return sorted(migrations, key=lambda m: m["version"])

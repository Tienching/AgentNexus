# -*- coding: utf-8 -*-
"""User-level config storage

Stores per-user preferences in SQLite for slash /config.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from .db import Database, get_db

logger = logging.getLogger(__name__)

ALLOWED_USER_CONFIG_KEYS = {"provider", "exec_user", "alias"}


def normalize_config_key(key: str) -> str:
    normalized = (key or "").strip().lower()
    return normalized


class UserConfigStore:
    """User-level config stored in SQLite."""

    def __init__(self, db: Optional[Database] = None):
        self._db = db or get_db()

    def get_all(self, user_id: str) -> Dict[str, str]:
        if not user_id:
            return {}
        try:
            rows = self._db.execute_fetchall(
                "SELECT key, value FROM user_config WHERE user_id = ?",
                (user_id,),
            )
            out: Dict[str, str] = {}
            for row in rows:
                nk = normalize_config_key(row["key"])
                if nk in {"provider", "exec_user", "alias"}:
                    out[nk] = (row["value"] or "").strip()
            return out
        except Exception as e:
            logger.error(f"Failed to get user config: {e}")
            return {}

    def set(self, user_id: str, key: str, value: str) -> bool:
        if not user_id:
            raise ValueError("missing user_id")
        raw_key = (key or "").strip().lower()
        if raw_key not in ALLOWED_USER_CONFIG_KEYS:
            raise ValueError(f"unsupported key: {key}")
        normalized = normalize_config_key(raw_key)
        if normalized not in {"provider", "exec_user", "alias"}:
            raise ValueError(f"unsupported key: {key}")
        val = (value or "").strip()
        if not val:
            raise ValueError("value cannot be empty")
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO user_config (user_id, key, value) VALUES (?, ?, ?)",
                    (user_id, normalized, val),
                )
            return True
        except Exception as e:
            logger.error(f"Failed to set user config: {e}")
            return False

    def reset(self, user_id: str) -> bool:
        if not user_id:
            return False
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM user_config WHERE user_id = ?", (user_id,))
            return True
        except Exception as e:
            logger.error(f"Failed to reset user config: {e}")
            return False

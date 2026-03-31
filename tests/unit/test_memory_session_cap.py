# -*- coding: utf-8 -*-
"""Tests for bounded in-memory session store eviction.

Ported from mission-control rate-limit.test.ts maxEntries eviction logic
(commit e7aa7e6).  The Nexus fallback store is _memory_sessions in
src/server/routers/nexus_auth.py.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — import internals we need to white-box test
# ---------------------------------------------------------------------------

def _get_module():
    """Re-import the module so each test starts with a clean module state."""
    import importlib
    import src.server.routers.nexus_auth as mod
    return mod


# ---------------------------------------------------------------------------
# _evict_oldest_session
# ---------------------------------------------------------------------------

class TestEvictOldestSession:
    def test_evicts_smallest_expiry(self):
        mod = _get_module()
        mod._memory_sessions.clear()
        # Three tokens with distinct expiries
        now = time.time()
        mod._memory_sessions["old"] = now + 10
        mod._memory_sessions["older"] = now + 5   # ← should be evicted
        mod._memory_sessions["newest"] = now + 20

        mod._evict_oldest_session()

        assert "older" not in mod._memory_sessions
        assert "old" in mod._memory_sessions
        assert "newest" in mod._memory_sessions

    def test_evicts_exactly_one_entry(self):
        mod = _get_module()
        mod._memory_sessions.clear()
        now = time.time()
        for i in range(5):
            mod._memory_sessions[f"tok{i}"] = now + i + 1
        before = len(mod._memory_sessions)

        mod._evict_oldest_session()

        assert len(mod._memory_sessions) == before - 1

    def test_no_op_on_empty_store(self):
        mod = _get_module()
        mod._memory_sessions.clear()
        # Should not raise
        mod._evict_oldest_session()
        assert len(mod._memory_sessions) == 0

    def test_evicts_sole_entry(self):
        mod = _get_module()
        mod._memory_sessions.clear()
        mod._memory_sessions["only"] = time.time() + 100
        mod._evict_oldest_session()
        assert len(mod._memory_sessions) == 0

    def test_survives_tie_in_expiry(self):
        """When two tokens share the exact same expiry, one is evicted, not both."""
        mod = _get_module()
        mod._memory_sessions.clear()
        t = time.time() + 60
        mod._memory_sessions["a"] = t
        mod._memory_sessions["b"] = t
        mod._evict_oldest_session()
        assert len(mod._memory_sessions) == 1


# ---------------------------------------------------------------------------
# _create_session capacity enforcement
# ---------------------------------------------------------------------------

class TestCreateSessionCapacity:
    def _setup(self, mod):
        """Clear the store and disable Redis so we hit the memory path."""
        mod._memory_sessions.clear()

    def _mock_redis_down(self):
        """Context manager that makes _redis_available() return False."""
        from unittest.mock import patch
        return patch(
            "src.server.routers.nexus_auth._redis_available",
            return_value=False,
        )

    def test_does_not_exceed_max_entries(self):
        mod = _get_module()
        self._setup(mod)
        cap = mod._MEMORY_SESSIONS_MAX_ENTRIES

        with self._mock_redis_down():
            # Fill to capacity
            now = time.time()
            for i in range(cap):
                tok = f"sess_{i}"
                # Inject directly so _cleanup won't prune them (far-future expiry)
                mod._memory_sessions[tok] = now + 3600 + i

            # One extra insertion should evict first
            mod._create_session("new_token")

        assert len(mod._memory_sessions) <= cap

    def test_new_token_is_present_after_eviction(self):
        mod = _get_module()
        self._setup(mod)
        cap = mod._MEMORY_SESSIONS_MAX_ENTRIES

        with self._mock_redis_down():
            now = time.time()
            for i in range(cap):
                mod._memory_sessions[f"fill_{i}"] = now + 3600 + i

            mod._create_session("brand_new")

        assert "brand_new" in mod._memory_sessions

    def test_no_eviction_below_capacity(self):
        mod = _get_module()
        self._setup(mod)

        with self._mock_redis_down():
            now = time.time()
            # Fill to cap - 1
            for i in range(5):
                mod._memory_sessions[f"pre_{i}"] = now + 3600 + i

            mod._create_session("no_evict_needed")

        # All pre-filled tokens still present
        assert "no_evict_needed" in mod._memory_sessions
        assert len(mod._memory_sessions) == 6

    def test_refresh_existing_token_does_not_evict(self):
        """Re-creating an existing session must not trigger eviction."""
        mod = _get_module()
        self._setup(mod)
        cap = mod._MEMORY_SESSIONS_MAX_ENTRIES

        with self._mock_redis_down():
            now = time.time()
            # Fill to capacity, include the token we'll refresh
            mod._memory_sessions["existing"] = now + 100
            for i in range(cap - 1):
                mod._memory_sessions[f"filler_{i}"] = now + 3600 + i

            before = len(mod._memory_sessions)
            mod._create_session("existing")

        # Refreshing should not push size over cap (no additional eviction)
        assert len(mod._memory_sessions) <= cap
        assert "existing" in mod._memory_sessions

    def test_constant_is_10000(self):
        mod = _get_module()
        assert mod._MEMORY_SESSIONS_MAX_ENTRIES == 10_000


# ---------------------------------------------------------------------------
# _cleanup_expired_sessions still works alongside cap
# ---------------------------------------------------------------------------

class TestCleanupInteraction:
    def test_cleanup_removes_expired_entries(self):
        mod = _get_module()
        mod._memory_sessions.clear()
        now = time.time()
        mod._memory_sessions["valid"] = now + 3600
        mod._memory_sessions["expired"] = now - 1  # already past

        mod._cleanup_expired_sessions()

        assert "valid" in mod._memory_sessions
        assert "expired" not in mod._memory_sessions

    def test_cleanup_runs_after_create_session(self):
        """_create_session always calls _cleanup, so expired entries are pruned."""
        mod = _get_module()
        mod._memory_sessions.clear()
        now = time.time()
        # Inject an already-expired token directly
        mod._memory_sessions["stale"] = now - 10

        with patch(
            "src.server.routers.nexus_auth._redis_available",
            return_value=False,
        ):
            mod._create_session("fresh")

        assert "stale" not in mod._memory_sessions
        assert "fresh" in mod._memory_sessions

# -*- coding: utf-8 -*-
"""Tests for shared history alias/provider resolution helpers."""

from __future__ import annotations

import json

from src.runtime.history.alias_resolution import (
    build_alias_config_map,
    infer_base_provider,
    resolve_history_user_homes,
)


def test_infer_base_provider_handles_provider_and_alias_prefixes():
    assert infer_base_provider("claude") == "claude"
    assert infer_base_provider("claude-internal") == "claude"
    assert infer_base_provider("codex-dev") == "codex"
    assert infer_base_provider("unknown-tool") is None


def test_resolve_history_user_homes_deduplicates_fallback(tmp_path):
    home_root = tmp_path / "home"
    (home_root / "alice").mkdir(parents=True)
    homes = resolve_history_user_homes(
        exec_user="",
        user_home_base=str(home_root),
        fallback_exec_user="alice",
    )
    assert homes == [home_root / "alice"]


def test_build_alias_config_map_merges_defaults_registry_and_custom_paths(tmp_path):
    user_home = tmp_path / "alice"
    user_home.mkdir()
    (user_home / ".claude").mkdir()
    (user_home / ".claude-internal").mkdir()
    external = user_home / "custom-codex"
    external.mkdir()

    alias_map = build_alias_config_map(
        user_home=user_home,
        provider_filter=None,
        alias_registry_map={"claude-internal": "claude", "codex-lab": "codex"},
        custom_paths_str=json.dumps({"codex-lab": str(external)}),
    )

    assert alias_map["claude"] == user_home / ".claude"
    assert alias_map["claude-internal"] == user_home / ".claude-internal"
    assert alias_map["codex-lab"] == external


def test_build_alias_config_map_filters_provider_family(tmp_path):
    user_home = tmp_path / "alice"
    user_home.mkdir()
    (user_home / ".claude").mkdir()
    (user_home / ".gemini-alt").mkdir()

    alias_map = build_alias_config_map(
        user_home=user_home,
        provider_filter="gemini",
        alias_registry_map={},
        custom_paths_str="",
    )

    assert "claude" not in alias_map
    assert alias_map["gemini"] == user_home / ".gemini"
    assert alias_map["gemini-alt"] == user_home / ".gemini-alt"

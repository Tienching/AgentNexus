# -*- coding: utf-8 -*-
from __future__ import annotations

from src.server.services.workspace_validation import normalize_workspace_path


def test_normalize_workspace_path_accepts_existing_absolute_directory(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()

    assert normalize_workspace_path(str(workspace)) == str(workspace.resolve())


def test_normalize_workspace_path_resolves_relative_directory_against_base(tmp_path):
    base = tmp_path / "root"
    base.mkdir()
    workspace = base / "ws1"
    workspace.mkdir()

    assert normalize_workspace_path("ws1", base_dir=base) == str(workspace.resolve())


def test_normalize_workspace_path_rejects_missing_directory(tmp_path):
    missing = tmp_path / "missing"

    try:
        normalize_workspace_path(str(missing))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "workspace 不存在或不是目录" in str(exc)

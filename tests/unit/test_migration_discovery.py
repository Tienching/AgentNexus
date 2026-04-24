# -*- coding: utf-8 -*-
"""Tests for strict migration discovery and validation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.runtime.stores.migrations import (
    MigrationDiscoveryError,
    get_all_migrations,
)


def test_get_all_migrations_raises_on_import_error(monkeypatch):
    monkeypatch.setattr(
        "src.runtime.stores.migrations._MIGRATION_MODULES",
        ["fake.bad.module"],
    )

    def _boom(_path: str):
        raise ImportError("boom")

    monkeypatch.setattr("importlib.import_module", _boom)

    with pytest.raises(MigrationDiscoveryError, match="fake.bad.module"):
        get_all_migrations()


def test_get_all_migrations_raises_on_missing_required_attrs(monkeypatch):
    monkeypatch.setattr(
        "src.runtime.stores.migrations._MIGRATION_MODULES",
        ["fake.missing.attrs"],
    )
    monkeypatch.setattr("importlib.import_module", lambda _path: SimpleNamespace(VERSION=1, NAME="oops"))

    with pytest.raises(MigrationDiscoveryError, match="missing up"):
        get_all_migrations()


def test_get_all_migrations_raises_on_duplicate_versions(monkeypatch):
    monkeypatch.setattr(
        "src.runtime.stores.migrations._MIGRATION_MODULES",
        ["fake.one", "fake.two"],
    )

    modules = {
        "fake.one": SimpleNamespace(VERSION=1, NAME="one", up=lambda conn: None),
        "fake.two": SimpleNamespace(VERSION=1, NAME="two", up=lambda conn: None),
    }
    monkeypatch.setattr("importlib.import_module", lambda path: modules[path])

    with pytest.raises(MigrationDiscoveryError, match="Duplicate migration versions"):
        get_all_migrations()

# -*- coding: utf-8 -*-
"""Tests for Database instance scoping."""

from __future__ import annotations

from src.runtime.stores.db import Database, get_db


def teardown_function():
    Database.reset_instances()


def test_get_db_reuses_instance_per_path(tmp_path):
    path_a = str(tmp_path / "a.db")
    path_b = str(tmp_path / "b.db")

    db1 = get_db(path_a)
    db2 = get_db(path_a)
    db3 = get_db(path_b)

    assert db1 is db2
    assert db1 is not db3
    assert db1.db_path == path_a
    assert db3.db_path == path_b


def test_legacy_instance_reset_still_forces_fresh_db(tmp_path, monkeypatch):
    path_a = str(tmp_path / "legacy-a.db")
    monkeypatch.setenv("NEXUS_DB_PATH", path_a)
    db1 = get_db()

    Database._instance = None

    path_b = str(tmp_path / "legacy-b.db")
    monkeypatch.setenv("NEXUS_DB_PATH", path_b)
    db2 = get_db()

    assert db1 is not db2
    assert db2.db_path == path_b

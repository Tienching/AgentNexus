# -*- coding: utf-8 -*-
"""Tests for docs freshness guard."""

from __future__ import annotations

from scripts.check_docs_freshness import main


def test_docs_freshness_passes_when_no_ui_files(monkeypatch):
    monkeypatch.setattr(
        "scripts.check_docs_freshness._changed_files",
        lambda base, head: ["src/runtime/stores/db.py"],
    )
    assert main(["check_docs_freshness.py", "base", "head"]) == 0


def test_docs_freshness_fails_when_ui_changes_have_no_docs(monkeypatch):
    monkeypatch.setattr(
        "scripts.check_docs_freshness._changed_files",
        lambda base, head: ["src/server/static/nexus/js/app.js"],
    )
    assert main(["check_docs_freshness.py", "base", "head"]) == 1


def test_docs_freshness_passes_when_ui_and_docs_change(monkeypatch):
    monkeypatch.setattr(
        "scripts.check_docs_freshness._changed_files",
        lambda base, head: [
            "src/server/static/nexus/js/app.js",
            "docs/history-ui.md",
        ],
    )
    assert main(["check_docs_freshness.py", "base", "head"]) == 0

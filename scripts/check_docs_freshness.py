#!/usr/bin/env python3
"""Warn/fail when UI changes land without companion docs or screenshot updates.

This is a lightweight substitute for screenshot-drift tooling: if frontend
surface files changed but no docs/release/readme/screenshot assets moved with
them, the workflow asks the author to confirm documentation freshness.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


UI_PREFIXES = (
    "src/server/static/nexus/",
)
DOC_PREFIXES = (
    "README",
    "docs/",
    "CHANGELOG.md",
    "RELEASE.md",
)
SCREENSHOT_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _changed_files(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}..{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_ui_file(path: str) -> bool:
    return path.startswith(UI_PREFIXES)


def _is_doc_file(path: str) -> bool:
    p = Path(path)
    return path.startswith(DOC_PREFIXES) or p.suffix.lower() in SCREENSHOT_EXTS


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: check_docs_freshness.py <base-ref> <head-ref>", file=sys.stderr)
        return 2

    base, head = argv[1], argv[2]
    changed = _changed_files(base, head)
    ui_changes = [path for path in changed if _is_ui_file(path)]
    if not ui_changes:
        print("No Nexus UI changes detected; docs freshness check skipped.")
        return 0

    doc_changes = [path for path in changed if _is_doc_file(path)]
    if doc_changes:
        print("UI and docs changed together; docs freshness check passed.")
        return 0

    print("Detected Nexus UI changes without companion docs/screenshot updates:", file=sys.stderr)
    for path in ui_changes:
        print(f"  - {path}", file=sys.stderr)
    print(
        "\nPlease update README/docs/release notes (and screenshots if needed), "
        "or intentionally amend the PR with a docs note.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

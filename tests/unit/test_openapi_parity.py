# -*- coding: utf-8 -*-
"""Regression test to keep generated OpenAPI spec in sync with docs artifact."""

from __future__ import annotations

import json
from pathlib import Path

from src.core.openapi_generator import generate_openapi_spec


def test_docs_openapi_json_matches_generated_spec():
    docs_path = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
    with docs_path.open() as fh:
        docs_spec = json.load(fh)

    assert docs_spec == generate_openapi_spec()

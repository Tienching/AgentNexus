from __future__ import annotations

import ast
import configparser
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
PYTEST_INI_PATH = REPO_ROOT / "pytest.ini"


def _read_section(text: str, name: str) -> str:
    match = re.search(
        rf"^\[{re.escape(name)}\]\n(?P<body>.*?)(?=^\[|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"Missing [{name}] section"
    return match.group("body")


def _read_string(body: str, key: str) -> str:
    match = re.search(rf'^\s*{re.escape(key)}\s*=\s*"([^"]+)"\s*$', body, re.MULTILINE)
    assert match, f"Missing {key}"
    return match.group(1)


def _read_list(body: str, key: str) -> list[str]:
    match = re.search(
        rf"^\s*{re.escape(key)}\s*=\s*\[(?P<items>.*?)\]\s*$",
        body,
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"Missing {key}"
    return ast.literal_eval(f"[{match.group('items')}]")


def _top_level_src_packages() -> list[str]:
    src_root = REPO_ROOT / "src"
    return sorted(
        f"src/{path.name}"
        for path in src_root.iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    )


def test_pyproject_package_paths_match_source_tree() -> None:
    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    coverage_body = _read_section(pyproject_text, "tool.coverage.run")
    wheel_body = _read_section(pyproject_text, "tool.hatch.build.targets.wheel")
    expected_paths = _top_level_src_packages()

    assert sorted(_read_list(coverage_body, "source")) == expected_paths
    assert sorted(_read_list(wheel_body, "packages")) == expected_paths


def test_requires_python_matches_supported_runtime_floor() -> None:
    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    project_body = _read_section(pyproject_text, "project")

    assert _read_string(project_body, "requires-python") == ">=3.10"


def test_pytest_ini_matches_active_defaults() -> None:
    parser = configparser.ConfigParser()
    parser.read(PYTEST_INI_PATH, encoding="utf-8")

    pytest_section = parser["pytest"]
    addopts = pytest_section.get("addopts", "").split()

    assert pytest_section.get("testpaths") == "tests"
    assert pytest_section.get("pythonpath") == "."
    assert pytest_section.get("asyncio_mode") == "auto"
    assert "-x" in addopts
    assert "-q" in addopts
    assert "--tb=short" in addopts
    assert "--strict-markers" in addopts

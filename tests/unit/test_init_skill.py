import importlib.util
from pathlib import Path


_SCRIPT_CANDIDATES = [
    Path(__file__).resolve().parents[2]
    / "src"
    / "core"
    / "agent_runtime"
    / "skills"
    / "skill-creator"
    / "scripts"
    / "init_skill.py",
]

SCRIPT_PATH = next(path for path in _SCRIPT_CANDIDATES if path.exists())


def _load_init_skill_module():
    spec = importlib.util.spec_from_file_location("init_skill", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


init_skill_module = _load_init_skill_module()


def test_init_skill_writes_actionable_default_section_and_selected_resource_guidance(tmp_path, capsys):
    skill_dir = init_skill_module.init_skill(
        "test-skill",
        tmp_path,
        ["scripts"],
        include_examples=False,
    )

    output = capsys.readouterr().out
    skill_md = (skill_dir / "SKILL.md").read_text()

    assert "## Quick Start" in skill_md
    assert "TODO" not in skill_md
    assert "1. Edit SKILL.md to describe when this skill should be used and how it should work" in output
    assert "2. Add resources to scripts/ as needed" in output
    assert "references/" not in output
    assert "assets/" not in output


def test_init_skill_examples_guidance_only_mentions_selected_resource_directories(tmp_path, capsys):
    skill_dir = init_skill_module.init_skill(
        "reference-heavy-skill",
        tmp_path,
        ["scripts", "references"],
        include_examples=True,
    )

    output = capsys.readouterr().out
    skill_md = (skill_dir / "SKILL.md").read_text()
    example_script = (skill_dir / "scripts" / "example.py").read_text()
    example_reference = (skill_dir / "references" / "api_reference.md").read_text()

    assert skill_dir is not None
    assert "TODO" not in skill_md
    assert "TODO" not in example_script
    assert "TODO" not in example_reference
    assert "2. Replace or remove the example files in scripts/ and references/" in output
    assert "assets/" not in output

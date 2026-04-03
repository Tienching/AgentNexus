import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "nanobot"
    / "skills"
    / "skill-creator"
    / "scripts"
    / "init_skill.py"
)


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
    assert "## [TODO: Replace with the first main section based on chosen structure]" not in skill_md
    assert "2. Add resources to scripts/ as needed" in output
    assert "references/" not in output
    assert "assets/" not in output


def test_init_skill_examples_guidance_only_mentions_selected_resource_directories(tmp_path, capsys):
    skill_dir = init_skill_module.init_skill(
        "reference-heavy-skill",
        tmp_path,
        ["references", "assets"],
        include_examples=True,
    )

    output = capsys.readouterr().out

    assert skill_dir is not None
    assert (skill_dir / "SKILL.md").exists()
    assert "2. Customize or delete the example files in references/ and assets/" in output
    assert "scripts/" not in output

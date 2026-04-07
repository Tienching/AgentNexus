"""Tests for evolve prompt loading and new default asset paths."""

from __future__ import annotations

from pathlib import Path

from src.nanobot.config.schema import EvolutionConfig as SchemaEvolutionConfig
from src.nanobot.evolve.engine import EvolutionEngine as CompatEvolutionEngine
from src.nanobot.evolve.models import EvolutionConfig
from src.nanobot.evolve.prompts import build_assessment_prompt, load_prompt_template
from src.nanobot.evolve.runtime import EvolutionEngine as RuntimeEvolutionEngine


def test_engine_module_reexports_runtime_engine():
    assert CompatEvolutionEngine is RuntimeEvolutionEngine


def test_engine_config_defaults_point_to_evolve_assets():
    config = EvolutionConfig()
    assert config.memory_path == "./evolve/memory"
    assert config.journal_path == "./evolve/JOURNAL.md"
    assert config.identity_file == "./evolve/context/IDENTITY.md"
    assert config.personality_file == "./evolve/context/PERSONALITY.md"
    assert "evolve/context/IDENTITY.md" in config.protected_files
    assert "IDENTITY.md" in config.protected_files


def test_schema_config_defaults_point_to_evolve_assets():
    config = SchemaEvolutionConfig()
    assert config.memory_path == "./evolve/memory"
    assert config.journal_path == "./evolve/JOURNAL.md"
    assert config.identity_file == "./evolve/context/IDENTITY.md"
    assert config.personality_file == "./evolve/context/PERSONALITY.md"
    assert "evolve/context/PERSONALITY.md" in config.protected_files
    assert "PERSONALITY.md" in config.protected_files


def test_load_prompt_template_prefers_working_dir_assets(tmp_path):
    prompt_dir = tmp_path / "evolve" / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "assessment.md").write_text("custom prompt", encoding="utf-8")

    config = EvolutionConfig(working_dir=str(tmp_path))
    assert load_prompt_template(config, "assessment") == "custom prompt"


def test_build_assessment_prompt_injects_evolve_asset_paths(tmp_path):
    config = EvolutionConfig(working_dir=str(tmp_path))

    prompt = build_assessment_prompt(
        config,
        session_number=3,
        date_str="2026-04-01 00:00 UTC",
        context="CTX",
        working_dir=str(tmp_path),
    )

    assert "./evolve/JOURNAL.md" in prompt
    assert "./evolve/memory/active_learnings.md" in prompt
    assert "CTX" in prompt
    assert "Session 3" in prompt

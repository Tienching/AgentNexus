"""Prompt loading and rendering for the self-evolution system."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.agent_runtime.evolve.models import EvolutionConfig, EvolutionTask

PROJECT_ROOT = Path(__file__).resolve().parents[3]

LEGACY_PROMPT_FILES = {
    "assessment": "ASSESSMENT_AGENT.md",
    "planning": "PLANNING_AGENT.md",
    "implementation": "IMPLEMENTATION_AGENT.md",
    "skill": "SKILL.md",
}


def _stringify(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)


def _render(content: str, values: dict[str, Any]) -> str:
    rendered = content
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", _stringify(value))
    return rendered


def _candidate_paths(config: EvolutionConfig, name: str) -> list[Path]:
    working_dir = Path(config.working_dir).resolve()
    candidates = [
        working_dir / "evolve" / "prompts" / f"{name}.md",
        PROJECT_ROOT / "evolve" / "prompts" / f"{name}.md",
    ]
    if name in LEGACY_PROMPT_FILES:
        candidates.append(PROJECT_ROOT / "prompts" / "evolve" / LEGACY_PROMPT_FILES[name])
    return candidates


def load_prompt_template(config: EvolutionConfig, name: str) -> str:
    for path in _candidate_paths(config, name):
        if path.exists():
            return path.read_text(encoding="utf-8")
    paths = _candidate_paths(config, name)
    paths_str = ", ".join(str(p) for p in paths)
    raise FileNotFoundError(f"Prompt template '{name}' not found. Searched: {paths_str}")


def build_assessment_prompt(
    config: EvolutionConfig,
    *,
    session_number: int,
    date_str: str,
    context: str,
    working_dir: str,
) -> str:
    template = load_prompt_template(config, "assessment")
    return _render(
        template,
        {
            "session_number": session_number,
            "date_str": date_str,
            "context": context,
            "working_dir": working_dir,
            "journal_path": config.journal_path,
            "active_learnings_path": f"{config.memory_path.rstrip('/')}" + "/active_learnings.md",
        },
    )


def build_planning_prompt(
    config: EvolutionConfig,
    *,
    session_number: int,
    context: str,
    assessment_text: str,
) -> str:
    template = load_prompt_template(config, "planning")
    return _render(
        template,
        {
            "session_number": session_number,
            "context": context,
            "assessment_text": assessment_text,
            "max_tasks_per_session": config.max_tasks_per_session,
        },
    )


def build_implementation_prompt(
    config: EvolutionConfig,
    *,
    session_number: int,
    context: str,
    task: EvolutionTask,
    branch_name: str,
    pytest_cmd: str,
    working_dir: str,
) -> str:
    template = load_prompt_template(config, "implementation")
    return _render(
        template,
        {
            "session_number": session_number,
            "context": context,
            "task_title": task.title,
            "task_files": ", ".join(task.files) if task.files else "src/",
            "task_description": task.description,
            "branch_name": branch_name,
            "pytest_cmd": pytest_cmd,
            "working_dir": working_dir,
            "protected_files": ", ".join(config.protected_files),
        },
    )


def build_conflict_resolution_prompt(
    config: EvolutionConfig,
    *,
    branch_name: str,
    task: EvolutionTask,
    files_changed: list[str],
    conflicted_files: list[str],
    commit_msg: str,
) -> str:
    template = load_prompt_template(config, "conflict_resolution")
    return _render(
        template,
        {
            "branch_name": branch_name,
            "task_title": task.title,
            "files_changed": ", ".join(files_changed),
            "conflicted_files": [f"  - {path}" for path in conflicted_files],
            "git_add_files": " ".join(conflicted_files),
            "commit_msg": commit_msg,
        },
    )

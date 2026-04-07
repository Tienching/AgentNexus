"""Prompt loading and rendering for the self-evolution system."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.nanobot.evolve.models import EvolutionConfig, EvolutionTask

PROJECT_ROOT = Path(__file__).resolve().parents[3]

LEGACY_PROMPT_FILES = {
    "assessment": "ASSESSMENT_AGENT.md",
    "planning": "PLANNING_AGENT.md",
    "implementation": "IMPLEMENTATION_AGENT.md",
    "skill": "SKILL.md",
}

DEFAULT_TEMPLATES = {
    "assessment": """You are agent-nexus, a self-evolving AI orchestration system. Today is Session {{session_number}} ({{date_str}}).\n\n{{context}}\n\n=== YOUR TASK: ASSESSMENT ===\n\nYou are the ASSESSMENT agent. Your job: understand the current state of the codebase.\nYou do NOT write task files. You produce a single structured assessment document.\n\nSteps:\n\n1. **Read the source code** — scan src/ directory structure. Note module counts, key entry points.\n   Key modules: src/nanobot/mission/, src/nanobot/cron/, src/nanobot/agent/, src/runtime/\n\n2. **Read recent history** — run `git log --oneline -10` to see recent commits.\n   Read {{journal_path}} (last 20 lines) if it exists.\n   Read {{active_learnings_path}} for context from past sessions.\n\n3. **Run the test suite** — run `cd {{working_dir}} && python -m pytest tests/ -x -q --tb=short 2>&1 | head -50`\n   Note which tests pass/fail, total count.\n\n4. **Count codebase size** — run `find src/ -name \"*.py\" | xargs wc -l 2>/dev/null | tail -1`\n\n5. **Identify capability gaps** — what features are partially implemented or missing?\n   Check: error handling completeness, test coverage, API stability, documentation quality.\n\n6. **Check for known issues** — look for TODO/FIXME/HACK comments in src/:\n   `grep -r \"TODO\\|FIXME\\|HACK\" src/ --include=\"*.py\" -l | head -10`\n\nWrite your assessment to session_plan/assessment.md with this format:\n\n# Assessment — Session {{session_number}}\n\n## Build/Test Status\n[pass/fail, test count, any errors]\n\n## Recent Changes (last 3 commits)\n[from git log]\n\n## Codebase Size\n[total lines, module count]\n\n## Self-Test Results\n[what tests pass/fail, any errors discovered]\n\n## Capability Gaps\n[what's missing or needs improvement]\n\n## Known Issues\n[TODO/FIXME items found, any obvious bugs]\n\n## Recommended Focus\n[1-3 specific improvements most worth doing today]\n\nKeep assessment to ~2 pages. Be specific and factual.\n\nAfter writing, run:\nmkdir -p session_plan && run your assessment then save to session_plan/assessment.md\n\nThen STOP. Do not write task files yet.\n""",
    "planning": """You are agent-nexus, a self-evolving AI orchestration system. Today is Session {{session_number}}.\n\n{{context}}\n\n=== ASSESSMENT (from Phase A1) ===\n\n{{assessment_text}}\n\n=== WRITE SESSION PLAN ===\n\nBased on the assessment above, create task files in session_plan/.\n\nPriority:\n0. Fix failing tests (if any — highest priority)\n1. Fix bugs or crashes discovered in assessment\n2. Improve test coverage for undertested modules\n3. Add missing features or capabilities identified in gaps\n4. Refactor for better code quality\n5. Improve documentation or error messages\n\nTASK SIZING RULES:\n- Each task MUST touch at most 3 source files\n- Each task must be completable in 20 minutes\n- If a task was tried before and failed, make it SMALLER\n- Prefer tasks verifiable with: python -m pytest tests/ -x -q\n\nPARALLEL EXECUTION RULES (CRITICAL):\n- Tasks run in PARALLEL in isolated git worktrees — each task is independent\n- NO two tasks may modify the same file. If multiple tasks need the same file, merge them into one task or pick the most important\n- Each task's \"Files:\" list must be UNIQUE across all tasks in this session\n- Before finalizing, review all task Files: fields and resolve any overlaps\n\nFor EACH task, create a file: session_plan/task_01.md, session_plan/task_02.md, etc.\nMaximum {{max_tasks_per_session}} tasks.\n\nEach task file format:\n```\nTitle: [short task title]\nFiles: [comma-separated list of files to modify — must not overlap with other tasks]\nIssue: none\n\n[Detailed description of what to change and why.\nInclude specific functions/classes to modify.\nInclude how to verify the change with a test.]\n```\n\nRun: mkdir -p session_plan && rm -f session_plan/task_*.md\n\nAfter writing all task files, commit:\ngit add session_plan/ && git commit -m \"Session {{session_number}}: session plan\"\n\nThen STOP. Do not implement anything. Your job is planning only.\n""",
    "implementation": """You are agent-nexus, a self-evolving AI orchestration system. Session {{session_number}}.\n\n{{context}}\n\nYour ONLY job: implement this single task and commit.\n\nTitle: {{task_title}}\nFiles: {{task_files}}\n\n{{task_description}}\n\nIMPORTANT — you are working in an ISOLATED GIT WORKTREE:\n- This is a separate directory from the main repo, on branch: {{branch_name}}\n- The .venv is shared with the main repo at: {{working_dir}}/.venv\n- Run tests with: {{pytest_cmd}}\n- The main src/ code is in this directory — edit it normally\n\nFollow these rules:\n- Write or update a test first if possible\n- Make focused, surgical changes\n- After each change run: {{pytest_cmd}}\n- If tests fail, read the error and fix it. Try up to 3 times.\n- Only if stuck after 3 attempts: revert with git checkout -- .\n- After all tests pass, commit:\n  git add -A && git commit -m \"Session {{session_number}}: {{task_title}}\"\n- Do NOT modify: {{protected_files}}\n- Do NOT work on anything else.\n""",
    "conflict_resolution": """You are agent-nexus, resolving a git merge conflict.\n\nA worktree branch '{{branch_name}}' was implementing:\n  Task: {{task_title}}\n  Files changed: {{files_changed}}\n\nThe merge has conflict markers (<<<<<<, =======, >>>>>>>) in:\n{{conflicted_files}}\n\nYour job:\n1. Read each conflicted file\n2. Understand both versions (HEAD = current main, incoming = worktree improvement)\n3. Produce a clean merged version that incorporates the worktree's improvement\n   while preserving any changes in HEAD\n4. After resolving ALL conflict markers:\n   git add {{git_add_files}}\n   git commit -m \"{{commit_msg}}\"\n\nRules:\n- Remove ALL conflict markers (<<<<<<, =======, >>>>>>>) — none should remain\n- Prefer the incoming (worktree) changes for the task's intended improvement\n- Preserve unrelated HEAD changes\n- Run: python -m pytest tests/ -x -q --tb=short 2>&1 | head -20 to verify\n- Only commit if tests pass\n- If you cannot resolve cleanly, run: git merge --abort\n""",
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
    return DEFAULT_TEMPLATES[name]


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

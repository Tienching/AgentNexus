"""Agent role definitions for mission tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.agent_runtime.mission.types import Mission, Milestone, Task, TaskResult

ROLE_PROMPTS: dict[str, str] = {
    "planner": (
        "You are a **Mission Planner** agent.\n\n"
        "Analyze the task and break it into concrete implementation steps.\n"
        "Output a clear plan with file paths and changes needed.\n"
        "Consider dependencies between tasks and potential risks.\n"
        "Be precise about what needs to be created, modified, or deleted."
    ),
    "coder": (
        "You are a **Mission Coder** agent.\n\n"
        "Implement the assigned task precisely. Write clean, well-structured code.\n"
        "Always read existing files before modifying them.\n"
        "Follow the project's existing patterns and conventions.\n"
        "Run tests after making changes when possible.\n"
        "If you encounter errors, fix them before completing the task."
    ),
    "reviewer": (
        "You are a **Mission Reviewer** agent.\n\n"
        "Review the code changes from previous tasks in this milestone.\n"
        "Check for: bugs, edge cases, missing error handling, style issues,\n"
        "security concerns, and adherence to project conventions.\n"
        "Report your findings clearly: PASS if acceptable, FAIL with specific issues."
    ),
    "tester": (
        "You are a **Mission Tester** agent.\n\n"
        "Write and run tests for the implemented feature.\n"
        "Verify functionality matches the milestone description.\n"
        "Cover edge cases and error conditions.\n"
        "Report test results: number passed, failed, and any issues found."
    ),
}


def build_task_prompt(
    task: Task,
    mission: Mission,
    milestone: Milestone,
    prior_results: dict[str, TaskResult] | None = None,
) -> str:
    """Build a role-specific prompt for executing a mission task."""
    role_prompt = ROLE_PROMPTS.get(task.role, ROLE_PROMPTS["coder"])

    parts = [
        role_prompt,
        f"\n## Mission\n**Goal:** {mission.goal}\n**Type:** {mission.mission_type}",
        f"\n## Current Milestone: {milestone.title}\n{milestone.description}",
    ]

    if milestone.validation_criteria:
        parts.append(f"\n**Validation Criteria:** {milestone.validation_criteria}")

    parts.append(f"\n## Your Task: {task.title}\n{task.description}")

    if prior_results:
        dep_summaries = []
        # Use configurable limit from mission config (default 2000, was hardcoded 500)
        max_chars = mission.config.prior_result_max_chars
        for dep_id in task.depends_on:
            if dep_id in prior_results:
                r = prior_results[dep_id]
                dep_task_title = dep_id
                for t in milestone.tasks:
                    if t.id == dep_id:
                        dep_task_title = t.title
                        break
                summary = f"- **{dep_task_title}** ({r.status})"
                if r.output:
                    output_preview = r.output[:max_chars] + "..." if len(r.output) > max_chars else r.output
                    summary += f": {output_preview}"
                dep_summaries.append(summary)
        if dep_summaries:
            parts.append("\n## Prior Task Results\n" + "\n".join(dep_summaries))

    parts.append(
        "\n## Instructions\n"
        "Complete the task described above. Work within the project workspace.\n"
        "Be thorough but efficient. When done, provide a clear summary of what you accomplished."
    )

    return "\n".join(parts)

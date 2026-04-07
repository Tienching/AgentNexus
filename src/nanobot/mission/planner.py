"""LLM-driven mission planning: goal decomposition into milestones and tasks."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.nanobot.mission.types import Milestone, Task, _now_ms

if TYPE_CHECKING:
    from src.nanobot.providers.base import LLMProvider

_PLAN_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "mission_plan",
            "description": "Submit a structured mission plan with milestones and tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_type": {
                        "type": "string",
                        "enum": [
                            "feature_impl",
                            "bug_fix",
                            "code_migration",
                            "refactor",
                            "research",
                            "documentation",
                            "custom",
                        ],
                        "description": "Classified type of mission",
                    },
                    "milestones": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "validation_criteria": {"type": "string"},
                                "validation_commands": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Shell commands to validate milestone completion (e.g. 'pytest tests/', 'python -c \"import mymodule\"'). Empty array for no validation.",
                                },
                                "depends_on": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Milestone IDs this milestone depends on for parallel execution. Empty array means no dependencies (can run immediately).",
                                },
                                "tasks": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "title": {"type": "string"},
                                            "description": {"type": "string"},
                                            "role": {
                                                "type": "string",
                                                "enum": [
                                                    "planner",
                                                    "coder",
                                                    "reviewer",
                                                    "tester",
                                                ],
                                            },
                                            "depends_on": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                                "description": "Task IDs this depends on",
                                            },
                                            "model": {
                                                "type": "string",
                                                "description": "Optional model override for this task. Leave empty for default.",
                                            },
                                        },
                                        "required": ["title", "description"],
                                    },
                                },
                            },
                            "required": ["title", "description", "tasks"],
                        },
                    },
                },
                "required": ["mission_type", "milestones"],
            },
        },
    }
]

_SYSTEM_PROMPT = """You are a Mission Planner. Given a goal, decompose it into milestones and tasks.

Rules:
1. Each milestone is a logical phase (e.g., "Setup", "Core Implementation", "Testing").
2. Each task within a milestone is a concrete, actionable unit of work.
3. Tasks can depend on other tasks WITHIN THE SAME MILESTONE using task IDs.
4. Milestones can depend on other milestones using milestone IDs (e.g., depends_on: ["m-001"]).
   Milestones with no dependencies can run in parallel.
5. Assign roles: "planner" for analysis, "coder" for implementation, "reviewer" for review, "tester" for testing.
6. Keep task descriptions specific — include file paths, function names, and expected behavior.
7. Order milestones from foundation to integration.
8. Aim for 2-5 milestones with 2-6 tasks each.
9. For each milestone, provide validation_commands — shell commands that verify the milestone's work
   (e.g., ["pytest tests/", "python -c 'import mymodule'"]).

Call the mission_plan tool with your structured plan."""


class MissionPlanner:
    """Decomposes a goal into milestones and tasks using LLM."""

    def __init__(self, provider: LLMProvider, model: str, workspace: Path):
        self.provider = provider
        self.model = model
        self.workspace = workspace

    async def plan_mission(
        self, goal: str, context: str = ""
    ) -> tuple[str, list[Milestone]]:
        """Decompose goal into milestones and tasks.

        Returns (mission_type, milestones).
        """
        user_content = f"## Goal\n{goal}"
        if context:
            user_content += f"\n\n## Additional Context\n{context}"
        user_content += f"\n\n## Workspace\n{self.workspace}"

        try:
            response = await self.provider.chat_with_retry(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                tools=_PLAN_TOOL,
                model=self.model,
            )

            if not response.has_tool_calls:
                logger.warning("Planner did not use tool call, using default plan")
                return "custom", self._default_plan(goal)

            args = response.tool_calls[0].arguments
            mission_type = args.get("mission_type", "custom")
            milestones = self._parse_plan(args.get("milestones", []))

            if not milestones:
                logger.warning("Planner returned empty plan, using default")
                return "custom", self._default_plan(goal)

            return mission_type, milestones

        except Exception as e:
            logger.error("Planning failed: {}", e)
            return "custom", self._default_plan(goal)

    def _parse_plan(self, milestones_data: list[dict[str, Any]]) -> list[Milestone]:
        """Parse LLM plan output into Milestone/Task objects."""
        milestones = []

        for mi, ms_data in enumerate(milestones_data):
            ms_id = f"m-{mi + 1:03d}"
            tasks = []
            task_id_map: dict[int, str] = {}

            for ti, t_data in enumerate(ms_data.get("tasks", [])):
                t_id = f"{ms_id}-t-{ti + 1:03d}"
                task_id_map[ti] = t_id

                depends_on = []
                for dep in t_data.get("depends_on", []):
                    if isinstance(dep, int) and dep in task_id_map:
                        depends_on.append(task_id_map[dep])
                    elif isinstance(dep, str):
                        depends_on.append(dep)

                tasks.append(
                    Task(
                        id=t_id,
                        title=t_data.get("title", f"Task {ti + 1}"),
                        description=t_data.get("description", ""),
                        role=t_data.get("role", "coder"),
                        depends_on=depends_on,
                        model=t_data.get("model", ""),
                    )
                )

            milestones.append(
                Milestone(
                    id=ms_id,
                    title=ms_data.get("title", f"Milestone {mi + 1}"),
                    description=ms_data.get("description", ""),
                    tasks=tasks,
                    validation_criteria=ms_data.get("validation_criteria", ""),
                    validation_commands=ms_data.get("validation_commands", []),
                    depends_on=ms_data.get("depends_on", []),
                )
            )

        # Validate plan quality
        self._validate_plan(milestones)

        return milestones

    def _validate_plan(self, milestones: list[Milestone]) -> None:
        """Validate plan quality — reject bad plans with clear errors.

        Raises ValueError if the plan has critical issues.
        """
        if not milestones:
            raise ValueError("Plan has no milestones")

        milestone_ids = {milestone.id for milestone in milestones}
        for ms in milestones:
            for dep in ms.depends_on:
                if dep not in milestone_ids:
                    raise ValueError(
                        f"Milestone '{ms.title}' depends on '{dep}' which doesn't exist"
                    )
                if dep == ms.id:
                    raise ValueError(f"Milestone '{ms.title}' depends on itself")

        self._check_milestone_cycles(milestones)

        for ms in milestones:
            if not ms.tasks:
                raise ValueError(f"Milestone '{ms.title}' has no tasks")

            task_ids = {t.id for t in ms.tasks}
            for task in ms.tasks:
                # Check for empty descriptions
                if not task.description or not task.description.strip():
                    raise ValueError(
                        f"Task '{task.title}' in milestone '{ms.title}' has empty description"
                    )

                # Validate dependency references
                for dep in task.depends_on:
                    if dep not in task_ids:
                        raise ValueError(
                            f"Task '{task.title}' depends on '{dep}' which doesn't exist "
                            f"in milestone '{ms.title}'"
                        )

                # Check for self-dependency
                if task.id in task.depends_on:
                    raise ValueError(f"Task '{task.title}' depends on itself")

            # Detect DAG cycles
            self._check_dag_cycles(ms)

    @staticmethod
    def _check_milestone_cycles(milestones: list[Milestone]) -> None:
        """Detect cycles in milestone dependency graph using DFS."""
        adjacency: dict[str, list[str]] = {
            milestone.id: list(milestone.depends_on) for milestone in milestones
        }
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {milestone_id: WHITE for milestone_id in adjacency}

        def dfs(node: str) -> str | None:
            color[node] = GRAY
            for dep in adjacency.get(node, []):
                if color[dep] == GRAY:
                    return f"{node} -> {dep}"
                if color[dep] == WHITE:
                    result = dfs(dep)
                    if result:
                        return result
            color[node] = BLACK
            return None

        for milestone_id in adjacency:
            if color[milestone_id] == WHITE:
                cycle = dfs(milestone_id)
                if cycle:
                    raise ValueError(f"Milestone dependency cycle detected: {cycle}")

    @staticmethod
    def _check_dag_cycles(milestone: Milestone) -> None:
        """Detect cycles in task dependency graph using DFS."""
        adjacency: dict[str, list[str]] = {t.id: list(t.depends_on) for t in milestone.tasks}
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {tid: WHITE for tid in adjacency}

        def dfs(node: str) -> str | None:
            color[node] = GRAY
            for dep in adjacency.get(node, []):
                if dep not in color:
                    continue
                if color[dep] == GRAY:
                    return f"Cycle detected involving tasks: {node} -> {dep}"
                if color[dep] == WHITE:
                    result = dfs(dep)
                    if result:
                        return result
            color[node] = BLACK
            return None

        for task_id in adjacency:
            if color[task_id] == WHITE:
                cycle = dfs(task_id)
                if cycle:
                    raise ValueError(f"DAG cycle in milestone '{milestone.title}': {cycle}")

    def _inject_quality_tasks(self, milestones: list[Milestone], auto_review: bool, auto_test: bool) -> list[Milestone]:
        """Auto-inject reviewer/tester tasks after coder tasks."""
        for ms in milestones:
            new_tasks = []
            for task in ms.tasks:
                new_tasks.append(task)
                if task.role == "coder":
                    if auto_review:
                        review_id = f"{task.id}-review"
                        new_tasks.append(
                            Task(
                                id=review_id,
                                title=f"Review: {task.title}",
                                description=f"Review the implementation of: {task.title}",
                                role="reviewer",
                                depends_on=[task.id],
                            )
                        )
                    if auto_test:
                        test_id = f"{task.id}-test"
                        test_deps = [task.id]
                        if auto_review:
                            test_deps.append(f"{task.id}-review")
                        new_tasks.append(
                            Task(
                                id=test_id,
                                title=f"Test: {task.title}",
                                description=f"Write and run tests for: {task.title}",
                                role="tester",
                                depends_on=test_deps,
                            )
                        )
            ms.tasks = new_tasks
        return milestones

    def _default_plan(self, goal: str) -> list[Milestone]:
        """Generate a simple default plan when LLM planning fails."""
        return [
            Milestone(
                id="m-001",
                title="Implementation",
                description=goal,
                tasks=[
                    Task(
                        id="m-001-t-001",
                        title="Analyze requirements",
                        description=f"Analyze and plan: {goal}",
                        role="planner",
                    ),
                    Task(
                        id="m-001-t-002",
                        title="Implement solution",
                        description=f"Implement: {goal}",
                        role="coder",
                        depends_on=["m-001-t-001"],
                    ),
                    Task(
                        id="m-001-t-003",
                        title="Verify implementation",
                        description="Run tests and verify the implementation works correctly.",
                        role="tester",
                        depends_on=["m-001-t-002"],
                    ),
                ],
                validation_criteria="All tasks complete successfully.",
            )
        ]

    async def replan_milestone(
        self, milestone: Milestone, error_context: str
    ) -> Milestone | None:
        """Re-plan a failed milestone with error context."""
        prompt = (
            f"The following milestone failed:\n\n"
            f"## {milestone.title}\n{milestone.description}\n\n"
            f"## Error\n{error_context}\n\n"
            f"Create a revised plan to accomplish the same goal, "
            f"taking the error into account."
        )

        try:
            _, milestones = await self.plan_mission(prompt)
            return milestones[0] if milestones else None
        except Exception as e:
            logger.error("Replanning failed: {}", e)
            return None

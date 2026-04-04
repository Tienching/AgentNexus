from pathlib import Path

import pytest

from src.nanobot.mission.planner import MissionPlanner


def _planner() -> MissionPlanner:
    return MissionPlanner(provider=None, model="test-model", workspace=Path("/tmp"))


def test_parse_plan_accepts_valid_milestone_dependency_chain():
    milestones = _planner()._parse_plan(
        [
            {
                "title": "Foundation",
                "description": "Set up the base milestone.",
                "tasks": [
                    {
                        "title": "Plan work",
                        "description": "Create the foundation plan.",
                    }
                ],
            },
            {
                "title": "Integration",
                "description": "Build on the foundation milestone.",
                "depends_on": ["m-001"],
                "tasks": [
                    {
                        "title": "Implement work",
                        "description": "Implement the integration changes.",
                    }
                ],
            },
        ]
    )

    assert [milestone.id for milestone in milestones] == ["m-001", "m-002"]
    assert milestones[0].depends_on == []
    assert milestones[1].depends_on == ["m-001"]


def test_parse_plan_rejects_unknown_milestone_dependency_reference():
    with pytest.raises(ValueError, match="depends on 'm-999' which doesn't exist"):
        _planner()._parse_plan(
            [
                {
                    "title": "Foundation",
                    "description": "Set up the base milestone.",
                    "depends_on": ["m-999"],
                    "tasks": [
                        {
                            "title": "Plan work",
                            "description": "Create the foundation plan.",
                        }
                    ],
                }
            ]
        )


def test_parse_plan_rejects_milestone_self_dependency():
    with pytest.raises(ValueError, match="Milestone 'Foundation' depends on itself"):
        _planner()._parse_plan(
            [
                {
                    "title": "Foundation",
                    "description": "Set up the base milestone.",
                    "depends_on": ["m-001"],
                    "tasks": [
                        {
                            "title": "Plan work",
                            "description": "Create the foundation plan.",
                        }
                    ],
                }
            ]
        )


def test_parse_plan_rejects_cycles_across_milestones():
    with pytest.raises(ValueError, match="Milestone dependency cycle"):
        _planner()._parse_plan(
            [
                {
                    "title": "Foundation",
                    "description": "Set up the base milestone.",
                    "depends_on": ["m-002"],
                    "tasks": [
                        {
                            "title": "Plan work",
                            "description": "Create the foundation plan.",
                        }
                    ],
                },
                {
                    "title": "Integration",
                    "description": "Build on the foundation milestone.",
                    "depends_on": ["m-001"],
                    "tasks": [
                        {
                            "title": "Implement work",
                            "description": "Implement the integration changes.",
                        }
                    ],
                },
            ]
        )

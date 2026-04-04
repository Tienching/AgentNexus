Title: Reject invalid milestone dependency graphs
Files: src/nanobot/mission/planner.py, tests/unit/test_mission_planner.py
Issue: none

Extend `MissionPlanner._validate_plan()` to validate milestone-level `depends_on` edges before a plan is accepted. In addition to the existing task-level checks, reject unknown milestone IDs, self-dependencies, and cross-milestone cycles so the orchestration layer cannot emit an invalid milestone DAG.

Keep the implementation inside `MissionPlanner` and add focused tests that exercise `_parse_plan()` / `_validate_plan()` with minimal plans: one valid dependency chain, one missing milestone reference, one self-dependency, and one cycle across milestones. The goal is to catch bad mission graphs before scheduling starts. Verify with `python3 -m pytest tests/unit/test_mission_planner.py -q`.

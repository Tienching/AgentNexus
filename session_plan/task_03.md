Title: Add validated evolution task manifest parsing
Files: src/nanobot/evolve/runtime.py, src/nanobot/evolve/models.py, tests/evolve/test_engine.py
Issue: none

Strengthen the planning contract by adding a typed session-plan manifest alongside the existing markdown parsing. Introduce a small dataclass model in `src/nanobot/evolve/models.py` for a parsed task payload, then update `EvolutionEngine.run_planning()` and `EvolutionEngine._parse_task_file()` to validate required fields, reject empty `files` lists, and fail fast when two planned tasks claim the same file path.

Keep markdown task files supported so the planner remains backward compatible, but make the parser enforce the same invariants the worktree executor depends on. Extend `tests/evolve/test_engine.py` with regression coverage for valid tasks, invalid task files, and duplicate file ownership across tasks.

Why: the assessment identified the evolution pipeline as too filesystem-driven and weakly typed; adding validation is the smallest high-value step toward a durable planning contract.

Verify with:
`python3 -m pytest tests/evolve/test_engine.py -q`
Title: Add typed JSON manifest support for evolution planning
Files: src/nanobot/evolve/runtime.py, tests/evolve/test_engine.py
Issue: none

Keep the existing markdown task files, but add an optional machine-readable planning manifest at `session_plan/tasks.json`. Extend `EvolutionEngine.run_planning()` in `src/nanobot/evolve/runtime.py` to load the JSON manifest first when present, validate that each task has a title, non-empty files list, and description, and fall back to parsing `task_*.md` files when the manifest is missing. Add focused tests in `tests/evolve/test_engine.py` for valid manifest loading and markdown fallback.

Why: the Day 3 assessment identified the planning boundary as fragile because it depends entirely on markdown parsing. A small typed layer improves reliability without breaking the current workflow or removing the human-readable task files.

Verify with:
`python3 -m pytest tests/evolve/test_engine.py -q`

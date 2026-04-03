Title: Accept a typed session plan manifest before markdown fallback
Files: src/nanobot/evolve/runtime.py, tests/evolve/test_engine.py
Issue: none

Reduce planning fragility without changing the human-readable `session_plan/task_*.md` workflow. In `src/nanobot/evolve/runtime.py`, teach `EvolutionEngine.run_planning()` to look for an optional typed manifest such as `session_plan/tasks.json`, validate the required task fields, and build `EvolutionTask` objects from it before falling back to `_parse_task_file()`.

Keep markdown support intact so existing prompts still work, but make malformed manifest data fail closed and fall back cleanly instead of producing half-parsed tasks. Extend `tests/evolve/test_engine.py` with coverage for both the typed-manifest path and the existing markdown fallback path. Verify with `python3 -m pytest tests/evolve/test_engine.py -q`.

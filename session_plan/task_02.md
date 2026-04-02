Title: Emit a typed manifest for planned evolution tasks
Files: src/nanobot/evolve/runtime.py, src/nanobot/evolve/models.py, tests/evolve/test_engine.py
Issue: none

Keep the markdown task files as the human planning surface, but add a machine-readable manifest beside them after planning completes. Introduce a narrow typed representation in `src/nanobot/evolve/models.py` for the derived planning output, then update `EvolutionEngine.run_planning()` in `src/nanobot/evolve/runtime.py` to serialize the parsed tasks to `session_plan/tasks.json` after reading `task_*.md` files.

Why: the current planning contract depends entirely on markdown filenames and free-form parsing. A derived JSON manifest makes downstream automation more reliable without changing the authoring workflow or requiring the planner to stop writing markdown.

Extend `tests/evolve/test_engine.py` to assert that planning writes the manifest with the expected task IDs, titles, files, and issue fields, and that fallback planning still produces a valid manifest. Verify with `python3 -m pytest tests/evolve/test_engine.py -q`.
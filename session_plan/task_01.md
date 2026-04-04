Title: Make evolution pytest command interpreter-safe
Files: src/nanobot/evolve/prompts.py, src/nanobot/evolve/implementation.py, tests/evolve/test_engine_worktree.py
Issue: none

Create one authoritative pytest command for the self-evolution flow and stop hardcoding bare `python -m pytest` in an environment where only `python3 -m pytest` is reliable. Update the default assessment/conflict-resolution templates in `src/nanobot/evolve/prompts.py`, and update `run_task_in_worktree` plus `run_implementation_serial` in `src/nanobot/evolve/implementation.py` so they use the same resolved command (prefer `.venv/bin/python` when present, otherwise fall back to `python3`). Extend `tests/evolve/test_engine_worktree.py` to assert the executor prompt and post-run verification both use the authoritative command. Verify with `python3 -m pytest tests/evolve/test_engine_worktree.py tests/evolve/test_prompts.py -q`.

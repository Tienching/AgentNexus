Title: Reuse one resolved pytest command in serial evolve execution
Files: src/nanobot/evolve/implementation.py, tests/evolve/test_engine_worktree.py
Issue: none

Shrink the failed Day 8 interpreter fix into the serial path only. In `src/nanobot/evolve/implementation.py`, extract a small helper that resolves the working pytest command once for the current environment, then reuse it in both `run_task_in_worktree()` and `run_implementation_serial()` instead of mixing `.venv` detection with hardcoded `python -m pytest` calls.

Keep the change surgical: prefer `.venv/bin/python` when available, otherwise fall back to `python3`, then `python`, and make the post-implementation verification in `run_implementation_serial()` use the same resolved command that is shown in the implementation prompt. Add regression coverage in `tests/evolve/test_engine_worktree.py` for the serial branch so the test proves the resolved command is passed through consistently. Verify with `python3 -m pytest tests/evolve/test_engine_worktree.py -q`.

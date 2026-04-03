Title: Unify pytest command resolution in serial evolve execution
Files: src/nanobot/evolve/implementation.py, tests/evolve/test_implementation.py
Issue: none

Fix the remaining runtime-side verification bug in `src/nanobot/evolve/implementation.py`. Right now `run_task_in_worktree` has one command selection path, while `run_implementation_serial` still hardcodes `python -m pytest` for both the implementation prompt and the post-change verification step.

Add a focused helper in this module that resolves the pytest command once, then use it from both `run_task_in_worktree` and `run_implementation_serial`. Update the serial path so the prompt passed to `build_implementation_prompt` and the final verification shell command both use the same resolved interpreter.

Add a dedicated test module at `tests/evolve/test_implementation.py` covering `.venv/bin/python` preference and `python3` fallback, and assert serial execution calls `_run_shell` with the resolved command instead of the broken default. Verify with `python3 -m pytest tests/evolve/test_implementation.py -q`.

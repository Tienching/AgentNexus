Title: Reuse interpreter resolution in serial and worktree evolution runs
Files: src/nanobot/evolve/implementation.py, tests/evolve/test_engine.py, tests/evolve/test_engine_worktree.py
Issue: none

Centralize pytest command selection in `src/nanobot/evolve/implementation.py` so both `run_task_in_worktree()` and `run_implementation_serial()` use the same interpreter resolution rule. Update those two functions to prefer the shared `.venv/bin/python` when it exists, otherwise fall back to `python3`, and stop emitting or executing bare `python -m pytest ...` in either path.

Why: worktree execution partly handles `.venv`, but the serial path still hardcodes bare `python`, so self-evolution can pass planning and still fail during implementation on this machine.

Add focused regression coverage in `tests/evolve/test_engine_worktree.py` and `tests/evolve/test_engine.py` that asserts the generated implementation prompt and the post-change verification command both use the resolved interpreter.

Verify with: `python3 -m pytest tests/evolve/test_engine.py tests/evolve/test_engine_worktree.py -q`.

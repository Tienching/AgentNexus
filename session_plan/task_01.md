Title: Unify evolve pytest command selection
Files: src/nanobot/evolve/prompts.py, src/nanobot/evolve/implementation.py, tests/evolve/test_prompts.py
Issue: none

Replace the remaining bare `python -m pytest` instructions in the self-evolution flow with one shared pytest command resolver that matches this repository's working interpreter. Update `DEFAULT_TEMPLATES` in `src/nanobot/evolve/prompts.py` so the assessment and conflict-resolution prompts stop telling agents to run a broken command, and update `run_task_in_worktree()` plus `run_implementation_serial()` in `src/nanobot/evolve/implementation.py` to reuse the same command when injecting `pytest_cmd` and when running post-change validation.

Why: Day 13 assessment showed the source tree is green on Python 3, but the self-evolution control plane still hardcodes a pytest entrypoint that fails in this environment. Fixing that makes autonomous assessment, implementation, and merge resolution consistent.

Verify by extending `tests/evolve/test_prompts.py` to assert the generated prompt text and resolved command prefer `.venv/bin/python` when available and otherwise fall back to `python3 -m pytest`, then run `python3 -m pytest tests/evolve/test_prompts.py -q`.

Title: Replace bare python in default evolve prompts
Files: src/nanobot/evolve/prompts.py, tests/evolve/test_prompts.py
Issue: none

Update the built-in prompt templates in `DEFAULT_TEMPLATES` so every pytest instruction emitted by the assessment, implementation, and conflict-resolution prompts uses the supported interpreter in this repo. Keep `build_assessment_prompt()` path substitution intact while removing any remaining bare `python -m pytest ...` guidance from the rendered prompt text.

Why: the self-evolution planner still bakes `/usr/bin/python` into prompt text, which makes assessment and remediation fail before the real suite runs in this environment.

Add regression coverage in `tests/evolve/test_prompts.py` that checks the rendered assessment prompt uses `python3 -m pytest tests/ -x -q --tb=short` and that the built-in implementation/conflict prompt templates no longer mention bare `python`.

Verify with: `python3 -m pytest tests/evolve/test_prompts.py -q`.

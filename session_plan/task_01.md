Title: Make evolve prompts use a working pytest interpreter
Files: src/nanobot/evolve/prompts.py, tests/evolve/test_prompts.py
Issue: none

Update the default evolve prompt templates so self-assessment and merge-conflict recovery stop hardcoding `python -m pytest`, which is a false-red command in this environment. Keep the change inside `src/nanobot/evolve/prompts.py`: add a small helper that resolves the prompt-facing pytest command from repo context, preferring `.venv/bin/python` when it exists and otherwise falling back to `python3 -m pytest`.

Apply that helper in the prompt builders that currently render broken instructions, especially `build_assessment_prompt`, `build_planning_prompt`, and `build_conflict_resolution_prompt`. The goal is for the generated instructions to tell agent-nexus to run a command that actually matches the repo’s supported interpreter contract instead of teaching itself the wrong verification step.

Extend `tests/evolve/test_prompts.py` to assert the rendered prompts include the resolved pytest command and no longer embed the hardcoded `python -m pytest` string. Verify with `python3 -m pytest tests/evolve/test_prompts.py -q`.

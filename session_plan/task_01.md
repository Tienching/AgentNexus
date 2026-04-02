Title: Align evolve pytest commands with the supported interpreter
Files: src/nanobot/evolve/prompts.py, src/nanobot/evolve/implementation.py, tests/evolve/test_prompts.py
Issue: none

Remove the remaining hardcoded `python -m pytest` commands from the evolve flow. Update the default templates in `src/nanobot/evolve/prompts.py` so assessment and conflict-resolution instructions use the same supported test command the repo actually needs in this environment. In `src/nanobot/evolve/implementation.py`, add one small helper that builds the pytest command once (`.venv/bin/python -m pytest ...` when present, otherwise `python3 -m pytest ...`) and reuse it in both worktree and serial execution paths.

Why: the self-evolution system currently reports false failures because assessment, conflict resolution, and serial verification still assume `/usr/bin/python` can run pytest. This task fixes the platform's own feedback loop first.

Add regression coverage in `tests/evolve/test_prompts.py` that asserts the default prompt text no longer emits bare `python -m pytest` and that the shared command builder chooses the supported interpreter. Verify with `python3 -m pytest tests/evolve/test_prompts.py -q`.
Title: Fix evolve assessment prompt pytest command
Files: src/nanobot/evolve/prompts.py, tests/evolve/test_prompts.py
Issue: none

Update `DEFAULT_TEMPLATES["assessment"]` in `src/nanobot/evolve/prompts.py` so the embedded verification step uses the supported interpreter and preserves pytest's exit status. Replace the current `python -m pytest ... | head -50` instruction with a direct `python3 -m pytest tests/ -x -q --tb=short` command, and keep the prompt wording explicit that the agent must report pass/fail and the first failure accurately.

Extend `tests/evolve/test_prompts.py` to assert that `build_assessment_prompt()` renders the `python3 -m pytest` command and no longer includes the masking `| head -50` pipeline.

Verify with:
`python3 -m pytest tests/evolve/test_prompts.py -q`

Title: Fix assessment prompt pytest health check
Files: src/nanobot/evolve/prompts.py, tests/evolve/test_prompts.py
Issue: none

Update `DEFAULT_TEMPLATES["assessment"]` in `src/nanobot/evolve/prompts.py` so the self-assessment instructions use the supported interpreter in this repo and do not mask pytest failures behind a pipe. Replace the bare `python -m pytest tests/ -x -q --tb=short 2>&1 | head -50` guidance with a command that preserves exit status, such as direct `python3 -m pytest tests/ -x -q --tb=short` or an equivalent `pipefail` form if truncation is still needed. Keep `build_assessment_prompt()` behavior the same aside from the rendered command text.

Extend `tests/evolve/test_prompts.py` with assertions on the generated assessment prompt so it explicitly mentions `python3` and no longer relies on the old pipe-masked form. This prevents the evolution system from reporting a false green when `python` resolves to 2.7.18.

Verify with:
`python3 -m pytest tests/evolve/test_prompts.py -q`

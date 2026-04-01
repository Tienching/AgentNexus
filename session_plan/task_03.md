Title: Use the supported pytest interpreter in evolve prompts
Files: src/nanobot/evolve/prompts.py, src/nanobot/evolve/implementation.py, tests/evolve/test_prompts.py
Issue: none

Update the evolve prompt text and implementation command wiring so self-evolution stops telling itself to run bare `python -m pytest` in environments where `python` points to Python 2. Adjust the prompt builders in `src/nanobot/evolve/prompts.py` and the command selection in `src/nanobot/evolve/implementation.py` so they prefer `.venv/bin/python -m pytest` when available and otherwise fall back to `python3 -m pytest`. Extend `tests/evolve/test_prompts.py` to pin the generated command strings.

Why: the Day 3 assessment showed a false-red workflow where the project test suite passes under the supported interpreter but the evolve loop still instructs itself to use the wrong entrypoint. Fixing the command contract makes the self-improvement loop trustable again.

Verify with:
`python3 -m pytest tests/evolve/test_prompts.py -q`

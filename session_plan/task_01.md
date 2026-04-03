Title: Remove hardcoded pytest interpreter from fallback evolve prompts
Files: src/nanobot/evolve/prompts.py, tests/evolve/test_prompts.py
Issue: none

Update the default prompt templates in `src/nanobot/evolve/prompts.py` so the assessment, planning, and conflict-resolution fallback prompts stop telling the system to run `python -m pytest` directly. Keep the current workspace prompt file precedence unchanged, but make the built-in fallback text describe the configured pytest command generically instead of hardcoding an interpreter assumption that is wrong in this repo.

Touch the prompt-building paths that feed the fallback templates and add focused assertions in `tests/evolve/test_prompts.py` proving the rendered fallback prompts no longer contain the literal `python -m pytest` guidance. Verify with `python3 -m pytest tests/evolve/test_prompts.py -q`.

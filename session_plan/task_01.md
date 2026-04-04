Title: Unify pytest command resolution in evolve prompts
Files: src/nanobot/evolve/prompts.py, src/nanobot/evolve/implementation.py, tests/evolve/test_prompts.py
Issue: none

Introduce one shared pytest command resolution path for the self-evolution flow so this repo stops instructing itself to run `python -m pytest` on an environment where bare `python` points at Python 2. Update the default prompt templates in `DEFAULT_TEMPLATES`, the rendering path in `build_assessment_prompt()`, `build_implementation_prompt()`, and `build_conflict_resolution_prompt()`, plus the execution entrypoints `run_task_in_worktree()` and `run_implementation_serial()` so assessment, implementation, and conflict resolution all use the same resolved command.

Keep the change focused on consistency and operability: the assessment prompt, implementation prompt, and post-change verification should all agree on the same command string. Add regression coverage in `tests/evolve/test_prompts.py` that asserts the generated prompts include the resolved pytest command and no longer hardcode the broken `python -m pytest` fallback in this environment. Verify with `python3 -m pytest tests/evolve/test_prompts.py -q`.

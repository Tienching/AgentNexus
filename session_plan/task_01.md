Title: Fix evolution prompt pytest interpreter
Files: src/nanobot/evolve/prompts.py, tests/evolve/test_prompts.py
Issue: none

Update the built-in default prompt templates that still hardcode bare `python` for test execution. Start with `DEFAULT_TEMPLATES["assessment"]` in `src/nanobot/evolve/prompts.py`, and also fix any other default evolution prompt text in the same module that directly instructs pytest execution.

Why: the autonomous assessment contract currently fails in this repo because `/usr/bin/python` does not have pytest, while `python3 -m pytest tests/ -x -q --tb=short` passes. The planner should generate commands that match the supported interpreter instead of baking environment-sensitive failures into the default prompt.

Add a regression test in `tests/evolve/test_prompts.py` around `build_assessment_prompt()` that asserts the rendered prompt contains the Python 3 pytest command and still injects the evolve journal and memory paths correctly.

Verify with: `python3 -m pytest tests/evolve/test_prompts.py -q`.

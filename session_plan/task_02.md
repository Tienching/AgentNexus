Title: Remove inline DEFAULT_TEMPLATES from prompts.py
Files: src/nanobot/evolve/prompts.py
Issue: none

## Problem

The `prompts.py` file contains both inline `DEFAULT_TEMPLATES` (lines 19-24) and logic to load from external files. The external files already exist in `evolve/prompts/`:
- assessment.md
- planning.md
- implementation.md
- conflict_resolution.md
- skill.md
- reflection.md

The `load_prompt_template()` function loads external files first, then falls back to inline templates. The inline templates are now redundant and make the file harder to maintain.

## Solution

1. Remove the `DEFAULT_TEMPLATES` dict (lines 19-24) from `src/nanobot/evolve/prompts.py`
2. Update `load_prompt_template()` to raise a clear `FileNotFoundError` with the attempted paths if no prompt file is found
3. Keep `LEGACY_PROMPT_FILES` mapping for backward compatibility with old paths

This simplifies the code and ensures all prompts are externalized in `evolve/prompts/` where they can be easily edited.

## Verification

Run: `python3 -m pytest tests/evolve/test_prompts.py -v`

Tests should pass. Verify that loading each prompt works:
```python
from src.nanobot.evolve.prompts import load_prompt_template
from src.nanobot.evolve.models import EvolutionConfig
config = EvolutionConfig(working_dir=".")
for name in ["assessment", "planning", "implementation", "conflict_resolution"]:
    content = load_prompt_template(config, name)
    assert len(content) > 100  # Loaded from file, not empty
```

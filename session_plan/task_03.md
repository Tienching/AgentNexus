Title: Remove remaining scaffold TODO placeholders
Files: src/nanobot/skills/skill-creator/scripts/init_skill.py, tests/unit/test_init_skill.py
Issue: none

Tighten the generated skill scaffold so it starts from concrete starter guidance instead of unfinished TODO prose. Update the template constants `SKILL_TEMPLATE`, `EXAMPLE_SCRIPT`, and `EXAMPLE_REFERENCE`, plus the next-step output from `init_skill()`, so a newly generated skill explains what to fill in next without shipping placeholder text that looks incomplete.

Keep the scope small: do not redesign the scaffold, just replace the remaining placeholder wording with actionable defaults. Extend `tests/unit/test_init_skill.py` to assert generated `SKILL.md` and example resource files no longer contain the current TODO markers while still mentioning only the selected resource directories. Verify with `python3 -m pytest tests/unit/test_init_skill.py -q`.

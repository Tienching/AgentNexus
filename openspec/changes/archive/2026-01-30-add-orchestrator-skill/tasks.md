# Tasks: Add Orchestrator Skill

## Implementation

- [x] **Create Skill Directory Structure** <!-- id: 0 -->
    - `mkdir -p prompts/skills/orchestrator/scripts`
- [x] **Implement SKILL.md** <!-- id: 1 -->
    - Define "Chief Task Orchestrator" persona.
    - Define JSON output schema (`id`, `depends_on`, `title`, etc.).
    - Document usage of `orchestrator.py`.
- [x] **Implement orchestrator.py** <!-- id: 2 -->
    - Implement argument parsing (`--plan`).
    - Implement JSON parsing.
    - Implement `urllib` client for `/api/nexus/tasks`.
    - Implement dependency ID resolution logic.

## Validation

- [x] **Manual Test: Script Execution** <!-- id: 3 -->
    - Run `python3 prompts/skills/orchestrator/scripts/orchestrator.py --plan '{"tasks": [{"id": "t1", "title": "Test"}]}'`
    - Verify task appears in `GET /api/nexus/tasks`.
- [x] **Manual Test: Dependency Linking** <!-- id: 4 -->
    - Run script with a 2-step dependent plan.
    - Verify second task has correct `depends_on` UUID.

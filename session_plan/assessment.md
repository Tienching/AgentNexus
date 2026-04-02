# Assessment — Day 4

## Build/Test Status
- **Requested assessment command fails in this shell.** `python -m pytest tests/ -x -q --tb=short` exits before collection because `/usr/bin/python` has no `pytest` module installed.
- **Actual project test run is green.** `python3 -m pytest tests/ -x -q --tb=short` collected **1650** tests and passed **1650/1650** in **55.34s**.
- **Tooling contract is still inconsistent.** Project metadata requires Python 3.11+ (`pyproject.toml:6`), the green run here used Python 3.10.12, and pytest warns that `pytest.ini:1` overrides `pyproject.toml:83`.

## Recent Changes (last 3 commits)
- `5267309` Day 3: session wrap-up
- `8705d69` Day 3: Replace deprecated FastAPI 422 constants [worktree]
- `234c5e9` Day 3: Replace deprecated FastAPI 422 constants

Recent history is still mostly cleanup and operational hardening, not major orchestration expansion. The journal and active learnings show the same pattern: recent sessions focused on compatibility, installer execution, and health visibility (`JOURNAL.md:76`, `memory/active_learnings.md:5`).

## Codebase Size
- **Python source:** **69,043** lines under `src/`
- **Python modules:** **268**
- **Top-level distribution:** `src/channels/` 16, `src/nanobot/` 70, `src/providers/` 35, `src/runtime/` 77, `src/server/` 70
- **Requested subsystem counts:** `src/nanobot/mission/` 11, `src/nanobot/cron/` 3, `src/nanobot/agent/` 17, `src/runtime/` 77

Key entry points:
- API/lifecycle bootstrap: `src/server/app.py:65`
- CLI entrypoint: `src/runtime/plugins/cli/__init__.py:51`
- Agent loop: `src/nanobot/agent/loop.py:39`
- Mission orchestration: `src/nanobot/mission/service.py:24`, `src/nanobot/mission/planner.py:115`
- Cron scheduling: `src/nanobot/cron/service.py:63`
- Runtime task scheduler: `src/runtime/execution/scheduler.py:49`
- Self-evolution runtime: `src/nanobot/evolve/runtime.py:49`

## Self-Test Results
- Test breadth is strong. The suite covers evolve flows, integration/API behavior, provider adapters, channel integrations, task execution, storage, and scheduler/watchdog paths.
- No functional failures were found under the supported interpreter path used here (`python3`).
- The highest-value failure discovered is **inside the evolution system’s own verification path**: assessment, planning, conflict-resolution, and implementation code still hardcode `python -m pytest` commands (`src/nanobot/evolve/prompts.py:20`, `src/nanobot/evolve/prompts.py:21`, `src/nanobot/evolve/prompts.py:23`, `src/nanobot/evolve/implementation.py:189`, `src/nanobot/evolve/implementation.py:388`, `src/nanobot/evolve/implementation.py:409`). In this environment, that causes false-red self-assessment even though the suite passes.
- Pytest configuration is duplicated. `pytest.ini:1` is active, while `[tool.pytest.ini_options]` in `pyproject.toml:83` is ignored.

## Capability Gaps
1. **Self-evolution still uses the wrong test command**
   - The system that evaluates and improves the repo is wired to `python -m pytest`, not the interpreter that actually works here (`src/nanobot/evolve/prompts.py:20`, `src/nanobot/evolve/implementation.py:409`).
   - This directly undermines autonomous reliability: the platform can misclassify a healthy codebase as failing.

2. **Startup error handling still prefers “stay up” over a strong degraded-state contract**
   - `src/server/app.py:88` through `src/server/app.py:173` wraps executor, scheduler, channel service, terminal manager, and evolution startup in broad `try/except Exception` blocks.
   - `src/server/routers/health.py:195` improves visibility after boot, but the process can still come up partially broken without a hard failure or explicit startup-state surface.

3. **Evolution planning/output is still markdown-file driven instead of strongly typed**
   - `src/nanobot/evolve/runtime.py:110` expects `session_plan/assessment.md`, and `src/nanobot/evolve/runtime.py:144` through `src/nanobot/evolve/runtime.py:218` discovers and parses `task_*.md` files.
   - This is flexible, but fragile. Correctness depends on prompt format and filename conventions rather than a validated schema.

4. **Cron persistence failure handling is tolerant but lossy**
   - If cron store loading fails, `src/nanobot/cron/service.py:90` through `src/nanobot/cron/service.py:137` logs a warning and falls back to an empty `CronStore()`.
   - That keeps the service alive, but it also means malformed or corrupted schedule state can silently collapse into “no jobs loaded.”

5. **Documentation scaffolding still ships unfinished placeholders**
   - The generated skill template in `src/nanobot/skills/skill-creator/scripts/init_skill.py:25` and `src/nanobot/skills/skill-creator/scripts/init_skill.py:62` still contains multiple `[TODO: ...]` placeholders and example-only content.
   - That weakens documentation quality at the point new capabilities are created.

6. **API compatibility remains implicit rather than explicit**
   - The FastAPI app mounts a broad router set directly in `src/server/app.py:244`, while version metadata is repeated as string literals in `src/server/app.py:221` and `src/server/routers/health.py:208`.
   - The platform has a sizeable API surface, but no clear in-code versioning boundary or compatibility contract.

## Known Issues
- **Broken assessment/test command in evolve flow:** hardcoded `python -m pytest` remains in prompts and implementation (`src/nanobot/evolve/prompts.py:20`, `src/nanobot/evolve/implementation.py:409`).
- **Interpreter mismatch at repo boundary:** metadata targets Python 3.11+ (`pyproject.toml:6`), current green tests ran on 3.10.12, and default `python` in this environment is not the working project interpreter.
- **TODO scan has many false positives:** many hits are the runtime `TODO` task status (`src/runtime/models/task_models.py:46`, `src/runtime/stores/task_storage.py:31`), not unfinished work.
- **Actionable TODOs are concentrated in the skill scaffold:** `src/nanobot/skills/skill-creator/scripts/init_skill.py:25`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:32`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:62`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:124`.

## Recommended Focus
1. **Fix the self-evolution test contract first**
   - Replace hardcoded `python -m pytest` references in evolve prompts and implementation with the supported project test command.
   - Why: this is mission-critical infrastructure. The system cannot evolve itself reliably while its own self-check is wrong.

2. **Add a typed manifest alongside markdown planning artifacts**
   - Keep human-readable `session_plan/*.md`, but add validated machine-readable outputs around `src/nanobot/evolve/runtime.py:110` and `src/nanobot/evolve/runtime.py:188`.
   - Why: the evolution pipeline is central, and its current I/O contract is too easy to break with prompt drift.

3. **Make degraded startup and persistence failures explicit**
   - Tighten boot-time failure signaling in `src/server/app.py:88` and decide whether cron-store load failures in `src/nanobot/cron/service.py:90` should fail fast, surface degraded health, or require operator action.
   - Why: operability is improving, but the current contract still hides partial failure states.

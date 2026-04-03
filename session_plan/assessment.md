# Assessment — Day 9

## Build/Test Status
- **Mixed.** The exact assessment command is red in this shell: `python -m pytest tests/ -x -q --tb=short` fails immediately with `/usr/bin/python: No module named pytest`.
- **Actual project status is green on the usable interpreter here.** `python3 -m pytest tests/ -x -q --tb=short` ran on Python 3.10.12 and passed **1656/1656** tests in **54.55s**.
- **Environment drift is still real.** Package metadata requires Python 3.11+ (`pyproject.toml:6`), but the passing suite in this environment is running on 3.10.12.
- **Pytest config is duplicated.** The run emitted `configfile: pytest.ini (WARNING: ignoring pytest config in pyproject.toml!)`, which means `pytest.ini:1-11` currently overrides `pyproject.toml:83-90`.

## Recent Changes (last 3 commits)
- `2bc28aa` Day 8: session wrap-up
- `26a6615` Day 8: Make generated skill scaffolds actionable by default [worktree]
- `5bf9295` Day 8: Make generated skill scaffolds actionable by default

Context from recent history is consistent: `memory/active_learnings.md:33-38` records the Day 8 scaffold work, and the journal tail shows the follow-up pytest-interpreter fix was attempted but not landed (`JOURNAL.md:301-305`).

## Codebase Size
- **Python source:** **69,070** lines under `src/`
- **Python modules:** **268**
- **Top-level package split:** `channels/` 16, `nanobot/` 70, `providers/` 35, `runtime/` 77, `server/` 70
- **Requested key module counts:** `src/nanobot/mission/` 11, `src/nanobot/cron/` 3, `src/nanobot/agent/` 17, `src/runtime/` 77

Key entry points:
- API/lifecycle bootstrap: `src/server/app.py:65`
- CLI entrypoint: `src/runtime/plugins/cli/__init__.py:51`
- Core agent loop: `src/nanobot/agent/loop.py:39`
- Mission orchestration API: `src/nanobot/mission/service.py:24`
- Mission planning and DAG runner: `src/nanobot/mission/planner.py:115`, `src/nanobot/mission/runner.py:22`
- Cron scheduler/service: `src/nanobot/cron/service.py:63`
- Runtime task executor and scheduler: `src/runtime/execution/task_executor.py:39`, `src/runtime/execution/scheduler.py:49`
- Self-evolution runtime: `src/nanobot/evolve/runtime.py:49`

## Self-Test Results
- The suite is broad and currently healthy on `python3`: evolve flows, integration APIs, provider routing, channel integrations, runtime scheduling, storage, notifications, and task execution all passed.
- The HTTP server is a single FastAPI bootstrap that starts executor, scheduler, channels, terminal management, and evolution services from one lifespan function (`src/server/app.py:65-175`).
- Mission support is substantive, not skeletal: `MissionService` wires planning, execution, persistence, and notifications (`src/nanobot/mission/service.py:24-61`); `MissionPlanner` emits milestone/task DAGs and injects review/test steps (`src/nanobot/mission/planner.py:123-339`); `MissionRunner` executes ready milestones/tasks concurrently and runs milestone validation commands (`src/nanobot/mission/runner.py:47-454`).
- The runtime execution layer is also real and separate from mission logic: `TaskExecutor` manages queue polling, retries, and workspace concurrency (`src/runtime/execution/task_executor.py:88-370`), while `TaskScheduler` turns schedules into generated tasks and runs the stale-task watchdog (`src/runtime/execution/scheduler.py:92-286`).
- The only concrete failures discovered in this assessment were tooling-contract failures, not functional regressions: the scripted `python` test command is wrong here, and pytest configuration is drifting between two files.

## Capability Gaps
1. **Self-evolution verification is still not environment-safe.**
   - The built-in assessment prompt still tells the system to run `python -m pytest ...` (`src/nanobot/evolve/prompts.py:20-23`).
   - Serial implementation verification also hardcodes the same command (`src/nanobot/evolve/implementation.py:382-409`).
   - Result: agent-nexus can falsely mark itself unhealthy even when the real suite is green.

2. **The self-evolution pipeline still depends on markdown side effects instead of typed artifacts.**
   - Assessment success is inferred from `session_plan/assessment.md` existing (`src/nanobot/evolve/runtime.py:110-139`).
   - Planning then discovers `task_*.md` files and parses them line-by-line into `EvolutionTask` objects (`src/nanobot/evolve/runtime.py:144-218`).
   - This is flexible, but it is brittle under prompt drift and hard to validate mechanically.

3. **Public API/runtime compatibility is still implicit and duplicated.**
   - The server mounts a broad router surface directly in one module (`src/server/app.py:244-261`).
   - Version strings are repeated across API, health, CLI, parser, and run protocol code (`src/server/app.py:224`, `src/server/routers/health.py:211`, `src/runtime/plugins/cli/__init__.py:35`, `src/runtime/plugins/cli/parser.py:41`, `src/server/services/run_service.py:37`).
   - There is no clear single compatibility boundary or single source of truth for public version metadata.

4. **Documentation generation is still incomplete at the scaffold boundary.**
   - `init_skill.py` still emits SKILL.md templates with unresolved TODO placeholders and example text (`src/nanobot/skills/skill-creator/scripts/init_skill.py:23-108`).
   - The validator explicitly rejects those placeholders later (`src/nanobot/skills/skill-creator/scripts/quick_validate.py:118-129`).
   - So Day 8 improved the scaffold flow, but new skills still begin from partially unfinished documentation.

5. **Cron corruption handling is visible now, but still lossy.**
   - On parse failure, `CronService` logs the error, marks degraded state, and falls back to an empty in-memory store (`src/nanobot/cron/service.py:92-145`).
   - Status exposes the degradation (`src/nanobot/cron/service.py:417-425`), but jobs effectively disappear until the store is repaired.

6. **Coverage tooling exists, but coverage is not part of the default quality gate.**
   - `pytest-cov` is declared in dev dependencies (`pyproject.toml:35-41`, `pyproject.toml:61-69`) and a coverage source list exists (`pyproject.toml:88-90`).
   - The default pytest options do not enforce coverage (`pytest.ini:1-11`), so test breadth is strong but minimum coverage is not being checked in the standard workflow.

## Known Issues
- **Broken assessment/test command in the evolve flow:** `src/nanobot/evolve/prompts.py:20-23`, `src/nanobot/evolve/implementation.py:382-409`
- **Pytest configuration drift warning:** `pytest.ini:1-11`, `pyproject.toml:83-90`
- **Real TODOs are concentrated in generated skill content, not core runtime logic:** `src/nanobot/skills/skill-creator/scripts/init_skill.py:25`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:32`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:64`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:124`
- **TODO/FIXME/HACK search is noisy because many hits are the `TaskStatus.TODO` state, not unfinished work** (`src/runtime/models/task_models.py`, `src/runtime/stores/task_storage.py`)
- **Version metadata is duplicated in multiple entry surfaces:** `src/server/app.py:224`, `src/server/routers/health.py:211`, `src/runtime/plugins/cli/__init__.py:35`, `src/runtime/plugins/cli/parser.py:41`, `src/server/services/run_service.py:37`

## Recommended Focus
1. **Fix pytest command resolution across evolve prompts and runtime.**
   - Replace hardcoded `python -m pytest` with a single resolved command shared by assessment, implementation, and conflict resolution.
   - Why: self-verification is the foundation of safe self-improvement.

2. **Add a typed manifest for assessment/planning alongside markdown.**
   - Keep `session_plan/*.md` for readability, but emit and parse a machine-validated artifact from `src/nanobot/evolve/runtime.py:110-218`.
   - Why: this reduces prompt-format fragility without losing human-readable plans.

3. **Reduce metadata/config drift in the public surface.**
   - Centralize version reporting and choose one pytest configuration source of truth.
   - Why: agent-nexus already has a broad surface area; operational consistency now matters more than another new feature.

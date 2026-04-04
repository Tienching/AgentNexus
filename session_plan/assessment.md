# Assessment — Day 10

## Build/Test Status
- **Green on the usable interpreter.** `python3 -m pytest tests/ -x -q --tb=short` passed **1656/1656** tests on Python 3.10.12.
- **Interpreter contract is still inconsistent.** In this environment, bare `python` still resolves to Python 2.7.18, while `pyproject.toml` declares `requires-python = ">=3.11"` (`pyproject.toml:6`).
- **Pytest config is duplicated.** The run warns that `pytest.ini` is being used while `[tool.pytest.ini_options]` in `pyproject.toml` is ignored (`pytest.ini:1-11`, `pyproject.toml:83-90`).
- Bottom line: the codebase is currently test-green, but the self-test command contract is brittle.

## Recent Changes (last 3 commits)
- `d75b59a` Day 9: session wrap-up
- `e798b02` Day 9: session plan
- `2bc28aa` Day 8: session wrap-up

Context:
- The latest visible commits are planning/wrap-up commits, not new feature work.
- `memory/active_learnings.md:33-38` shows the last substantive improvement was Day 8: generated skill scaffolds were made more actionable.
- The tail of `JOURNAL.md` still highlights unresolved issues around duplicated version metadata, scaffold documentation placeholders, lossy cron degradation, and missing coverage gating (`JOURNAL.md:373-389`).

## Codebase Size
- **Python source under `src/`:** 69,071 lines across **268** modules.
- **Top-level structure:** `channels/`, `nanobot/`, `providers/`, `runtime/`, `server/`.
- **Requested key module counts:**
  - `src/nanobot/mission/`: 11 modules
  - `src/nanobot/cron/`: 3 modules
  - `src/nanobot/agent/`: 17 modules
  - `src/runtime/`: 77 modules
- **Entry points / architectural anchors:**
  - Console entrypoint is the `anexus` script in `pyproject.toml:31-33`, implemented by `src/runtime/plugins/cli/__init__.py:51`.
  - FastAPI application bootstrap is `src/server/app.py:221`.
  - Core agent loop is `src/nanobot/agent/loop.py:39`.
  - Mission orchestration API is `src/nanobot/mission/service.py:24`.
  - Cron service is `src/nanobot/cron/service.py:63`.
  - Runtime scheduler bootstrap is `src/runtime/execution/scheduler.py:273`.
- There are **no** `__main__.py` module entrypoints under `src/`; the project is entered through packaging scripts and server bootstrap.

## Self-Test Results
- The current suite is broad and healthy: evolve flows, integration APIs, provider routing, channels, runtime scheduling, storage, notifications, and task execution all passed.
- `src/server/app.py` is the main system composition root. Its lifespan bootstraps the task executor, task scheduler, channel service, terminal manager, and evolution service from one place (`src/server/app.py:65-175`).
- The mission stack is substantive:
  - `MissionService` wires persistence, planning, execution, and notifications (`src/nanobot/mission/service.py:24-61`).
  - `MissionPlanner` uses an LLM tool call to produce milestone/task plans and injects reviewer/tester tasks (`src/nanobot/mission/planner.py:17-95`, `src/nanobot/mission/planner.py:273-306`).
  - `AgentLoop` integrates sessions, memory consolidation, tool execution, spawning, web tools, mission tools, and optional cron tooling (`src/nanobot/agent/loop.py:53-165`, `src/nanobot/agent/loop.py:214-366`).
- The runtime layer is also mature:
  - `TaskScheduler` spawns generated tasks from schedules and runs the stale-task watchdog (`src/runtime/execution/scheduler.py:49-56`, `src/runtime/execution/scheduler.py:172-254`).
  - `CronService` persists jobs, tracks degraded state on store parse failure, and exposes service status (`src/nanobot/cron/service.py:82-151`, `src/nanobot/cron/service.py:417-425`).
- I did **not** find a current failing test. The issues discovered today are mostly contract/operability issues rather than functional regressions.

## Capability Gaps
1. **Self-verification still hardcodes the wrong test command.**
   - The assessment prompt still instructs `python -m pytest ...` (`src/nanobot/evolve/prompts.py:20`).
   - The implementation flow hardcodes the same command in multiple places (`src/nanobot/evolve/implementation.py:189`, `src/nanobot/evolve/implementation.py:388`, `src/nanobot/evolve/implementation.py:409`).
   - Because the environment’s bare `python` is not the project’s working interpreter, self-evolution can misdiagnose the repo.

2. **Mission DAG validation stops at the task level.**
   - `MissionPlanner._validate_plan()` validates task descriptions, intra-milestone task dependencies, and cycles within a single milestone (`src/nanobot/mission/planner.py:211-271`).
   - I did not see equivalent validation for `Milestone.depends_on` references or cross-milestone cycles, even though milestone dependencies are part of the planner schema (`src/nanobot/mission/planner.py:52-56`, `src/nanobot/mission/planner.py:194-203`).
   - For an orchestration platform, this is a real scheduling-quality gap.

3. **Service startup error handling favors availability over observability.**
   - `src/server/app.py` logs and continues if executor, scheduler, channel service, terminal manager, or evolution service startup fails (`src/server/app.py:88-173`).
   - That is pragmatic, but it means partial boot failure can be easy to miss unless health/status surfaces are checked carefully.

4. **Documentation quality is still weak at the scaffold boundary.**
   - The skill scaffold generator still contains unresolved TODO placeholders and stub logic (`src/nanobot/skills/skill-creator/scripts/init_skill.py:25`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:32`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:64`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:124`).
   - Day 8 improved the flow, but the generated artifact still begins from partially unfinished documentation.

5. **Quality gates emphasize breadth, not coverage policy.**
   - Test breadth is strong, but coverage is not enforced by default: coverage config exists in `pyproject.toml` (`pyproject.toml:88-90`) while the active pytest config in `pytest.ini` does not require coverage thresholds (`pytest.ini:1-11`).
   - This makes regressions less likely, but leaves “untested enough” undefined.

6. **Version metadata is duplicated across public surfaces.**
   - `0.1.0` appears in runtime package metadata, CLI version output, FastAPI app metadata, health responses, and run protocol metadata (`src/runtime/__init__.py:18`, `src/runtime/plugins/cli/__init__.py:35`, `src/runtime/plugins/cli/parser.py:41`, `src/server/app.py:224`, `src/server/routers/health.py:211`, `src/server/services/run_service.py:37`).
   - That increases drift risk as the platform surface grows.

## Known Issues
- **Hardcoded `python -m pytest` in self-evolution paths:** `src/nanobot/evolve/prompts.py:20`, `src/nanobot/evolve/implementation.py:189`, `src/nanobot/evolve/implementation.py:388`, `src/nanobot/evolve/implementation.py:409`
- **Duplicate pytest configuration sources causing warning:** `pytest.ini:1-11`, `pyproject.toml:83-90`
- **Real TODOs are concentrated in generated skill scaffold content, not the requested core modules:** `src/nanobot/skills/skill-creator/scripts/init_skill.py:25`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:32`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:64`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:124`
- **TODO/FIXME/HACK scanning is noisy because many hits are the literal `TaskStatus.TODO` state, not unfinished engineering work** (`src/runtime/models/task_models.py:39`, `src/runtime/stores/task_storage.py:210`)
- **Cron degraded-state behavior is visible but still lossy on parse failure:** `src/nanobot/cron/service.py:139-145`, `src/nanobot/cron/service.py:417-425`

## Recommended Focus
1. **Fix interpreter/test-command resolution in the evolution pipeline.**
   - Replace hardcoded `python -m pytest` with one shared, resolved pytest command used by assessment, implementation, and conflict resolution.
   - Why: self-verification is the foundation of safe self-improvement.

2. **Add milestone-level DAG validation in `MissionPlanner`.**
   - Validate `Milestone.depends_on` references and detect cross-milestone cycles, then cover it with focused tests.
   - Why: task-level DAG safety is good; orchestration-level DAG safety is still incomplete.

3. **Reduce configuration and metadata drift.**
   - Pick one pytest config source of truth and centralize version metadata used by CLI, API, and health surfaces.
   - Why: the platform already has a wide public surface, so consistency now matters as much as new features.

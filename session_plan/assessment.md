# Assessment — Day 13

## Build/Test Status
- **Requested command:** `python -m pytest tests/ -x -q --tb=short` fails immediately in this environment with `/usr/bin/python: No module named pytest`.
- **Supported interpreter:** `python3 -m pytest tests/ -x -q --tb=short` passes cleanly.
- `python3 -m pytest tests/ --collect-only -q` reports **1679 collected tests**, so the source tree is green on Python 3, but the default self-evolution test entrypoint is still brittle.

## Recent Changes (last 3 commits)
- `941ebdc` Day 12: session wrap-up
- `7c42c10` Day 12: Reuse runtime version in API health surfaces [worktree]
- `cc1eb0a` Day 12: Align packaging metadata with the tested source tree [worktree]

Recent journal/memory context matches that history: the last few sessions have focused on surfacing subsystem health, tightening router/service boundaries, and keeping package metadata aligned with the tested runtime.

## Codebase Size
- `src/` contains **69,519** Python lines across **268** modules.
- Requested key-module counts:
  - `src/nanobot/mission/`: **11** modules
  - `src/nanobot/cron/`: **3** modules
  - `src/nanobot/agent/`: **17** modules
  - `src/runtime/`: **77** modules
- Supporting API surface is also large: `src/server/routers/` has **25** modules and `src/server/services/` has **32** modules.
- Key entry points:
  - FastAPI bootstrap: `src/server/app.py:394`
  - CLI entrypoint: `src/runtime/plugins/cli/__init__.py:51`
  - Agent loop: `src/nanobot/agent/loop.py:39`
  - Mission orchestration: `src/nanobot/mission/service.py:24`
  - Mission planning: `src/nanobot/mission/planner.py:115`
  - Cron service: `src/nanobot/cron/service.py:63`
  - Runtime scheduler: `src/runtime/execution/scheduler.py:49`
  - Evolution engine: `src/nanobot/evolve/runtime.py:49`

## Self-Test Results
- The Python 3 run passed end to end. No failing tests surfaced.
- Test breadth is strong: the collected suite covers evolve flows, integration APIs, provider routing, channels, health checks, missions, runtimes, storage, schedulers/watchdogs, and worktree behavior.
- The codebase is structurally substantial rather than scaffold-only:
  - `src/server/app.py:98` wires executor, scheduler, channels, terminal manager, and evolution startup into the FastAPI lifespan.
  - `src/nanobot/agent/loop.py:53` builds the main orchestration loop around sessions, tools, missions, cron, MCP, and concurrent message handling.
  - `src/nanobot/mission/planner.py:123` decomposes goals into milestone/task DAGs and validates dependency graphs in `src/nanobot/mission/planner.py:211`.
  - `src/runtime/execution/scheduler.py:127` runs a background polling loop plus stale-task watchdog.
- The main self-test weakness is environmental and prompt-driven, not a red test suite: default evolve prompts still tell the system to run the broken bare-`python` pytest command in `src/nanobot/evolve/prompts.py:19`.

## Capability Gaps
1. **Startup error handling is observable but still permissive.**
   - Required subsystems are started behind broad exception handling in `src/server/app.py:123` through `src/server/app.py:337`.
   - Health reporting now exposes that state cleanly in `src/server/routers/health.py:206` through `src/server/routers/health.py:288`.
   - That is good operational visibility, but the process contract is still “stay up in degraded mode” rather than “fail fast when core services are broken.”

2. **The self-evolution control plane is still file-contract driven and environment-sensitive.**
   - Assessment expects `session_plan/assessment.md` and planning parses `task_*.md` files line-by-line in `src/nanobot/evolve/runtime.py:110` through `src/nanobot/evolve/runtime.py:188`.
   - If planning emits nothing usable, the engine falls back to a generic catch-all task in `src/nanobot/evolve/runtime.py:169`.
   - Prompt templates still hardcode shell behavior in `src/nanobot/evolve/prompts.py:19`, including the wrong pytest entrypoint for this repo.

3. **Internal API stability is better at the router layer, but some service boundaries still depend on private internals.**
   - `src/server/services/stale_task_watchdog.py:37` through `src/server/services/stale_task_watchdog.py:45` reaches into `executor._running_tasks`.
   - The same watchdog mutates queue internals directly via `_redis` and `_update_task_status` in `src/server/services/stale_task_watchdog.py:113` through `src/server/services/stale_task_watchdog.py:150`.
   - That works today, but it couples server services tightly to runtime storage implementation details.

4. **Version/compatibility metadata is improved, but not fully centralized.**
   - The API now uses `runtime_version` in `src/server/app.py:394` and `src/server/routers/health.py:282`.
   - But runtime, CLI, and packaging still each define version information separately in `src/runtime/__init__.py:18`, `src/runtime/plugins/cli/__init__.py:35`, and `pyproject.toml:3`.
   - That leaves room for future drift between what the package declares and what the CLI/API report.

## Known Issues
- **Obvious current bug:** the exact assessment/self-test command still fails in this environment because `python` does not resolve to a pytest-capable interpreter. The default evolve prompt still embeds that command in `src/nanobot/evolve/prompts.py:19`.
- **Mission failure path is incomplete:** if `MissionRunner` raises an unexpected exception, `MissionService` logs it in `src/nanobot/mission/service.py:195` but does not mark the mission failed before cleanup in `src/nanobot/mission/service.py:197`. That can leave error state under-surfaced.
- **TODO/FIXME/HACK search is noisy:** most grep hits are not backlog markers but legitimate `TaskStatus.TODO` references in task models/storage, such as `src/runtime/models/task_models.py:46` and `src/runtime/stores/task_storage.py:31`. Real unresolved markers in source are sparse; the meaningful functional one is the evolve prompt’s hardcoded test command.
- **Scaffold/documentation quality is guarded, not guaranteed:** `src/nanobot/skills/skill-creator/scripts/quick_validate.py:118` through `src/nanobot/skills/skill-creator/scripts/quick_validate.py:129` explicitly rejects TODO placeholder text, which is good, but it also shows generated skill docs still rely on validation to stay clean.

## Recommended Focus
1. **Fix the self-evolution pytest command everywhere it is hardcoded.**
   - Highest leverage because it directly affects autonomous assessment, implementation, and conflict-resolution reliability.
   - Primary file: `src/nanobot/evolve/prompts.py:19`.

2. **Harden mission failure-state reporting.**
   - Ensure unexpected runner exceptions transition missions to a durable failed state with stored error details instead of only logging.
   - Primary file: `src/nanobot/mission/service.py:187`.

3. **Replace remaining watchdog/runtime private-member coupling with public APIs.**
   - This would reduce cross-layer fragility and make the scheduler/watchdog path safer to refactor.
   - Primary file: `src/server/services/stale_task_watchdog.py:30`.

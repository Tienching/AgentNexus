# Assessment — Day 15

## Build/Test Status
- **Mixed entrypoint health:** the exact requested command, `python -m pytest tests/ -x -q --tb=short`, fails in this environment before test collection with `/usr/bin/python: No module named pytest`.
- **Green on supported interpreter:** `python3 -m pytest tests/ -q --tb=short` passed cleanly.
- `python3 -m pytest tests/ --collect-only -o addopts=` reports **1,686 collected tests**.
- Current package metadata targets Python 3.10+ in `pyproject.toml:6`, but the built-in evolution assessment prompt still hardcodes bare `python` in `src/nanobot/evolve/prompts.py:20`.

## Recent Changes (last 3 commits)
- `349ca22` Day 14: session wrap-up
- `2629806` Day 14: Replace watchdog private runtime coupling [worktree]
- `4333513` Day 14: Persist unexpected mission runner failures [worktree]

Recent journal context is consistent with that history. The latest Day 14 entry still flags three unresolved themes: self-evolution command correctness, mission workspace isolation, and startup contract clarity (`JOURNAL.md:597`-`JOURNAL.md:617`).

## Codebase Size
- `src/` contains **69,587** Python lines across **268** modules.
- Top-level module distribution:
  - `src/runtime/`: **77** modules
  - `src/server/`: **70** modules
  - `src/nanobot/`: **70** modules
  - `src/providers/`: **35** modules
  - `src/channels/`: **16** modules
- Requested key-module breakdown:
  - `src/nanobot/mission/`: **11** modules
  - `src/nanobot/cron/`: **3** modules
  - `src/nanobot/agent/`: **17** modules
  - `src/runtime/`: **77** modules
- Key entry points:
  - FastAPI app bootstrap: `src/server/app.py:394`
  - App lifespan / subsystem startup: `src/server/app.py:98`
  - Agent loop: `src/nanobot/agent/loop.py:39`
  - Mission service: `src/nanobot/mission/service.py:24`
  - Mission planner: `src/nanobot/mission/planner.py:115`
  - Cron service: `src/nanobot/cron/service.py:63`
  - Runtime task scheduler: `src/runtime/execution/scheduler.py:49`
  - Evolution engine: `src/nanobot/evolve/runtime.py:49`

## Self-Test Results
- The real suite is healthy on the supported interpreter: **1,686/1,686 tests passed** with `python3 -m pytest tests/ -q --tb=short`.
- The failure is not product behavior; it is the autonomous verification contract. The assessment prompt still instructs the system to use the wrong interpreter in `src/nanobot/evolve/prompts.py:20`.
- The core orchestration surfaces are substantial and exercised:
  - `src/server/app.py:98` starts executor, scheduler, channel service, terminal manager, and evolution service from one FastAPI lifespan.
  - `src/nanobot/agent/loop.py:53` composes sessions, tools, missions, cron, MCP, and concurrent request handling.
  - `src/nanobot/mission/planner.py:211` validates milestone and task dependency graphs before execution.
  - `src/runtime/execution/scheduler.py:127` runs both schedule polling and the stale-task watchdog.

## Capability Gaps
1. **Self-evolution is still environment-sensitive and file-contract driven.**
   - Assessment and planning still depend on writing and reparsing markdown files in `src/nanobot/evolve/runtime.py:110` and `src/nanobot/evolve/runtime.py:144`-`src/nanobot/evolve/runtime.py:188`.
   - If planning emits nothing usable, the engine falls back to a generic task in `src/nanobot/evolve/runtime.py:169`.
   - The default assessment prompt still hardcodes the broken bare-`python` test command in `src/nanobot/evolve/prompts.py:20`.

2. **Mission workspace isolation is incomplete.**
   - `MissionBridge` is a singleton in `src/server/services/mission_bridge.py:24`.
   - Request-scoped workspace overrides mutate shared service state in `src/server/services/mission_bridge.py:80`-`src/server/services/mission_bridge.py:83` and `src/server/services/mission_bridge.py:96`-`src/server/services/mission_bridge.py:99`.
   - `MissionRunner` captures its `store` at construction in `src/nanobot/mission/runner.py:25`-`src/nanobot/mission/runner.py:35`, so bridge-level store rebinding does not propagate to the runner.

3. **Startup handling is observable, but the contract is still permissive.**
   - `src/server/app.py:123`-`src/server/app.py:337` catches subsystem startup failures and keeps the API process alive.
   - That is pragmatic, but it leaves the platform in “degraded but running” mode for required services unless operators inspect startup state explicitly.

4. **Version/API identity is still split across packages.**
   - Runtime exposes `0.1.0` in `src/runtime/__init__.py:18`.
   - CLI also exposes `0.1.0` in `src/runtime/plugins/cli/__init__.py:35`.
   - Nanobot still reports `0.1.4.post5` in `src/nanobot/__init__.py:5`.
   - Packaging metadata says `0.1.0` in `pyproject.toml:3`. That is manageable now, but it invites drift as API and dashboard surfaces grow.

## Known Issues
- **Confirmed bug:** the built-in assessment prompt still tells the system to run the wrong pytest entrypoint in `src/nanobot/evolve/prompts.py:20`.
- **Likely mission bug:** workspace overrides in `src/server/services/mission_bridge.py:80`-`src/server/services/mission_bridge.py:83` and `src/server/services/mission_bridge.py:96`-`src/server/services/mission_bridge.py:99` do not update the runner store held in `src/nanobot/mission/runner.py:35`.
- **No meaningful comment backlog surfaced in `src/`.** A targeted `# TODO|FIXME|HACK` scan returned no real unresolved engineering comments. Most broad matches were false positives from `TaskStatus.TODO` strings rather than actionable code markers.
- **Test/coverage policy is broad but not explicit.** `pytest.ini:8` defines strict default pytest behavior, and coverage sources exist in `pyproject.toml:83`-`pyproject.toml:88`, but there is no enforced coverage threshold in the default test gate.

## Recommended Focus
1. **Fix the self-evolution test command first.**
   - Align the assessment/planning prompts with the interpreter that actually passes in this repo, starting at `src/nanobot/evolve/prompts.py:20`.

2. **Repair MissionBridge workspace isolation and add regression coverage.**
   - Make workspace selection request-scoped, or fully rebind all mission-service dependencies including the runner store.
   - Primary files: `src/server/services/mission_bridge.py:24` and `src/nanobot/mission/runner.py:25`.

3. **Decide and codify the startup failure policy.**
   - If executor, scheduler, channel service, terminal manager, and evolution are required, boot should fail loudly. If degraded mode is intended, expose it as a first-class contract instead of an implementation side effect.
   - Primary file: `src/server/app.py:98`.

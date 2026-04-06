# Assessment — Day 16

## Build/Test Status
- The exact requested assessment command still fails immediately in this environment: `/usr/bin/python: No module named pytest`. The autonomous assessment prompt still encodes that broken entrypoint in `src/nanobot/evolve/prompts.py:20`.
- The supported interpreter is `python3`, but the suite is not green today. `python3 -m pytest tests/ -x --tb=short` stops at **1 error after 909 passed** in **34.45s**.
- `python3 -m pytest tests/ --collect-only -q` reports **1,690 collected tests** across **76 test files**.
- The first failing test is `tests/unit/test_nexus_admin.py:30`. Startup aborts in `src/server/app.py:372` because the task scheduler is marked unhealthy when the task executor is disabled in the active settings path (`src/server/app.py:188-205`).

## Recent Changes (last 3 commits)
- `18aee80` Day 15: session wrap-up
- `c440c9e` Day 15: Codify startup failure policy for required subsystems [worktree]
- `ef81961` Day 15: Rebind mission runner state for workspace overrides [worktree]

The current tree reflects those themes: startup now fails fast on required subsystem failures in `src/server/app.py:348-375`, and mission workspace rebinding now reaches the runner via `src/server/services/mission_bridge.py:80-88` and `src/nanobot/mission/runner.py:39-56`.

## Codebase Size
- `src/` contains **69,657 Python lines** across **268 modules**.
- Top-level breakdown:
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
  - FastAPI app bootstrap: `src/server/app.py:423`
  - API router assembly: `src/server/app.py:446-463`
  - CLI entrypoint: `src/runtime/plugins/cli/__init__.py:51`
  - Agent loop: `src/nanobot/agent/loop.py:39`
  - Mission service: `src/nanobot/mission/service.py:24`
  - Cron service: `src/nanobot/cron/service.py:63`
  - Evolution engine: `src/nanobot/evolve/runtime.py:49`

## Self-Test Results
- The failure is in application bootstrap, not in the `/api/nexus/diagnostics` handler body. `TestClient(app)` in `tests/unit/test_nexus_admin.py:17` triggers the FastAPI lifespan, which now aggregates required subsystem failures and raises at `src/server/app.py:367-375`.
- The concrete failure path is: executor disabled -> scheduler marked unhealthy at `src/server/app.py:188-205` -> API startup refused at `src/server/app.py:372`.
- This looks like a test-isolation/configuration problem more than a diagnostics feature regression. Settings are instantiated eagerly in `src/server/config.py:253`, and the suite imports the app eagerly in `tests/conftest.py:7`, so ambient environment can affect startup before test-local monkeypatching.
- Broadly, the platform still has clear architectural entry points: mission orchestration in `src/nanobot/mission/service.py:24-60`, agent execution/tooling in `src/nanobot/agent/loop.py:53-165`, cron scheduling in `src/nanobot/cron/service.py:63-217`, and self-evolution control flow in `src/nanobot/evolve/runtime.py:110-186`.

## Capability Gaps
1. **Self-evolution verification is still environment-unsafe.**
   - The default assessment, planning, and conflict-resolution prompts still hardcode bare `python`/shell commands in `src/nanobot/evolve/prompts.py:20-23`.
   - Worktree implementation partly prefers `.venv/bin/python` in `src/nanobot/evolve/implementation.py:185-190`, but the serial path still hardcodes bare `python` in `src/nanobot/evolve/implementation.py:388-409`.
   - Result: agent-nexus can still misdiagnose itself before the real test suite runs.

2. **The self-evolution control plane is still markdown/file-contract driven.**
   - Assessment success is inferred from `session_plan/assessment.md` in `src/nanobot/evolve/runtime.py:130-136`.
   - Planning reparses `task_*.md` files line-by-line in `src/nanobot/evolve/runtime.py:162-218`.
   - If nothing usable is emitted, the engine falls back to a generic catch-all task in `src/nanobot/evolve/runtime.py:169-181`.
   - This is flexible, but fragile under prompt drift and hard to validate mechanically.

3. **API bootstrap and tests are tightly coupled to ambient configuration.**
   - The new startup policy is explicit and better than silent degradation, but it now exposes how much the app depends on import-time settings and real environment state.
   - `settings = Settings()` is created at import time in `src/server/config.py:253`, the app is imported in `tests/conftest.py:7`, and required startup checks execute in `src/server/app.py:98-375`.
   - That makes endpoint tests less hermetic than they should be.

4. **Mission workspace isolation is improved, but still shared-state based.**
   - `MissionBridge` remains a singleton in `src/server/services/mission_bridge.py:24`.
   - Workspace overrides still mutate one shared service instance in-place in `src/server/services/mission_bridge.py:70-95`, then request handlers reuse that same service in `src/server/services/mission_bridge.py:98-123`.
   - The runner rebinding fix helps correctness, but concurrent multi-workspace requests can still contend on shared mutable state.

5. **Version and compatibility identity are still split across packages.**
   - Runtime reports `0.1.0` in `src/runtime/__init__.py:18`.
   - CLI reports `0.1.0` in `src/runtime/plugins/cli/__init__.py:35`.
   - Nanobot reports `0.1.4.post5` in `src/nanobot/__init__.py:5`.
   - Packaging metadata reports `0.1.0` in `pyproject.toml:2-6`.
   - This is survivable, but it invites drift as public API and dashboard surfaces grow.

6. **Coverage tooling exists, but coverage is not part of the default quality gate.**
   - `pytest-cov` is present in `pyproject.toml:35-41` and coverage sources are configured in `pyproject.toml:83-88`.
   - The active pytest defaults in `pytest.ini:1-12` do not enforce a coverage threshold.
   - The suite is large, but “enough coverage” is still policy-free.

## Known Issues
- A targeted `TODO/FIXME/HACK` scan found very little real comment debt. Most hits are false positives from `TaskStatus.TODO` usage in runtime task code, not unresolved engineering markers.
- The one clear actionable hit is the self-evolution assessment prompt embedding the broken bare-`python` test command in `src/nanobot/evolve/prompts.py:20`.
- There is a confirmed current regression in API test startup: `tests/unit/test_nexus_admin.py:30` fails because the app now refuses to start when required subsystems are unhealthy (`src/server/app.py:367-375`).
- `memory/active_learnings.md` currently stops at Day 14, while git history and `JOURNAL.md` have Day 15 entries. Self-memory continuity is lagging recent work.

## Recommended Focus
1. **Fix self-evolution pytest command resolution end-to-end.**
   Update prompt templates and serial verification so assessment, planning, implementation, and conflict resolution all use the interpreter that actually works here. Primary files: `src/nanobot/evolve/prompts.py:20-23` and `src/nanobot/evolve/implementation.py:185-190,388-409`.

2. **Make API tests hermetic against startup configuration.**
   Introduce an app-factory or test bootstrap path that sets executor/scheduler/evolution flags before app import, so diagnostics/admin tests validate endpoint behavior instead of ambient host settings. Primary files: `src/server/config.py:253`, `src/server/app.py:98-375`, and `tests/conftest.py:7`.

3. **Replace the markdown-only evolution plan contract with a typed artifact.**
   Keep human-readable markdown if useful, but make planning/assessment handoff machine-validated first. Primary file: `src/nanobot/evolve/runtime.py:128-218`.

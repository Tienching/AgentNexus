# Assessment — Day 18

## Build/Test Status
- The exact requested assessment command `cd /home/ubuntu/Projects/agent-nexus_feature-dev && python -m pytest tests/ -x -q --tb=short 2>&1 | head -50` returned no output and exit code 0 in this shell, but it is not a reliable health signal here: `python --version` is `Python 2.7.18`, and the pipeline reports `head`'s status instead of pytest's.
- Running the suite with the supported interpreter is red: `python3 -m pytest tests/ -x -q --tb=no` stops at **966 passed, 1 error**.
- `python3 -m pytest tests/ --collect-only -q` reports **1,691 collected tests**.
- The first failure is `tests/unit/test_nexus_ops.py::TestGlobalSearch::test_returns_200`, but the crash happens earlier during `TestClient(app)` startup in `tests/unit/test_nexus_ops.py:10-15`. FastAPI lifespan raises `RuntimeError: Required startup subsystems failed: Task Scheduler (unhealthy): Startup blocked: task executor is disabled` from `src/server/app.py:445-472`.

## Recent Changes (last 3 commits)
- `2b2a3d7` Day 17: session wrap-up
- `0a73139` Day 17: Isolate nexus admin startup from ambient settings [worktree]
- `296a2b3` Day 17: Isolate nexus admin startup from ambient settings

The recent direction is still startup isolation and ambient-state reduction. The journal tail points at the same architectural pressure: startup-policy isolation, prompt/file handoffs in evolution, and shared mutable mission state.

## Codebase Size
- `src/` top level contains five major areas: `channels/`, `nanobot/`, `providers/`, `runtime/`, and `server/`.
- `src/` currently contains **69,790 Python lines** across **268 modules**.
- Requested key-module breakdown:
  - `src/nanobot/mission/`: **11** modules
  - `src/nanobot/cron/`: **3** modules
  - `src/nanobot/agent/`: **17** modules
  - `src/runtime/`: **77** modules
- Key entry points:
  - FastAPI app creation and startup gate: `src/server/app.py:445-472`, `src/server/app.py:656-695`
  - Agent loop: `src/nanobot/agent/loop.py:39`
  - Mission service: `src/nanobot/mission/service.py:24`
  - Mission planner: `src/nanobot/mission/planner.py:115`
  - Mission runner / milestone DAG scheduler: `src/nanobot/mission/runner.py:22`
  - Cron scheduler: `src/nanobot/cron/service.py:63`
  - Runtime task executor: `src/runtime/execution/task_executor.py:39`
  - Self-evolution engine: `src/nanobot/evolve/runtime.py:49`

## Self-Test Results
- `tests/conftest.py:17-42` already provides an isolated `app_factory()` and async client, but `tests/unit/test_nexus_ops.py:10-15` bypasses that path and imports the shared global app.
- `src/server/config.py:49-68` enables both the executor and scheduler by default. In the shared app path, route tests can still inherit ambient startup state instead of only exercising the endpoint under test.
- `src/server/app.py:445-472` now correctly refuses startup when required subsystems are unhealthy. That is good production behavior, but it currently breaks a unit-style route test that assumes startup will always succeed.
- Error handling exists in the core services: mission runner failures are persisted by `src/nanobot/mission/service.py:187-202`, cron store load failures are captured in `src/nanobot/cron/service.py:82-151`, and executor timeout/cancel/error paths are handled in `src/runtime/execution/task_executor.py:224-257`. The weak spot is test-time startup isolation, not total absence of error handling.

## Capability Gaps
1. **Test isolation still lags startup policy.**
   - Evidence: the failing `nexus_ops` test imports the shared app directly while the repo already has `app_factory()` for isolated startup.
   - Impact: route tests validate environment boot state before they validate endpoint behavior.

2. **Self-evolution verification can report false green.**
   - Evidence: the assessment prompt still hardcodes `python -m pytest ... | head -50` in `src/nanobot/evolve/prompts.py:20`; in this environment `python` is 2.7.18 and the pipe masks pytest's exit status.
   - Impact: autonomous assessment can misread a red suite as healthy.

3. **Server mission integration still uses shared mutable state.**
   - Evidence: `MissionBridge` is a singleton in `src/server/services/mission_bridge.py:24-45` and mutates one service instance in place when workspaces change in `src/server/services/mission_bridge.py:70-123`.
   - Impact: concurrent multi-workspace or multi-request use still carries contention risk.

4. **API/runtime surface is larger than its quality gates and formal docs.**
   - Evidence: version surfaces are split between `src/runtime/__init__.py:18` (`0.1.0`) and `src/nanobot/__init__.py:5` (`0.1.4.post5`); coverage tooling exists in `pyproject.toml:35-38` and `pyproject.toml:83-88`, but `pytest.ini:1-12` sets no coverage threshold; formal docs under `docs/` are only `docs/superpowers/specs/2026-03-31-nanobot-merge-design.md` and `docs/superpowers/plans/2026-03-31-nanobot-source-merge.md`.
   - Impact: API stability and operator expectations are harder to reason about than the code size suggests.

## Known Issues
- A broad `TODO|FIXME|HACK` scan mostly hits `TaskStatus.TODO` strings and prompt text, not real unresolved comment debt. Real `FIXME`/`HACK` markers are effectively absent from `src/`.
- One real stale instruction remains in the evolution assessment prompt: `src/nanobot/evolve/prompts.py:20` still tells the system to run bare `python -m pytest`.
- One confirmed current regression remains: `tests/unit/test_nexus_ops.py:27` fails because shared-app startup now aborts in `src/server/app.py:469-472` when the task scheduler is unhealthy.
- Documentation is usable but thinly formalized: root READMEs and identity/journal files exist, but `docs/` currently contains only two design markdown files.

## Recommended Focus
1. **Make endpoint tests hermetic by default.**
   Update `tests/unit/test_nexus_ops.py:10-15` to use `tests/conftest.py:17-42` patterns or equivalent startup overrides, so route tests stop depending on ambient executor/scheduler state.

2. **Fix self-evolution verification commands.**
   Replace bare `python` and pipe-masked health checks in `src/nanobot/evolve/prompts.py:20` and the assessment flow in `src/nanobot/evolve/runtime.py:110-142` so assessment cannot silently pass on a broken suite.

3. **Remove shared mutable mission bridge state.**
   Refactor `src/server/services/mission_bridge.py:24-123` so workspace selection creates or scopes service instances instead of mutating a singleton.

# Assessment — Day 19

## Build/Test Status
- The exact requested assessment command is not a valid health check in this environment: `python -m pytest tests/ -x -q --tb=short 2>&1 | head -50` prints `/usr/bin/python: No module named pytest`, because `python` resolves to Python 2.7 here. The pipe also returns `head`'s exit status, so the command can look green while pytest never ran. This mismatch is still encoded in the evolution assessment prompt at `src/nanobot/evolve/prompts.py:20`.
- Using the supported interpreter, `python3 -m pytest tests/ --collect-only` reports **1694 collected tests**.
- Running `python3 -m pytest tests/ -x --tb=short` is **red**: **993 passed, 1 error** before stopping.

## Recent Changes (last 3 commits)
- `94bd27e` — Day 18: session wrap-up
- `e49206f` — Day 18: Scope MissionBridge services per workspace [worktree]
- `94a2090` — Day 18: Hermetic nexus_ops route tests [worktree]

Recent journal history is consistent with those commits. The Day 18 journal tail keeps pointing at the same pressure points: test isolation around app startup, false-green self-evolution verification, MissionBridge state scoping, and API/doc/version drift.

## Codebase Size
- `src/` contains **69,774 Python lines** across **268 modules**.
- Top-level packages: `channels/`, `nanobot/`, `providers/`, `runtime/`, `server/`.
- Requested key-module counts:
  - `src/nanobot/mission/`: **11** modules
  - `src/nanobot/cron/`: **3** modules
  - `src/nanobot/agent/`: **17** modules
  - `src/runtime/`: **77** modules
- Main entry points and orchestration seams:
  - FastAPI app bootstrap and startup policy: `src/server/app.py:137`, `src/server/app.py:656`
  - Agent loop and tool execution core: `src/nanobot/agent/loop.py:39`
  - Mission API surface: `src/nanobot/mission/service.py:24`
  - Mission planning: `src/nanobot/mission/planner.py:115`
  - Mission DAG runner: `src/nanobot/mission/runner.py:22`
  - Cron scheduler: `src/nanobot/cron/service.py:63`
  - Runtime task executor: `src/runtime/execution/task_executor.py:39`
  - Self-evolution runtime: `src/nanobot/evolve/runtime.py:49`
  - Evolution lifecycle glue: `src/server/services/evolution_service.py:39`

## Self-Test Results
- The first failing test is `tests/unit/test_nexus_runtimes.py::TestAgentRuntimes::test_returns_200`, but the failure happens during `TestClient(app)` startup, not inside the route handler itself: `tests/unit/test_nexus_runtimes.py:16-19`.
- Root cause: the shared FastAPI app refuses startup when the scheduler is considered required but the executor is disabled. That path is explicit in `src/server/app.py:247-273`, and the fatal startup gate is enforced in `src/server/app.py:463-472`.
- The runtime-detection endpoint itself is small and straightforward (`src/server/routers/nexus_runtimes.py:61-98`), so the current breakage is a startup/test-fixture isolation issue, not evidence that runtime detection logic is fundamentally broken.
- Core orchestration paths are present and reasonably mature:
  - missions persist failures in `src/nanobot/mission/service.py:187-202`
  - cron load degradation is surfaced in `src/nanobot/cron/service.py:139-145` and `src/nanobot/cron/service.py:417-426`
  - task execution handles timeout/cancel/error states in `src/runtime/execution/task_executor.py:224-292`
- The mission stack is featureful: planning supports milestone/task DAGs in `src/nanobot/mission/planner.py:163-345`, and execution supports parallel milestone scheduling plus replanning in `src/nanobot/mission/runner.py:84-234`.

## Capability Gaps
1. **Self-evolution still evaluates the repo with the wrong test contract.**
   The assessment template still hardcodes bare `python -m pytest ... | head -50` in `src/nanobot/evolve/prompts.py:20`. In this repo that means Python 2.7, masked exit status, and a real chance of false-green assessments.

2. **Route-test isolation is still fragile around startup policy.**
   Production startup behavior is now stricter, which is good, but tests that import the shared `app` still validate ambient subsystem state before they validate endpoint behavior. The failing `nexus_runtimes` test is the clearest example: `tests/unit/test_nexus_runtimes.py:16-19` collides with `src/server/app.py:247-273` and `src/server/app.py:463-472`.

3. **Mission workspace scoping is only partially complete.**
   `MissionBridge.plan()` and `MissionBridge.start()` fetch workspace-specific services (`src/server/services/mission_bridge.py:88-108`), but follow-up operations like `approve()`, `status()`, `list_missions()`, `cancel()`, `pause()`, `resume()`, and log access go back through the default singleton service (`src/server/services/mission_bridge.py:110-166`). That leaves multi-workspace mission lifecycle operations incomplete.

4. **API/runtime identity is still inconsistent, and formal docs are thin for the surface area.**
   `src/runtime/__init__.py:18` reports `0.1.0`, while `src/nanobot/__init__.py:5` reports `0.1.4.post5`. Meanwhile formal docs under `docs/` are only two design markdown files. For a platform with 268 Python modules and a broad router/runtime surface, the compatibility story is still implicit.

5. **Cron failure handling is durable enough to stay up, but still lossy under corrupted state.**
   If the cron JSON store cannot be parsed, `CronService` logs the error and falls back to an empty in-memory store in `src/nanobot/cron/service.py:139-145`. The service remains available, but persisted schedules effectively disappear until operators inspect `load_error`.

## Known Issues
- A `TODO|FIXME|HACK` scan of `src/` found **no substantial unresolved comment debt**. Most hits are false positives from the literal enum name `TaskStatus.TODO` or from embedded prompt text, not active engineering markers.
- One confirmed current regression is the failing runtime route test: `tests/unit/test_nexus_runtimes.py:16-19` imports the shared app, and startup aborts with `RuntimeError: Required startup subsystems failed: Task Scheduler (unhealthy): Startup blocked: task executor is disabled` from `src/server/app.py:469-472`.
- One confirmed self-evolution issue remains in source: the embedded assessment prompt at `src/nanobot/evolve/prompts.py:20` still instructs the system to use the broken pytest command.
- One likely functional bug remains in mission operations across workspaces: `src/server/services/mission_bridge.py:88-108` is workspace-aware for creation, but `src/server/services/mission_bridge.py:110-166` is not.
- Documentation is sparse relative to the platform size: only `docs/superpowers/specs/2026-03-31-nanobot-merge-design.md:1` and `docs/superpowers/plans/2026-03-31-nanobot-source-merge.md:1` exist under `docs/`.

## Recommended Focus
1. **Fix the failing runtime-route test path first.**
   Make `tests/unit/test_nexus_runtimes.py:16-19` use an isolated app factory or startup-policy overrides so endpoint tests stop depending on executor/scheduler boot state.

2. **Correct the self-evolution verification command.**
   Update the assessment prompt in `src/nanobot/evolve/prompts.py:20` so autonomous assessment uses the supported interpreter and preserves pytest failure status.

3. **Finish workspace-aware mission lifecycle handling.**
   Refactor `src/server/services/mission_bridge.py:88-166` so mission approval, status, pause/resume, cancellation, and log reads are scoped to the same workspace service that created the mission.

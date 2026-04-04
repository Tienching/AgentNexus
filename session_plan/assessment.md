# Assessment — Day 12

## Build/Test Status
- The exact requested self-test command fails immediately in this environment: `/usr/bin/python: No module named pytest`.
- Running the same suite with the usable interpreter passes cleanly: `python3 -m pytest tests/ -x -q --tb=short` collected **1676** tests and passed **1676/1676** on Python 3.10.12.
- Pytest also warns that `pytest.ini` is active while `[tool.pytest.ini_options]` in `pyproject.toml` is ignored.
- Bottom line: the codebase is green, but the default self-test entrypoint is still brittle.

## Recent Changes (last 3 commits)
- `b95085d` Day 11: session wrap-up
- `daec6f0` Day 11: Remove evolution router dependence on private service state [worktree]
- `6e10ea6` Day 11: Replace mission router private bridge accessors [worktree]
- Recent history and `JOURNAL.md` point in the same direction: tighten API boundaries and expose more operational state instead of reaching into internals.

## Codebase Size
- `src/` contains **69,516** Python lines across **268** modules.
- Requested key-module counts:
  - `src/nanobot/mission/`: **11** modules
  - `src/nanobot/cron/`: **3** modules
  - `src/nanobot/agent/`: **17** modules
  - `src/runtime/`: **77** modules
- Top-level package spread is large but coherent: `server` 70 modules, `nanobot` 70, `runtime` 77, `providers` 35, `channels` 16.
- Key entry points:
  - FastAPI bootstrap: `src/server/app.py:97`
  - CLI entrypoint: `src/runtime/plugins/cli/__init__.py:51`
  - Agent loop: `src/nanobot/agent/loop.py:39`
  - Mission orchestration: `src/nanobot/mission/service.py:24`, `src/nanobot/mission/planner.py:115`, `src/nanobot/mission/runner.py:22`
  - Cron service: `src/nanobot/cron/service.py:63`
  - Runtime scheduler: `src/runtime/execution/scheduler.py:49`

## Self-Test Results
- Test breadth is strong. The passing run covered evolve flows, integration APIs, provider routing, channels, missions, health checks, runtimes, task execution, task storage, and worktree behavior.
- No failing tests surfaced on the Python 3 run.
- The architecture is substantial, not placeholder code:
  - `src/server/app.py:97` wires executor, scheduler, channel service, terminal manager, and evolution service during lifespan startup.
  - `src/nanobot/agent/loop.py:39` manages sessions, tools, MCP connections, mission/cron tools, and concurrent message dispatch.
  - `src/nanobot/mission/planner.py:211` validates milestone/task dependency graphs, and `src/nanobot/mission/runner.py:47` executes milestones with DAG scheduling, retries, replanning, and validation commands.
- The main self-test weakness is not test failure; it is that the built-in assessment prompt still tells the system to run the broken bare-`python` command in `src/nanobot/evolve/prompts.py:20`.

## Capability Gaps
1. **Self-evolution verification is still environment-unsafe.**
   - The assessment template hardcodes `python -m pytest ...` in `src/nanobot/evolve/prompts.py:20`.
   - In this environment that command fails before tests start, while `python3 -m pytest ...` passes all 1676 tests.
   - Result: agent-nexus can still misclassify a healthy repo as failing during autonomous assessment.

2. **Packaging/runtime metadata is out of sync with the source tree.**
   - `pyproject.toml:6` declares `requires-python = ">=3.11"`, but the passing suite ran on Python 3.10.12.
   - The wheel target lists `src/core` and `src/protocols` in `pyproject.toml:92`, but those directories do not exist in this checkout.
   - The same wheel target omits `src/nanobot`, even though `nanobot` is a core package with 70 modules.
   - This suggests editable/source checkout is healthier than packaged install, which is a real DX and release gap.

3. **Version and public-surface metadata are still duplicated.**
   - `0.1.0` appears separately in `src/runtime/__init__.py:18`, `src/runtime/plugins/cli/__init__.py:35`, `src/server/app.py:396`, `src/server/routers/health.py:283`, and `src/server/services/run_service.py:37`.
   - Mission and evolution routers are more strongly typed now (`src/server/routers/nexus_missions.py:26`, `src/server/routers/nexus_evolution.py:20`), which is good progress.
   - But there is still no single source of truth for versioning or compatibility metadata across API, CLI, and runtime layers.

4. **Quality gates emphasize breadth, not coverage policy or config coherence.**
   - The suite is large and healthy, which is a strength.
   - But coverage is only configured in `pyproject.toml:88`; `pytest.ini:1` does not enforce coverage thresholds, and pytest warns that pyproject pytest options are ignored.
   - That means test breadth is high, but the default quality gate still does not define how much coverage is enough.

5. **Startup error handling is more observable, but still intentionally permissive.**
   - `src/server/app.py:123`, `src/server/app.py:206`, `src/server/app.py:238`, `src/server/app.py:284`, and `src/server/app.py:312` catch startup failures per subsystem and keep the process alive.
   - `src/server/routers/health.py:204` and `src/server/routers/health.py:263` now surface startup subsystem state, which is a real improvement over previous days.
   - But required services can still fail while the API process remains up, so deployment semantics are still “degraded but running,” not “fail fast on broken core subsystems.”

6. **The self-evolution control plane is still file-contract driven.**
   - `src/nanobot/evolve/runtime.py:110` expects assessment output to land in `session_plan/assessment.md`.
   - `src/nanobot/evolve/runtime.py:162` then discovers `task_*.md` files and parses them line-by-line.
   - If planning emits nothing usable, `src/nanobot/evolve/runtime.py:169` falls back to a generic catch-all task.
   - Flexible, but weakly typed and vulnerable to prompt/output drift.

## Known Issues
- The `TODO/FIXME/HACK` scan found very little actionable comment debt. Most hits are false positives from the literal `TaskStatus.TODO` state in runtime task code, not unfinished implementation work.
- The clearest functional issue discovered today is the broken assessment test command embedded in `src/nanobot/evolve/prompts.py:20`.
- `pyproject.toml:92` still points the wheel build at nonexistent `src/core` and `src/protocols` packages while omitting `src/nanobot`, which is an obvious packaging bug.
- Pytest prints `ignoring pytest config in pyproject.toml!`, confirming test configuration drift between `pytest.ini` and `pyproject.toml`.
- `src/nanobot/skills/skill-creator/scripts/quick_validate.py` still contains placeholder-text checks, so documentation quality at skill-generation time still relies on manual cleanup rather than stronger structural validation.

## Recommended Focus
1. **Fix interpreter/test command resolution for self-evolution.**
   - Make one supported pytest command authoritative and use it in assessment, planning, implementation, and conflict-resolution prompts.

2. **Repair packaging metadata before feature work.**
   - Align `requires-python`, wheel package targets, and the actual source tree so the published/installable artifact matches what the tests validate.

3. **Unify core contracts.**
   - Move version metadata and pytest config to single sources of truth, then replace markdown-only evolution control artifacts with a typed manifest path to reduce prompt drift.

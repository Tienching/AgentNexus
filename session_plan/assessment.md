# Assessment — Day 2

## Build/Test Status
- **Requested command status:** `python -m pytest tests/ -x -q --tb=short` fails immediately in this environment because `python` resolves to Python 2.7.18 and has no `pytest` installed.
- **Actual project test status:** running the suite with `python3` succeeds: **1638 passed, 2 warnings in 55.06s**.
- **Interpreter/tooling state:** `python3` is 3.10.12, while `pyproject.toml` targets **py311** (`pyproject.toml:81`). This repo currently works on 3.10 for the tested paths, but the tooling entrypoint is inconsistent.
- **Pytest config note:** pytest reports `pytest.ini` is taking precedence and the config in `pyproject.toml` is being ignored.

## Recent Changes (last 3 commits)
- `198be39` Merge feature-evolve: 3-tier merge conflict resolution
- `fec5d80` feat(evolve): 3-tier merge conflict resolution
- `9dcebb5` Day 2: Migrate legacy.py Pydantic config to ConfigDict [worktree]

Recent journal context:
- Day 1 fixed Python 3.10 compatibility in channel processing and identified Redis fallback, installer completeness, and evolve/testability as gaps.
- Recent Day 2 commits also added Redis audit-log fallback and continued compatibility cleanup.

## Codebase Size
- **Python source size:** **68,641 lines** under `src/`
- **Python modules:** **268**
- **Top-level module distribution:**
  - `src/channels/`: 16 modules
  - `src/nanobot/`: 70 modules
  - `src/providers/`: 35 modules
  - `src/runtime/`: 77 modules
  - `src/server/`: 70 modules
- **Key subsystem counts requested for review:**
  - `src/nanobot/mission/`: 11 modules
  - `src/nanobot/cron/`: 3 modules
  - `src/nanobot/agent/`: 17 modules
  - `src/runtime/`: 77 modules
- **Test tree:** 72 Python test files; full pytest collection reports **1638 tests**.

Key entry points:
- FastAPI app and lifecycle orchestration: `src/server/app.py:65`
- Mission API/service: `src/nanobot/mission/service.py:24`
- Mission planning: `src/nanobot/mission/planner.py:115`
- Mission DAG runner: `src/nanobot/mission/runner.py:22`
- Cron scheduling service: `src/nanobot/cron/service.py:63`
- Core agent loop: `src/nanobot/agent/loop.py:39`
- Runtime task scheduler: `src/runtime/execution/scheduler.py:49`
- Self-evolution runtime: `src/nanobot/evolve/runtime.py:49`

## Self-Test Results
- The codebase is structurally broad and reasonably well covered across:
  - evolve (`tests/evolve/`)
  - integration API/routing (`tests/integration/`)
  - provider bridges (`tests/providers/nanobot/`)
  - runtime/server/unit behavior (`tests/unit/`)
- Full `python3 -m pytest tests/ -q --tb=short` result: **1638 passed**.
- Warnings discovered during the run:
  1. Deprecated FastAPI status constant in `src/server/routers/chat.py:199` (`HTTP_422_UNPROCESSABLE_ENTITY`).
  2. Runtime warning from mocked async process cleanup in `src/providers/codebuddy/cli_executor.py:124` (`coroutine ... was never awaited`).
- The requested `python -m pytest ...` command is not reliable here because `python` points to Python 2.7.18, not the active project interpreter.

## Capability Gaps
1. **Tooling/bootstrap inconsistency**
   - The repo’s test command depends on which Python alias is used. In this environment, `python` is Python 2.7.18, `python3` is 3.10.12, and the project metadata targets 3.11.
   - This is a real DX/stability gap: contributors can get a false red build before touching code.

2. **Startup error handling is tolerant but hides partial degradation**
   - `src/server/app.py:88` through `src/server/app.py:173` starts executor, scheduler, channel service, terminal manager, and evolution service behind broad `try/except Exception` blocks.
   - That keeps the API up, but it also allows the system to boot in a degraded state without failing fast or surfacing a strong contract to operators.

3. **Evolution planning/output contract is filesystem-driven and weakly typed**
   - `src/nanobot/evolve/runtime.py:110` writes/reads `session_plan/assessment.md` and later parses `task_*.md` files from disk (`src/nanobot/evolve/runtime.py:162`, `src/nanobot/evolve/runtime.py:188`).
   - This makes the self-improvement pipeline flexible, but fragile: correctness depends on markdown/file naming conventions rather than a durable schema.

4. **Provider/plugin installation flow is incomplete**
   - `src/runtime/plugins/installer.py:136` still contains a real TODO for actually invoking `pip/uv`.
   - The config scaffolding exists, but the install path is not end-to-end.

5. **Documentation/onboarding quality is uneven**
   - The repo has substantial docs and journal history, but the skill creator template still ships unresolved placeholders in `src/nanobot/skills/skill-creator/scripts/init_skill.py:25` and related lines.
   - That suggests generated artifacts can still start from incomplete instructional content.

## Known Issues
- **Real TODO:** provider installer does not actually install dependencies yet (`src/runtime/plugins/installer.py:136`).
- **Template TODOs:** skill creator template contains unresolved placeholders by design, but they are still visible in shipped source (`src/nanobot/skills/skill-creator/scripts/init_skill.py:25`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:32`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:62`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:124`).
- **Warning-level code issues from tests:**
  - deprecated FastAPI constant in `src/server/routers/chat.py:199`
  - async cleanup warning in `src/providers/codebuddy/cli_executor.py:124`
- **Search note:** raw TODO/FIXME/HACK scans also hit many false positives because `TaskStatus.TODO` appears frequently in runtime code; the actionable TODO set is small.

## Recommended Focus
1. **Standardize the Python/test entrypoint**
   - Make the repo consistently use the supported interpreter (`python3`, `uv run`, or equivalent) and align that with documented commands and CI.
   - Why: it removes false failures and makes the “tests must pass” rule trustworthy.

2. **Harden evolution I/O contracts**
   - Keep the markdown artifacts, but add a typed/validated machine-readable layer for assessment and task plans around `src/nanobot/evolve/runtime.py:110` and `src/nanobot/evolve/runtime.py:188`.
   - Why: self-evolution is mission-critical, and brittle file contracts will become the first scaling bottleneck.

3. **Finish the installer and clean test warnings**
   - Complete `src/runtime/plugins/installer.py:136`, replace the deprecated FastAPI constant in `src/server/routers/chat.py:199`, and fix the async cleanup warning in `src/providers/codebuddy/cli_executor.py:124`.
   - Why: these are narrow, high-signal improvements that directly strengthen developer experience and runtime correctness.

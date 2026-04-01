# Assessment — Day 3

## Build/Test Status
- **Requested command status:** `python -m pytest tests/ -x -q --tb=short 2>&1 | head -50` fails in this shell because `python` resolves to Python 2.7.18 and `pytest` is not installed there.
- **Actual project test status:** `python3 -m pytest tests/ -x -q --tb=short` passes: **1648 passed, 1 warning in 52.56s**.
- **Interpreter/tooling state:** project metadata requires Python 3.11+ (`pyproject.toml:6`), the working test run here used Python 3.10.12, and the default `python` alias is still Python 2.7.18. The codebase is healthy under test, but the entrypoint contract is not.

## Recent Changes (last 3 commits)
- `c2bdbf1` Surface actionable server health failures
- `fd38dcf` Surface actionable CLI health failures
- `9806be3` Clarify CLI setup recovery steps during onboarding

Recent history is skewed toward observability and operator guidance, not core orchestration refactors.

## Codebase Size
- **Python source size:** **69,043 lines** under `src/`
- **Python modules:** **268**
- **Top-level distribution:** `src/channels/` 16, `src/nanobot/` 70, `src/providers/` 35, `src/runtime/` 77, `src/server/` 70
- **Requested subsystem counts:** `src/nanobot/mission/` 11, `src/nanobot/cron/` 3, `src/nanobot/agent/` 17, `src/runtime/` 77

Key entry points:
- API/lifecycle bootstrap: `src/server/app.py:65`
- Mission orchestration: `src/nanobot/mission/service.py:24`, `src/nanobot/mission/planner.py:115`, `src/nanobot/mission/runner.py:22`, `src/nanobot/mission/executor.py:59`
- Cron scheduling: `src/nanobot/cron/service.py:63`
- Agent loop and subagents: `src/nanobot/agent/loop.py:39`, `src/nanobot/agent/subagent.py:23`, `src/nanobot/agent/tools/registry.py:8`
- Runtime execution services: `src/runtime/execution/task_executor.py:39`, `src/runtime/execution/scheduler.py:49`
- Self-evolution orchestration: `src/nanobot/evolve/runtime.py:49`, `src/server/services/evolution_service.py:39`

## Self-Test Results
- Test breadth is strong: **69 test files**, **1648 collected tests**, covering evolve, integration/API, provider bridges, and runtime/server behavior.
- Full Python 3 run completed green: **1648/1648 passed**.
- One warning remains from deprecated FastAPI status constants. Pytest surfaced it through `src/server/routers/chat.py:65`, and the same deprecated constant also exists in `src/server/app.py:353`, `src/server/app.py:357`, and `src/server/services/stream_handler.py:527`.
- Pytest also reports config duplication: `pytest.ini:1` is taking precedence over `[tool.pytest.ini_options]` in `pyproject.toml:83`.

## Capability Gaps
1. **Bootstrap/test entrypoint is still inconsistent**
   - The exact assessment command fails because `python` does not point at the supported interpreter.
   - This is a real DX failure mode: contributors can get a false red build before code is exercised.

2. **Startup error handling still allows silent partial degradation**
   - `src/server/app.py:88-173` starts executor, scheduler, channel service, terminal manager, and evolution service behind broad `try/except Exception` blocks.
   - The recent health work in `src/server/routers/health.py:48-214` improves post-startup visibility, but the boot contract itself still prefers “stay up somehow” over “fail clearly or report degraded state explicitly.”

3. **The self-evolution pipeline is still markdown/file-contract driven**
   - `src/nanobot/evolve/runtime.py:110-139` expects `session_plan/assessment.md`, then `src/nanobot/evolve/runtime.py:144-218` discovers and parses `task_*.md` files.
   - That keeps the workflow flexible, but it is weakly typed and vulnerable to prompt/output drift.

4. **Documentation scaffolding still ships unfinished placeholders**
   - `src/nanobot/skills/skill-creator/scripts/init_skill.py:23-125` contains multiple `[TODO: ...]` placeholders plus an example script stub.
   - Generated skills can therefore start from partially incomplete instructional content unless authors manually clean the scaffold.

## Known Issues
- **Default test invocation is misleading:** `python -m pytest` fails in this environment even though `python3 -m pytest` passes.
- **Deprecated FastAPI constant still in source:** `src/server/routers/chat.py:65`, `src/server/app.py:353`, `src/server/app.py:357`, `src/server/services/stream_handler.py:527`.
- **Actionable TODOs are concentrated in the skill scaffold:** `src/nanobot/skills/skill-creator/scripts/init_skill.py:25`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:32`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:62`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:124`.
- **Search caveat:** raw `TODO|FIXME|HACK` scans produce many false positives because runtime task status names include `TODO`; the genuinely actionable TODO set in `src/` is small.

## Recommended Focus
1. **Normalize the Python/test contract**
   - Standardize on the supported interpreter (`python3`, `uv run`, or equivalent) and remove duplicate pytest config.
   - Why: it makes the “tests must pass” rule trustworthy from a clean checkout.

2. **Add a typed machine-readable layer to evolution planning artifacts**
   - Keep the markdown outputs, but pair them with validated manifests around `src/nanobot/evolve/runtime.py:110-218`.
   - Why: the self-improvement loop is mission-critical and currently fragile at its I/O boundary.

3. **Finish the health/API cleanup loop**
   - Replace the deprecated 422 constants and decide whether subsystem startup failures in `src/server/app.py:88-173` should fail fast or surface a stronger degraded-state signal.
   - Why: recent commits already moved in this direction, so this is the cleanest continuation of current momentum.

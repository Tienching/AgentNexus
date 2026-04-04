# Evolution Journal

*This file records every evolution session. Never delete entries.*

---

## Session 1 — 2026-03-31 12:14 UTC

**Duration:** 589s

**Tasks:** 1 completed, 0 failed


### Completed

- Fix asyncio.timeout Python 3.10 compatibility in channel_service.py

### Gaps Identified
1. **Python version compatibility**: Code uses `asyncio.timeout()` (Python 3.11+) but the runtime is Python 3.10. This silently breaks channel message processing for tool calls.

2. **Redis dependency without graceful degradation**: Audit log and some session storage features hard-depend on Redis. Tests that touch these paths fail in Redis-free environments. The audit log has no in-memory fallback.

3. **Incomplete installer**: `src/runtime/plugins/installer.py:136` has `# TODO: 实际调用 pip/uv 安装` — skill package installation is stubbed.

4. **Pydantic V1 legacy model**: `src/server/models/legacy.py` uses deprecated class-based config. Will break on Pydantic V3.

5. **Test coverage for evolve engine**: The evolution engine (`src/nanobot/evolve/engine.py`) contains template text with TODO placeholders (it's a prompt template, not a code gap — but worth noting the engine is prompt-driven with no dry-run mode).

---

---

## Session 2 — 2026-04-01 08:00 UTC

**Duration:** 1187s

**Tasks:** 2 completed, 1 failed


### Completed

- Complete provider installer execution path
- Fix Codebuddy timeout cleanup warning

### Failed

- Add validated evolution task manifest parsing: All merge strategies failed: error: Your local changes to the following files would be overwritten by merge:
	src/nanobot/evolve/engine.py
	src/nanobot/evolve/models.py
Please commit your changes or stash them before you merge.
A

### Gaps Identified
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

---

## Session 3 — 2026-04-01 16:00 UTC

**Duration:** 1045s

**Tasks:** 1 completed, 2 failed


### Completed

- Replace deprecated FastAPI 422 constants

### Failed

- Add typed JSON manifest support for evolution planning: All merge strategies failed: error: Your local changes to the following files would be overwritten by merge:
	src/nanobot/evolve/engine.py
Please commit your changes or stash them before you merge.
Aborting

- Use the supported pytest interpreter in evolve prompts: All merge strategies failed: error: Your local changes to the following files would be overwritten by merge:
	src/nanobot/evolve/engine.py
Please commit your changes or stash them before you merge.
error: The following untracked 

### Gaps Identified
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

---

## Session 4 — 2026-04-02 00:00 UTC

**Duration:** 846s

**Tasks:** 1 completed, 2 failed


### Completed

- Surface cron store corruption as degraded service state

### Failed

- Align evolve pytest commands with the supported interpreter: All merge strategies failed: error: Your local changes to the following files would be overwritten by merge:
	src/nanobot/evolve/engine.py
Please commit your changes or stash them before you merge.
error: The following untracked 
- Emit a typed manifest for planned evolution tasks: All merge strategies failed: error: Your local changes to the following files would be overwritten by merge:
	src/nanobot/evolve/engine.py
	src/nanobot/evolve/models.py
Please commit your changes or stash them before you merge.
A

### Gaps Identified
1. **Self-evolution still uses the wrong test command**
   - The system that evaluates and improves the repo is wired to `python -m pytest`, not the interpreter that actually works here (`src/nanobot/evolve/prompts.py:20`, `src/nanobot/evolve/implementation.py:409`).
   - This directly undermines autonomous reliability: the platform can misclassify a healthy codebase as failing.

2. **Startup error handling still prefers “stay up” over a strong degraded-state contract**
   - `src/server/app.py:88` through `src/server/app.py:173` wraps executor, scheduler, channel service, terminal manager, and evolution startup in broad `try/except Exception` blocks.
   - `src/server/routers/health.py:195` improves visibility after boot, but the process can still come up partially broken without a hard failure or explicit startup-state surface.

3. **Evolution planning/output is still markdown-file driven instead of strongly typed**
   - `src/nanobot/evolve/runtime.py:110` expects `session_plan/assessment.md`, and `src/nanobot/evolve/runtime.py:144` through `src/nanobot/evolve/runtime.py:218` discovers and parses `task_*.md` files.
   - This is flexible, but fragile. Correctness depends on prompt format and filename conventions rather than a validated schema.

4. **Cron persistence failure handling is tolerant but lossy**
   - If cron store loading fails, `src/nanobot/cron/service.py:90` through `src/nanobot/cron/service.py:137` logs a warning and falls back to an empty `CronStore()`.
   - That keeps the service alive, but it also means malformed or corrupted schedule state can silently collapse into “no jobs loaded.”

5. **Documentation scaffolding still ships unfinished placeholders**
   - The generated skill template in `src/nanobot/skills/skill-creator/scripts/init_skill.py:25` and `src/nanobot/skills/skill-creator/scripts/init_skill.py:62` still contains multiple `[TODO: ...]` placeholders and example-only content.
   - That weakens documentation quality at the point new capabilities are created.

6. **API compatibility remains implicit rather than explicit**
   - The FastAPI app mounts a broad router set directly in `src/server/app.py:244`, while version metadata is repeated as string literals in `src/server/app.py:221` and `src/server/routers/health.py:208`.
   - The platform has a sizeable API surface, but no clear in-code versioning boundary or compatibility contract.

---

## Session 5 — 2026-04-02 08:00 UTC

**Duration:** 17s

**Tasks:** 0 completed, 3 failed


### Failed

- Align evolve pytest commands with the supported interpreter: No commits produced
- Emit a typed manifest for planned evolution tasks: No commits produced
- Surface cron store corruption as degraded service state: No commits produced

### Gaps Identified
1. **Self-evolution still uses the wrong test command**
   - The system that evaluates and improves the repo is wired to `python -m pytest`, not the interpreter that actually works here (`src/nanobot/evolve/prompts.py:20`, `src/nanobot/evolve/implementation.py:409`).
   - This directly undermines autonomous reliability: the platform can misclassify a healthy codebase as failing.

2. **Startup error handling still prefers “stay up” over a strong degraded-state contract**
   - `src/server/app.py:88` through `src/server/app.py:173` wraps executor, scheduler, channel service, terminal manager, and evolution startup in broad `try/except Exception` blocks.
   - `src/server/routers/health.py:195` improves visibility after boot, but the process can still come up partially broken without a hard failure or explicit startup-state surface.

3. **Evolution planning/output is still markdown-file driven instead of strongly typed**
   - `src/nanobot/evolve/runtime.py:110` expects `session_plan/assessment.md`, and `src/nanobot/evolve/runtime.py:144` through `src/nanobot/evolve/runtime.py:218` discovers and parses `task_*.md` files.
   - This is flexible, but fragile. Correctness depends on prompt format and filename conventions rather than a validated schema.

4. **Cron persistence failure handling is tolerant but lossy**
   - If cron store loading fails, `src/nanobot/cron/service.py:90` through `src/nanobot/cron/service.py:137` logs a warning and falls back to an empty `CronStore()`.
   - That keeps the service alive, but it also means malformed or corrupted schedule state can silently collapse into “no jobs loaded.”

5. **Documentation scaffolding still ships unfinished placeholders**
   - The generated skill template in `src/nanobot/skills/skill-creator/scripts/init_skill.py:25` and `src/nanobot/skills/skill-creator/scripts/init_skill.py:62` still contains multiple `[TODO: ...]` placeholders and example-only content.
   - That weakens documentation quality at the point new capabilities are created.

6. **API compatibility remains implicit rather than explicit**
   - The FastAPI app mounts a broad router set directly in `src/server/app.py:244`, while version metadata is repeated as string literals in `src/server/app.py:221` and `src/server/routers/health.py:208`.
   - The platform has a sizeable API surface, but no clear in-code versioning boundary or compatibility contract.

---

## Session 6 — 2026-04-02 16:00 UTC

**Duration:** 20s

**Tasks:** 0 completed, 3 failed


### Failed

- Align evolve pytest commands with the supported interpreter: No commits produced
- Emit a typed manifest for planned evolution tasks: No commits produced
- Surface cron store corruption as degraded service state: No commits produced

### Gaps Identified
1. **Self-evolution still uses the wrong test command**
   - The system that evaluates and improves the repo is wired to `python -m pytest`, not the interpreter that actually works here (`src/nanobot/evolve/prompts.py:20`, `src/nanobot/evolve/implementation.py:409`).
   - This directly undermines autonomous reliability: the platform can misclassify a healthy codebase as failing.

2. **Startup error handling still prefers “stay up” over a strong degraded-state contract**
   - `src/server/app.py:88` through `src/server/app.py:173` wraps executor, scheduler, channel service, terminal manager, and evolution startup in broad `try/except Exception` blocks.
   - `src/server/routers/health.py:195` improves visibility after boot, but the process can still come up partially broken without a hard failure or explicit startup-state surface.

3. **Evolution planning/output is still markdown-file driven instead of strongly typed**
   - `src/nanobot/evolve/runtime.py:110` expects `session_plan/assessment.md`, and `src/nanobot/evolve/runtime.py:144` through `src/nanobot/evolve/runtime.py:218` discovers and parses `task_*.md` files.
   - This is flexible, but fragile. Correctness depends on prompt format and filename conventions rather than a validated schema.

4. **Cron persistence failure handling is tolerant but lossy**
   - If cron store loading fails, `src/nanobot/cron/service.py:90` through `src/nanobot/cron/service.py:137` logs a warning and falls back to an empty `CronStore()`.
   - That keeps the service alive, but it also means malformed or corrupted schedule state can silently collapse into “no jobs loaded.”

5. **Documentation scaffolding still ships unfinished placeholders**
   - The generated skill template in `src/nanobot/skills/skill-creator/scripts/init_skill.py:25` and `src/nanobot/skills/skill-creator/scripts/init_skill.py:62` still contains multiple `[TODO: ...]` placeholders and example-only content.
   - That weakens documentation quality at the point new capabilities are created.

6. **API compatibility remains implicit rather than explicit**
   - The FastAPI app mounts a broad router set directly in `src/server/app.py:244`, while version metadata is repeated as string literals in `src/server/app.py:221` and `src/server/routers/health.py:208`.
   - The platform has a sizeable API surface, but no clear in-code versioning boundary or compatibility contract.

---

## Session 7 — 2026-04-03 00:00 UTC

**Duration:** 16s

**Tasks:** 0 completed, 3 failed


### Failed

- Align evolve pytest commands with the supported interpreter: No commits produced
- Emit a typed manifest for planned evolution tasks: No commits produced
- Surface cron store corruption as degraded service state: No commits produced

### Gaps Identified
1. **Self-evolution still uses the wrong test command**
   - The system that evaluates and improves the repo is wired to `python -m pytest`, not the interpreter that actually works here (`src/nanobot/evolve/prompts.py:20`, `src/nanobot/evolve/implementation.py:409`).
   - This directly undermines autonomous reliability: the platform can misclassify a healthy codebase as failing.

2. **Startup error handling still prefers “stay up” over a strong degraded-state contract**
   - `src/server/app.py:88` through `src/server/app.py:173` wraps executor, scheduler, channel service, terminal manager, and evolution startup in broad `try/except Exception` blocks.
   - `src/server/routers/health.py:195` improves visibility after boot, but the process can still come up partially broken without a hard failure or explicit startup-state surface.

3. **Evolution planning/output is still markdown-file driven instead of strongly typed**
   - `src/nanobot/evolve/runtime.py:110` expects `session_plan/assessment.md`, and `src/nanobot/evolve/runtime.py:144` through `src/nanobot/evolve/runtime.py:218` discovers and parses `task_*.md` files.
   - This is flexible, but fragile. Correctness depends on prompt format and filename conventions rather than a validated schema.

4. **Cron persistence failure handling is tolerant but lossy**
   - If cron store loading fails, `src/nanobot/cron/service.py:90` through `src/nanobot/cron/service.py:137` logs a warning and falls back to an empty `CronStore()`.
   - That keeps the service alive, but it also means malformed or corrupted schedule state can silently collapse into “no jobs loaded.”

5. **Documentation scaffolding still ships unfinished placeholders**
   - The generated skill template in `src/nanobot/skills/skill-creator/scripts/init_skill.py:25` and `src/nanobot/skills/skill-creator/scripts/init_skill.py:62` still contains multiple `[TODO: ...]` placeholders and example-only content.
   - That weakens documentation quality at the point new capabilities are created.

6. **API compatibility remains implicit rather than explicit**
   - The FastAPI app mounts a broad router set directly in `src/server/app.py:244`, while version metadata is repeated as string literals in `src/server/app.py:221` and `src/server/routers/health.py:208`.
   - The platform has a sizeable API surface, but no clear in-code versioning boundary or compatibility contract.

---

## Session 8 — 2026-04-03 08:00 UTC

**Duration:** 964s

**Tasks:** 1 completed, 2 failed


### Completed

- Make generated skill scaffolds actionable by default

### Failed

- Make evolve prompts use a working pytest interpreter: No commits produced
- Unify pytest command resolution in serial evolve execution: All merge strategies failed: error: Your local changes to the following files would be overwritten by merge:
	src/nanobot/evolve/engine.py
Please commit your changes or stash them before you merge.
Aborting


### Gaps Identified
1. **Self-evolution verification is still not environment-safe**
   - Assessment, planning, implementation, and conflict-resolution prompts still embed `python -m pytest` instead of a resolved working interpreter path (`src/nanobot/evolve/prompts.py:20`, `src/nanobot/evolve/prompts.py:21`, `src/nanobot/evolve/prompts.py:23`).
   - The runtime also hardcodes the same assumption during implementation verification (`src/nanobot/evolve/implementation.py:409`).
   - This is the highest-impact reliability gap because the platform can misjudge its own health.

2. **Startup error handling still allows partial service boot without a strong contract**
   - The FastAPI lifespan starts executor, scheduler, channel service, terminal manager, and evolution service behind broad `try/except Exception` blocks (`src/server/app.py:88`, `src/server/app.py:124`, `src/server/app.py:140`, `src/server/app.py:153`, `src/server/app.py:165`).
   - Health reporting is better than before (`src/server/routers/health.py:195`), but startup can still succeed while important subsystems are missing.

3. **The self-evolution pipeline is still file-and-markdown driven instead of strongly typed**
   - Assessment success is inferred from `session_plan/assessment.md` (`src/nanobot/evolve/runtime.py:110`-`src/nanobot/evolve/runtime.py:139`).
   - Planning then discovers `task_*.md` files and parses them line-by-line (`src/nanobot/evolve/runtime.py:144`-`src/nanobot/evolve/runtime.py:218`).
   - This keeps the workflow flexible, but it is fragile under prompt drift and hard to validate mechanically.

4. **Cron persistence failure handling is explicit now, but still lossy**
   - If the cron store cannot be parsed, the service logs the error, records degraded state, and falls back to an empty in-memory store (`src/nanobot/cron/service.py:92`-`src/nanobot/cron/service.py:145`).
   - Status exposes the degradation (`src/nanobot/cron/service.py:417`-`src/nanobot/cron/service.py:425`), but the operational result is still “jobs disappear until repaired.”

5. **API/version compatibility is still implicit**
   - The service mounts a broad router surface directly in one app module (`src/server/app.py:244`-`src/server/app.py:261`).
   - Version strings are duplicated across the API and CLI (`src/server/app.py:221`, `src/server/routers/health.py:208`, `src/runtime/plugins/cli/__init__.py:35`).
   - There is no single compatibility boundary or shared version source for the public surface.

6. **Documentation quality is good at the top level but uneven at generation points**
   - The repo has real operator docs (`README.md:26`, `README.md:275`), but the skill scaffold still ships unresolved instructional placeholders (`src/nanobot/skills/skill-creator/scripts/init_skill.py:25`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:62`, `src/nanobot/skills/skill-creator/scripts/init_skill.py:124`).
   - That means new capabilities can still start from incomplete docs/templates.

---

## Session 9 — 2026-04-03 16:00 UTC

**Duration:** 995s

**Tasks:** 0 completed, 3 failed


### Failed

- Remove hardcoded pytest interpreter from fallback evolve prompts: All merge strategies failed: error: Your local changes to the following files would be overwritten by merge:
	src/nanobot/evolve/engine.py
Please commit your changes or stash them before you merge.
error: The following untracked 
- Reuse one resolved pytest command in serial evolve execution: All merge strategies failed: error: Your local changes to the following files would be overwritten by merge:
	src/nanobot/evolve/engine.py
Please commit your changes or stash them before you merge.
Aborting

- Accept a typed session plan manifest before markdown fallback: All merge strategies failed: error: Your local changes to the following files would be overwritten by merge:
	src/nanobot/evolve/engine.py
Please commit your changes or stash them before you merge.
Aborting


### Gaps Identified
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

---

## Session 10 — 2026-04-04 00:00 UTC

**Duration:** 839s

**Tasks:** 2 completed, 1 failed


### Completed

- Reject invalid milestone dependency graphs
- Remove remaining scaffold TODO placeholders

### Failed

- Unify pytest command resolution in evolve prompts: All merge strategies failed: error: Your local changes to the following files would be overwritten by merge:
	src/nanobot/evolve/engine.py
Please commit your changes or stash them before you merge.
error: The following untracked 

### Gaps Identified
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

---

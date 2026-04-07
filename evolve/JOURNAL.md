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

## Session 2 — 2026-04-07 08:00 UTC

**Duration:** 885s

**Tasks:** 2 completed, 1 failed


### Completed

- Add JSON serialization helper to StoredMessage and StoredToolCall
- Add TypedDict for AVAILABLE_PROVIDERS in installer.py

### Failed

- Add in-memory fallback for SessionStorage when Redis unavailable: Timed out after 600s

### Gaps Identified
1. **Incomplete skill installer** (`src/runtime/plugins/installer.py:136`) — Has stubbed pip/uv installation code.

2. **Pydantic V1 legacy model** (`src/server/models/legacy.py`) — Uses deprecated class-based config, will break on Pydantic V3.

3. **Redis dependency without graceful degradation** — Audit log and session storage require Redis; no in-memory fallback for development.

4. **Evolve system prompt templates** — The `prompts.py` file contains inline prompt templates; could benefit from externalization for easier tuning.

---

## Session 3 — 2026-04-07 09:00 UTC

**Duration:** 736s

**Tasks:** 2 completed, 1 failed


### Completed

- Migrate ClaudeEvent model from Pydantic V1 class Config to V2 model_config
- Add graceful Redis connection error handling with log-once behavior

### Failed

- Add external prompt file for evolve planning agent: All merge strategies failed: error: The following untracked working tree files would be overwritten by merge:
	evolve/prompts/planning.md
Please move or remove them before you merge.
Aborting


### Gaps Identified
1. **Incomplete skill installer** — `src/runtime/plugins/installer.py:136` has stubbed pip/uv installation code (mentioned in journal)

2. **Redis dependency without graceful degradation** — Session storage and audit log require Redis; no in-memory fallback for development environments (Session 2 attempted this but timed out)

3. **Pydantic V1 legacy model** — `src/server/models/legacy.py` uses deprecated class-based config, will break on Pydantic V3

4. **Evolve prompt externalization** — Prompts are inline in `src/nanobot/evolve/prompts.py`; could benefit from separate files for easier tuning

---

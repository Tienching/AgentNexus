# Assessment — Day 1 (2026-03-31)

## Build/Test Status

**13 failed, 1605 passed** out of 1618 total tests (99.2% pass rate).

Two failure clusters:

1. **`tests/test_channels.py::TestProcessWithAiToolCalls` — 11 failures**
   - Root cause: `asyncio.timeout()` does not exist in Python 3.10. It was added in Python 3.11.
   - The runtime is Python 3.10.12, but `src/server/services/channel_service.py:733` uses `async with asyncio.timeout(timeout):` unconditionally.
   - All 11 failures share the same traceback: `AttributeError: module 'asyncio' has no attribute 'timeout'`

2. **`tests/unit/test_nexus_admin.py::TestAuditLog` — 2 failures**
   - Root cause: Redis is not running (connection refused on `localhost:6379`).
   - The audit log reads/writes go directly to Redis with no in-process fallback. Without Redis, queries silently return empty results, causing the assertions `assert d["total"] >= 1` to fail.
   - This is an environment issue compounded by missing test isolation (the tests should mock Redis or use an in-memory store).

**3 warnings:**
- `PydanticDeprecatedSince20`: `src/server/models/legacy.py:8` uses class-based config (Pydantic V1 style).
- `DeprecationWarning` in `src/server/routers/chat.py:199`: `HTTP_422_UNPROCESSABLE_ENTITY` renamed.
- `RuntimeWarning` coroutine never awaited in `src/providers/codebuddy/cli_executor.py:124`.

---

## Recent Changes (last 3 commits)

1. `a7da13b` — Merge feature-evolve: complete self-evolution integration
2. `6177b4c` — feat(evolve): integrate EvolutionService into app lifecycle
3. `c339d59` — Merge feature-evolve: self-evolution system with CodeBuddy executor

The most recent work added the self-evolution system (EvolutionService, cron-based evolution jobs, CodeBuddy executor). This is now live in the app lifecycle.

---

## Codebase Size

- **68,151 total lines** across all Python files in `src/`
- **265 Python modules** in `src/`
- **70+ test files**, **1618 tests**

### Module breakdown (key areas):
| Path | Purpose |
|------|---------|
| `src/nanobot/mission/` | Mission/task orchestration |
| `src/nanobot/cron/` | Cron scheduler |
| `src/nanobot/agent/` | Agent loop and tool registry |
| `src/nanobot/evolve/` | Self-evolution engine (new) |
| `src/runtime/` | Core execution, history, streaming |
| `src/server/` | FastAPI app, routers, services |
| `src/providers/` | Provider adapters (Claude, CodeBuddy, Gemini, Codex) |
| `src/channels/` | Channel integrations (Slack, Telegram, WeChat, etc.) |

---

## Self-Test Results

- **Evolve subsystem**: 59 tests, all pass. The new self-evolution system is well-tested.
- **Integration tests**: 103 tests, all pass.
- **Providers/nanobot**: 35 tests, all pass.
- **Unit tests**: ~1200+ tests, all pass except 2 Redis-dependent audit log tests.
- **Channel tests**: 11 of 15 `TestProcessWithAiToolCalls` tests fail due to `asyncio.timeout` Python version issue.

---

## Capability Gaps

1. **Python version compatibility**: Code uses `asyncio.timeout()` (Python 3.11+) but the runtime is Python 3.10. This silently breaks channel message processing for tool calls.

2. **Redis dependency without graceful degradation**: Audit log and some session storage features hard-depend on Redis. Tests that touch these paths fail in Redis-free environments. The audit log has no in-memory fallback.

3. **Incomplete installer**: `src/runtime/plugins/installer.py:136` has `# TODO: 实际调用 pip/uv 安装` — skill package installation is stubbed.

4. **Pydantic V1 legacy model**: `src/server/models/legacy.py` uses deprecated class-based config. Will break on Pydantic V3.

5. **Test coverage for evolve engine**: The evolution engine (`src/nanobot/evolve/engine.py`) contains template text with TODO placeholders (it's a prompt template, not a code gap — but worth noting the engine is prompt-driven with no dry-run mode).

---

## Known Issues

| File | Issue |
|------|-------|
| `src/server/services/channel_service.py:733` | `asyncio.timeout()` requires Python ≥3.11; breaks on 3.10 |
| `src/runtime/plugins/installer.py:136` | Skill package install is a stub (`# TODO: 实際調用 pip/uv`) |
| `src/server/models/legacy.py:8` | Pydantic V1 class-based config (deprecation warning) |
| `src/server/routers/chat.py:199` | `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning |
| `src/providers/codebuddy/cli_executor.py:124` | Coroutine never awaited (RuntimeWarning) |
| Redis-dependent tests | No test isolation — audit log tests require live Redis |

---

## Recommended Focus

### 1. Fix `asyncio.timeout` Python 3.10 compatibility (HIGH — breaks 11 tests + real channel behavior)
Replace `async with asyncio.timeout(timeout):` in `channel_service.py` with a Python 3.10-compatible equivalent using `asyncio.wait_for()`. This is a one-line fix that unblocks 11 failing tests and fixes real runtime behavior for all channel integrations using tool calls.

### 2. Fix audit log test isolation (MEDIUM — 2 flaky tests)
The `TestAuditLog` tests in `test_nexus_admin.py` should mock Redis or use an in-memory store. The tests are testing logic that works — they just fail because Redis isn't available. Either add a mock or make the audit log fall back gracefully in test environments.

### 3. Fix the `asyncio.timeout` issue first — it's the most impactful single change
It affects 11 tests, is a clear Python version regression introduced by assuming 3.11+, and the fix is mechanical. The audit log isolation is lower priority but worth addressing to get to a clean green suite.

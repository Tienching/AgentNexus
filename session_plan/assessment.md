# Assessment — Day 2

## Build/Test Status

**2 FAILED, 1629 passed** — test suite runs in 38.59s on Python 3.14.0.

Failing tests:
- `tests/unit/test_nexus_admin.py::TestAuditLog::test_record_and_query`
- `tests/unit/test_nexus_admin.py::TestAuditLog::test_diagnostics_creates_audit_event`

Root cause: Both `record_audit_event()` and `get_audit_log()` in `src/server/routers/nexus_admin.py` hard-depend on Redis (localhost:6379). When Redis is unavailable, `record_audit_event` silently swallows the error (line 91-92), and `get_audit_log` returns `total=0` (line 143-145). Tests record an event then query for it — the event was never stored, so `total` is always 0 in a Redis-free test environment.

Warnings:
- `src/server/models/legacy.py:8` — Pydantic V2 class-based `config` deprecation (will break on Pydantic V3)
- `src/server/routers/chat.py:199` — `HTTP_422_UNPROCESSABLE_ENTITY` deprecated in favor of `HTTP_422_UNPROCESSABLE_CONTENT`
- `src/providers/codebuddy/cli_executor.py:124` — unawaited coroutine `process.kill()` in mock (test-only, RuntimeWarning)

## Recent Changes (last 3 commits)

1. `3a66fc2` — Merge feature-evolve: rename NANOBOT_EVOLUTION__* → EVOLUTION_*
2. `8ecf1c6` — refactor(evolve): rename env vars NANOBOT_EVOLUTION__* → EVOLUTION_*
3. `0db53e2` — Merge feature-evolve: parallel worktree evolution + hourly cron

Day 1 work: `asyncio.timeout` Python 3.10 compatibility fix in channel_service.py, plus evolution system wiring (parallel worktree execution, hourly cron, env var cleanup).

## Codebase Size

- **265 Python files**, **68,463 total lines**
- Modules: `src/channels/` (15 files), `src/providers/` (20 files), `src/runtime/` (50+ files), `src/server/` (40+ files), `src/nanobot/` (remainder)

## Self-Test Results

1629/1631 tests pass. The 2 failures are both in the same class (`TestAuditLog`) and share one root cause: audit log has no in-memory fallback when Redis is unavailable.

Other test areas are healthy: evolve engine (55 tests), integration API (70 tests), channel tests (79 tests), unit tests (850+ tests) all pass.

## Capability Gaps

1. **Audit log: no in-memory fallback** — `record_audit_event` and `get_audit_log` fail silently without Redis. In production this means audit events are silently dropped whenever Redis is down or not configured. This is a data-loss bug, not just a test failure.

2. **Installer stub** — `src/runtime/plugins/installer.py:136` has `# TODO: 实际调用 pip/uv 安装`. Skill package installation is completely unimplemented — provider install silently skips the actual package install step.

3. **Pydantic V2 legacy model** — `src/server/models/legacy.py` uses deprecated class-based config. Will break on Pydantic V3 upgrade.

4. **`process.kill()` not awaited** — `src/providers/codebuddy/cli_executor.py:124` calls `process.kill()` without `await` on an async subprocess. This is a real bug (not just test noise) — the kill never executes in async context.

5. **Evolution engine is prompt-driven with no dry-run mode** — the evolve engine (`src/nanobot/evolve/engine.py`) relies entirely on prompt templates. No dry-run or simulation mode exists for testing evolution runs without actually invoking a subprocess.

## Known Issues

| File | Issue |
|------|-------|
| `src/server/routers/nexus_admin.py:63-92` | `record_audit_event` silently drops events when Redis unavailable |
| `src/server/routers/nexus_admin.py:110-145` | `get_audit_log` returns empty on Redis failure — no in-memory fallback |
| `src/runtime/plugins/installer.py:136` | Provider package install is a no-op stub |
| `src/server/models/legacy.py:8` | Pydantic V2 deprecation warning → future V3 break |
| `src/providers/codebuddy/cli_executor.py:124` | `process.kill()` missing `await` |

## Recommended Focus

**Priority 1 (fixes failing tests + real bug): Add in-memory fallback to audit log**
- `record_audit_event` and `get_audit_log` should use a module-level in-memory deque when Redis is unavailable.
- This fixes both failing tests and prevents silent data loss in production.
- Surgical change — ~30 lines in `src/server/routers/nexus_admin.py`.

**Priority 2 (real async bug): Fix `process.kill()` missing `await`**
- `src/providers/codebuddy/cli_executor.py:124` — subprocess kill never fires in async context.
- Risk: leaked processes when tasks are cancelled or timed out.
- Small fix, high correctness value.

**Priority 3 (future-proofing): Migrate legacy.py to Pydantic ConfigDict**
- One-line fix for `src/server/models/legacy.py:8`.
- Eliminates deprecation warning and prevents V3 breakage.
- Zero risk, zero behavior change.

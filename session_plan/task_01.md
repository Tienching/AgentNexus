Title: Add in-memory fallback to audit log when Redis is unavailable
Files: src/server/routers/nexus_admin.py
Issue: none

The two failing tests (TestAuditLog::test_record_and_query and TestAuditLog::test_diagnostics_creates_audit_event)
both fail because record_audit_event() silently swallows Redis errors (lines 91-92) and get_audit_log() returns
total=0 on Redis failure (lines 143-145). In production this means audit events are silently lost whenever Redis
is down — a data-loss bug, not just a test artifact.

Fix: add a module-level in-memory deque as fallback storage.

Changes to src/server/routers/nexus_admin.py:

1. At module level, add:
   from collections import deque
   _audit_fallback: deque = deque(maxlen=1000)

2. In record_audit_event(): in the except block (currently line 91-92 which just logs and returns),
   instead of silently dropping, append the event dict to _audit_fallback.

3. In get_audit_log(): in the except/fallback block (currently returns total=0), instead read from
   _audit_fallback, apply the same offset/limit slicing, and return the real count and items.

The deque maxlen=1000 caps memory usage. This is intentionally simple — not a replacement for Redis,
just a resilience layer so events are not silently dropped.

Verify:
  python -m pytest tests/unit/test_nexus_admin.py -x -q

Expected: both previously-failing tests now pass. Full suite should show 0 failures.

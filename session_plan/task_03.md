Title: Add tests for redis_client zrevrange and scan_iter operations
Files: tests/unit/test_redis_client.py
Issue: none

## Problem

The existing `test_redis_client.py` only tests connection handling. It doesn't verify that core Redis operations (zrevrange, scan_iter, lset, ltrim) work correctly. The SessionStorage code uses these operations extensively, and the existing MockRedisClient in test_session_storage.py has its own implementation.

## Solution

Add unit tests to `tests/unit/test_redis_client.py` that verify:

1. `zadd()`, `zrem()`, `zrange()`, `zrevrange()` work correctly
2. `sadd()`, `srem()`, `smembers()`, `sismember()` work correctly
3. `scan_iter()` returns matching keys with prefix stripped
4. `lset()` updates value at index
5. `ltrim()` keeps only the specified range

Use a mock Redis client or fake-redis for these tests. These operations are used by:
- Session indexes (zadd, zrem, zrevrange for user session lists)
- Hidden history tracking (sadd, srem, sismember)
- Streaming content cleanup (scan_iter, delete)

## Verification

Run: `python3 -m pytest tests/unit/test_redis_client.py -v`

All tests should pass. The tests should cover the operations used by SessionStorage without requiring a real Redis instance.

Title: Add InMemoryBackend for Redis graceful degradation
Files: src/runtime/stores/redis_client.py, tests/unit/test_redis_client.py
Issue: none

## Problem

Session storage and audit log require Redis. When Redis is unavailable, the system returns None/empty values for most operations, blocking development without a running Redis instance. Multiple sessions (2, 3, 4) attempted to add graceful degradation but timed out trying to do too much at once.

## Solution

Add an `InMemoryBackend` class to `src/runtime/stores/redis_client.py` that:

1. Implements the same interface as RedisClient methods (get, set, hget, hset, hgetall, hdel, rpush, lrange, llen, zadd, zrem, zrevrange, sadd, srem, smembers, sismember, delete, expire, scan_iter, lset, ltrim)
2. Uses module-level dicts for storage: `_memory_store`, `_hashes`, `_lists`, `_sets`, `_sorted_sets`, `_expiry`
3. When Redis connection fails in `__init__`, log a warning once and set a flag `_use_memory_fallback = True`
4. All RedisClient methods check `_use_memory_fallback` first and delegate to InMemoryBackend

This is a small, focused change. Only the redis_client.py file is modified (plus tests). SessionStorage and other consumers continue to work without modification.

## Verification

Run: `python3 -m pytest tests/unit/test_redis_client.py tests/unit/test_session_storage.py -v`

All tests should pass. Additionally, verify the fallback works:
```python
import os
os.environ["REDIS_HOST"] = "invalid-host"
from src.runtime.stores.redis_client import get_redis_client
client = get_redis_client()
assert client.ping() is False  # Falls back to memory
client.set("test", "value")
assert client.get("test") == "value"  # Works with memory backend
```

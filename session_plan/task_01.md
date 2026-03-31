Title: Fix asyncio.timeout Python 3.10 compatibility in channel_service.py
Files: src/server/services/channel_service.py
Issue: none

## Problem

`src/server/services/channel_service.py:733` uses `async with asyncio.timeout(timeout):` which was
added in Python 3.11. The runtime is Python 3.10.12, so this raises:

    AttributeError: module 'asyncio' has no attribute 'timeout'

This breaks all 11 `TestProcessWithAiToolCalls` tests and causes real channel message processing
to fail at runtime whenever a tool call is involved.

## Fix

Replace the `asyncio.timeout()` context manager with `asyncio.wait_for()`, which is available in
Python 3.10 and earlier.

The current pattern wraps an `async for` loop:

```python
async with asyncio.timeout(timeout):
    async for output in executor.execute(...):
        ...
```

`asyncio.wait_for()` does not directly wrap async generators. The idiomatic 3.10-compatible
approach is to wrap the entire body in a coroutine and call `await asyncio.wait_for(coro, timeout)`.

Alternatively, use the backport from `async_timeout` (already likely in dependencies via anyio/
httpx), or simply guard the construction with a version check:

```python
import sys

if sys.version_info >= (3, 11):
    async with asyncio.timeout(timeout):
        async for output in executor.execute(...):
            ...
else:
    # Python 3.10 compatible: collect via a helper coroutine with wait_for
    async def _run():
        async for output in executor.execute(...):
            # [body unchanged]
            ...
    await asyncio.wait_for(_run(), timeout=timeout)
```

The cleanest single-path solution is to extract the loop body into a local async helper and use
`asyncio.wait_for()` unconditionally (it is available on all supported Python versions):

1. Define `async def _process_stream(): ...` containing the full `async for` loop body (lines
   734–end of the try block).
2. Replace `async with asyncio.timeout(timeout): async for ...` with
   `await asyncio.wait_for(_process_stream(), timeout=timeout)`.
3. Remove any `import`-level references to `asyncio.timeout` if present.

## Verification

```
python -m pytest tests/test_channels.py::TestProcessWithAiToolCalls -x -q
```

All 11 previously failing tests should now pass. Full suite regression check:

```
python -m pytest tests/ -x -q
```

Expected result: 13 failures → 2 failures (only the Redis-dependent audit log tests remain red).

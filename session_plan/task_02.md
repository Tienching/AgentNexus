Title: Fix missing await on process.kill() in cli_executor.py
Files: src/providers/codebuddy/cli_executor.py
Issue: none

src/providers/codebuddy/cli_executor.py:124 calls process.kill() without await on an asyncio subprocess.
asyncio.subprocess.Process.kill() is a synchronous method (it sends SIGKILL), but the surrounding code
is async and the missing await causes a RuntimeWarning in tests. More importantly, in async context the
kill may not be properly sequenced with subsequent cleanup (e.g., process.wait()), risking leaked
subprocess handles when tasks are cancelled or timed out.

Fix: inspect line 124 and surrounding context. If process.kill() is followed by process.wait() or
communicate(), ensure the kill call is correct for asyncio.subprocess (kill() is sync, but
process.wait() must be awaited). The likely fix is:
  - If it reads `process.kill()` followed by `await process.wait()`, the kill() itself is fine
    (it's sync), but verify the test mock is not an async mock that returns a coroutine.
  - If the RuntimeWarning comes from a test mock patching kill() with an async function, fix the
    mock to use a sync MagicMock instead of AsyncMock.
  - If the source itself has `await process.kill()` where kill() is sync, remove the await.

Verify by reading the file first, then applying the minimal correct fix.

Verify:
  python -m pytest tests/ -x -q -k "cli_executor"

No RuntimeWarning about unawaited coroutine. Full suite should remain green.

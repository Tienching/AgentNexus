Title: Replace watchdog private runtime coupling
Files: src/server/services/stale_task_watchdog.py, src/runtime/execution/task_executor.py, src/runtime/stores/task_storage.py
Issue: none

Refactor stale-task recovery to stop reaching into runtime internals directly. Add a narrow public accessor on `TaskExecutor` for active task IDs, add public `TaskQueue` helpers that own the status/index/Redis mutations needed to requeue or permanently fail stale tasks, and update `requeue_stale_tasks()` in `src/server/services/stale_task_watchdog.py` to use those APIs instead of `_running_tasks`, `_redis`, and `_update_task_status`.

Why: the Day 13 assessment identified this watchdog path as a fragile cross-layer dependency. Keeping the storage and executor invariants behind public methods makes the scheduler/watchdog flow safer to change without breaking runtime bookkeeping.

Keep behavior unchanged for callers: stale active tasks are still skipped, stale inactive tasks are still requeued or failed with the same counters and messages. Verify with the existing regression suite: `python3 -m pytest tests/unit/test_stale_task_watchdog.py -q`.

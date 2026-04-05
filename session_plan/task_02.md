Title: Persist unexpected mission runner failures
Files: src/nanobot/mission/service.py, tests/unit/test_mission_service.py
Issue: none

Harden `MissionService._run_and_cleanup()` in `src/nanobot/mission/service.py` so an unexpected exception from `runner.run_mission()` does not disappear behind logging alone. In the generic exception branch, mark the mission as failed, capture `mission.error`, append a failure log entry, update `updated_at_ms`, and persist the mission before removing it from `_running_missions`.

Why: the Day 13 assessment found a gap in the mission failure path. If the runner escapes with an unexpected exception, callers can lose the durable failed state even though something went wrong. This task makes failure reporting trustworthy at the service boundary.

Add a focused async regression test in `tests/unit/test_mission_service.py` that stubs `runner.run_mission()` to raise and asserts the stored mission ends in `failed` state with the error recorded. Verify with `python3 -m pytest tests/unit/test_mission_service.py -q`.

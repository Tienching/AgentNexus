Title: Rebind mission runner state for workspace overrides
Files: src/server/services/mission_bridge.py, src/nanobot/mission/runner.py, tests/test_mission_bridge.py
Issue: none

Make workspace selection in `MissionBridge` request-scoped instead of only partially mutating shared service state. Focus on `MissionBridge.plan()` and `MissionBridge.start()` in `src/server/services/mission_bridge.py`: when a caller passes `workspace`, rebind every mission-service dependency that persists workspace state, not just `svc.store`, `svc.planner.workspace`, and `svc.executor.workspace`.

Specifically ensure the `MissionRunner` created in `src/nanobot/mission/runner.py` stays aligned with the active store/workspace after rebinding. The current bridge mutates `MissionService.store`, but `MissionRunner.store` is captured at construction time, so missions can still persist through the original `missions.json` path.

Add a regression test in `tests/test_mission_bridge.py` that exercises workspace overrides and asserts the active service state and runner state both point at the requested workspace before mission planning/execution proceeds.

Verify with: `python3 -m pytest tests/test_mission_bridge.py -q`.

Title: Scope MissionBridge services per workspace
Files: src/server/services/mission_bridge.py, tests/test_mission_bridge.py
Issue: none

Refactor `MissionBridge` so workspace selection does not mutate one singleton `MissionService` instance in place. Replace `_rebind_service_workspace()` and the current `service` / `plan()` / `start()` flow with per-workspace service lookup or caching keyed by workspace path, while keeping the default workspace behavior intact. The important architectural change is that one request choosing a workspace must not rewrite another request’s planner, executor, runner, or store.

Update `tests/test_mission_bridge.py` to assert the new behavior: repeated calls for the same workspace can reuse the same service, different workspaces get isolated service state, and `plan()` / `start()` delegate to the correct service without cross-workspace bleed. Remove or rewrite the current rebinding-specific expectations accordingly.

Verify with:
`python3 -m pytest tests/test_mission_bridge.py -q`

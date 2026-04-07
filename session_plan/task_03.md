Title: Resolve mission actions by owning workspace service
Files: src/server/services/mission_bridge.py, tests/test_mission_bridge.py
Issue: none

Add a small helper in `MissionBridge` to locate the cached `MissionService` that owns a given `mission_id`, then route mission-id lifecycle methods through that service instead of `self.service`. Scope this task to `approve()`, `status()`, `cancel()`, `pause()`, `resume()`, `get_mission_raw()`, `get_log()`, and the payload helpers that build on those methods; keep `list_missions()` out of scope so the change stays small and targeted.

Extend `tests/test_mission_bridge.py` with regression coverage that seeds both the default workspace service and a non-default workspace service, then proves mission actions for a non-default mission do not fall back to the default singleton. This closes the current cross-workspace bleed in follow-up mission operations without redesigning the broader listing API.

Verify with:
`python3 -m pytest tests/test_mission_bridge.py -q`

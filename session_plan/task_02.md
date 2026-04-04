Title: Replace mission router private bridge accessors
Files: src/server/services/mission_bridge.py, src/server/routers/nexus_missions.py, tests/unit/test_nexus_missions.py
Issue: none

Add public mission serialization helpers to `MissionBridge` and switch the missions router to explicit response models instead of raw dicts and `_mission_to_dict` access.

Why: `src/server/routers/nexus_missions.py` currently depends on the bridge's private serializer and returns several untyped payloads. That makes the API contract brittle and blocks safe refactors of the mission service layer.

Change:
- In `src/server/services/mission_bridge.py`, expose public methods for mission detail and mission log/status payloads so the router no longer reaches into private internals.
- In `src/server/routers/nexus_missions.py`, add response models for mission detail, mission status, mission list, and mission log endpoints, and route all responses through the new public bridge methods.
- Cover the new payload shapes and 404 behavior with router-focused tests in `tests/unit/test_nexus_missions.py`.

Verify with `python3 -m pytest tests/unit/test_nexus_missions.py -q`.